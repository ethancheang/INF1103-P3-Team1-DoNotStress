"""DoNotStress entry point: campus UI → I/O → Gemini → Logic → records.

App is the composition root: it creates and owns the four managers and
wires them together. Flask routes live in WebController. App itself never
imports WebController: tests and the `python main.py` entry attach the
controller with WebController(App(...)). This module does not construct a
live App at import time.

Run locally with `python main.py`.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from ai.ai_provider import AIProvider
from ai.gemini_provider import GeminiProvider
from ai_manager import AIManager
from base_manager import BaseManager
from data_manager import DataManager
from io_manager import IOManager
from json_types import JSONObject
from logic_manager import LogicManager
from questionnaire import Questionnaire
from records.check_in_record import CheckInRecord
from records.pending_record import PendingRecord

load_dotenv()


class App:
    """The composition root: creates, owns and connects the four managers.

    IOManager, AIManager, LogicManager and DataManager are created here
    and live exactly as long as the App (composition), as are the worker
    threads that run each check-in in the background. LogicManager's
    instructions() and verify() are lent to AIManager. A provider can
    be passed in (tests pass a FakeProvider); otherwise App creates the
    live GeminiProvider through make_provider().
    """

    ROOT: Path = Path(__file__).resolve().parent
    DEFAULT_DATA_PATH: Path = ROOT / "data" / "student_records.json"
    MAX_CONTENT_LENGTH: int = 64 * 1024
    JOB_TTL_SECONDS: float = 1800
    WORKERS: int = 4

    def __init__(self, provider: AIProvider | None = None,
                 data_path: Path | str | None = None,
                 secret_key: str | None = None, testing: bool = False,
                 ai_max_attempts: int = 3,
                 ai_retry_delay_sec: float | None = None,
                 test_config: dict[str, object] | None = None) -> None:
        self.__logger: logging.Logger = logging.getLogger("main")
        self.__flask: Flask = Flask(__name__, root_path=str(self.ROOT))
        self.__flask.config.update(
            SECRET_KEY=(secret_key or os.environ.get("FLASK_SECRET_KEY")
                        or secrets.token_hex(32)),
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            MAX_CONTENT_LENGTH=self.MAX_CONTENT_LENGTH,
            TESTING=testing,
            DATA_PATH=(str(data_path) if data_path is not None else
                       os.environ.get("DONOTSTRESS_DATA_PATH") or None),
        )
        if test_config:
            self.__flask.config.update(test_config)
            if test_config.get("TESTING"):
                testing = True

        questionnaire = Questionnaire.from_survey()
        self.__questionnaire = questionnaire
        self.__io: IOManager = IOManager(questionnaire)
        self.__logic: LogicManager = LogicManager()
        delay = (0.0 if testing else 0.5) if ai_retry_delay_sec is None else ai_retry_delay_sec
        self.__ai: AIManager = AIManager(
            provider if provider is not None else self.make_provider(),
            questionnaire,
            instructions=self.__logic.instructions,
            verify=self.__logic.verify,
            max_attempts=ai_max_attempts,
            retry_delay_sec=delay,
        )
        configured = self.__flask.config.get("DATA_PATH")
        path = Path(str(configured)) if configured else self.DEFAULT_DATA_PATH
        self.__data: DataManager = DataManager(path)

        self.__save_lock: threading.Lock = threading.Lock()
        self.__jobs_lock: threading.Lock = threading.Lock()
        self.__jobs: dict[str, dict[str, object]] = {}
        self.__submissions: dict[str, dict[str, object]] = {}
        self.__executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=self.WORKERS, thread_name_prefix="checkin")
        self.__executor_stopped: bool = False
        self.__flask.extensions["dns_app"] = self

    @staticmethod
    def make_provider() -> AIProvider:
        """The live Gemini provider. Tests pass a different AIProvider in."""
        return GeminiProvider()

    @property
    def flask(self) -> Flask:
        return self.__flask

    def health(self) -> JSONObject:
        """Every manager's health summary. Never includes secrets."""
        return {"status": "ok",
                "managers": [manager.health() for manager in self.managers]}

    @property
    def managers(self) -> list[BaseManager]:
        return [self.__io, self.__ai, self.__logic, self.__data]

    def page_config(self) -> JSONObject:
        return self.__io.page_config()

    def validate_student_id(self, raw: object) -> tuple[bool, str]:
        return self.__io.validate_student_id(raw)

    def validate_form(self, form) -> JSONObject:
        """Validate a submitted form. Never reaches into I/O from the web."""
        values = form if isinstance(form, dict) or hasattr(form, "get") else {}
        safety = self.__io.safety_fired(values.get("feelings_text", "")
                                        if hasattr(values, "get") else "")
        ok, payload = self.__io.validate_student_form(values)
        if not ok:
            advisor = self.__io.advisor_panel("high") if safety else None
            return {"ok": False, "errors": payload, "safety_flag": safety,
                    "advisor": advisor}
        return {"ok": True, "record": payload,
                "safety_flag": payload.get("safety_flag") is True}

    def validate_record_filters(self, tier: str,
                                cohort_year: str) -> str | None:
        return self.__io.validate_record_filters(tier, cohort_year)

    def display_result(self, record: JSONObject) -> JSONObject:
        return self.__io.display_result(record)

    def process_checkin(self, record: JSONObject) -> JSONObject:
        """Gemini's analysis, then Logic's rules. AI must succeed first.

        A Logic rejection (such as a score mismatch) is reported as an
        "unavailable" failure, exactly like an AI failure.
        """
        analysis = self.__ai.analyse(record)
        if not analysis.get("ok"):
            code = str(analysis.get("error_code") or "unavailable")
            self.__logger.warning("Check-in could not complete: %s", code)
            return analysis
        evaluated = self.__logic.evaluate(analysis["fields"])  # type: ignore[arg-type]
        if not evaluated.get("ok"):
            detail = f"Logic rejected the analysis: {evaluated.get('error')}"
            self.__logger.warning(detail)
            return {"ok": False, "error_code": "unavailable", "detail": detail}
        return {"ok": True, "fields": evaluated}

    def submit_checkin(self, record: JSONObject, owner: str,
                       safety_flag: bool,
                       pending_fingerprint: str = "",
                       pending_record_id: str = "") -> JSONObject:
        """Start run_checkin on a worker thread and return at once.

        The same session sending the same answers again while a job runs
        gets that job back instead of a second Gemini call. The job dict
        holds a threading.Event so wait_for_job can block on it.
        """
        fingerprint = self.__fingerprint(record)
        with self.__jobs_lock:
            for job in self.__jobs.values():
                if (job.get("owner") == owner and job.get("key") == fingerprint
                        and not job.get("done")):
                    return {"status": "queued", "job_id": str(job["id"])}
            if self.__executor_stopped:
                raise RuntimeError("Cannot submit check-in after App.close().")
            job_id = uuid.uuid4().hex
            event = threading.Event()
            job: dict[str, object] = {
                "id": job_id,
                "owner": owner,
                "key": fingerprint,
                "safety_flag": safety_flag,
                "event": event,
                "created": time.monotonic(),
                "done": False,
                "status": "queued",
                "outcome": None,
                "pending_fingerprint": pending_fingerprint,
                "pending_record_id": pending_record_id,
            }
            self.__jobs[job_id] = job
            self.__executor.submit(self.__run_job, job_id, dict(record),
                                   owner, pending_fingerprint, pending_record_id)
        return {"status": "queued", "job_id": job_id}

    def job_status(self, job_id: str, owner: str) -> JSONObject:
        """The job, only for the session that submitted it.

        The payload is already shaped for the browser: WebController
        never builds a record or reaches into I/O.
        """
        with self.__jobs_lock:
            job = self.__jobs.get(job_id)
        if job is None or not owner or job.get("owner") != owner:
            return {"status": "not_found", "http_status": 404,
                    "payload": {"message": ("This check-in has expired. "
                                            "Please start a new check-in.")}}
        if not job.get("done"):
            return {"status": str(job.get("status") or "running"),
                    "http_status": 202,
                    "payload": {"status": job.get("status") or "running",
                                "jobId": job_id}}
        outcome = job.get("outcome")
        if not isinstance(outcome, dict):
            return {"status": "failed", "http_status": 500,
                    "payload": {"message": (
                        "We could not complete your check-in right now. "
                        "Your answers are still here; please try again.")}}
        return outcome

    def wait_for_job(self, job_id: str, timeout: float = 5.0) -> JSONObject:
        """Block until a job ends. Reports running if the timeout expires."""
        with self.__jobs_lock:
            job = self.__jobs.get(job_id)
        if job is None:
            return {"status": "not_found"}
        event = job.get("event")
        if isinstance(event, threading.Event):
            finished = event.wait(timeout)
            if not finished:
                return {"status": "running", "job_id": job_id}
        return self.job_status(job_id, str(job.get("owner") or ""))

    def expire_jobs(self) -> None:
        """Forget finished jobs and submission keys older than JOB_TTL_SECONDS."""
        cutoff = time.monotonic() - self.JOB_TTL_SECONDS
        with self.__jobs_lock:
            self.__jobs = {
                job_id: job for job_id, job in self.__jobs.items()
                if not job.get("done") or float(job.get("created") or 0) > cutoff
            }
        with self.__save_lock:
            self.__submissions = {
                key: entry for key, entry in self.__submissions.items()
                if float(entry.get("created") or 0) > cutoff
            }

    def forget_submission(self, owner: str) -> None:
        with self.__save_lock:
            to_drop = [key for key, entry in self.__submissions.items()
                       if entry.get("owner") == owner]
            for key in to_drop:
                self.__submissions.pop(key, None)

    def close(self) -> None:
        """Finish any running check-ins and stop the worker threads."""
        with self.__jobs_lock:
            if self.__executor_stopped:
                return
            self.__executor_stopped = True
        self.__executor.shutdown(wait=True)

    def admin_records(self, tier: str, cohort_year: str,
                      id_contains: str) -> JSONObject:
        """The admin table: current-questionnaire records, filtered.

        Returns {"ok": True, ...} or {"ok": False, "error": "storage"}.
        """
        version = self.__questionnaire.version
        try:
            records = [record for record in self.__data.load()
                       if record.survey_version == version]
        except OSError:
            return {"ok": False, "error": "storage"}
        matching = self.__data.filter_records(records, tier, cohort_year,
                                              id_contains)
        rows = self.__io.display_list([self.__row_for_display(record)
                                       for record in matching])
        return {"ok": True, "records": rows, "total": len(records),
                "matching": len(rows),
                "cohorts": list(self.__data.cohorts(records))}

    def student_history(self, student_id: str) -> JSONObject:
        """One student's own history page, already shaped for the browser.

        The file is loaded in full and filtered in memory; only this
        student's rows are returned. Returns {"ok": True, "history": ...}
        or {"ok": False, "error": "storage"}.
        """
        try:
            history = self.__data.history_for(
                student_id, self.__questionnaire.version)
        except OSError:
            return {"ok": False, "error": "storage"}
        trend = self.__logic.trend(history)
        return {"ok": True,
                "history": self.__io.display_history(history, trend)}

    def run_checkin(self, record: JSONObject, owner: str,
                    pending_fingerprint: str = "",
                    pending_record_id: str = "") -> JSONObject:
        """Analyse a validated check-in and save it exactly once.

        A failed analysis keeps the answers as one pending row per
        submission; a later success upgrades that same row in place.
        The match-pending and save steps run under __save_lock.
        """
        fingerprint = self.__fingerprint(record)
        student_id = str(record.get("student_id") or "")
        try:
            analysis = self.process_checkin(record)
        except Exception as error:
            self.__logger.warning("Check-in pipeline failed: %s",
                                  type(error).__name__)
            analysis = {"ok": False, "error_code": "unavailable",
                        "detail": type(error).__name__}

        with self.__save_lock:
            pending_id = self.__match_pending(
                fingerprint, owner, pending_fingerprint, pending_record_id)
            if not analysis.get("ok"):
                safety = record.get("safety_flag") is True
                record_id = pending_id or self.__save_pending(record)
                if record_id:
                    self.__remember(owner, fingerprint, record_id)
                code = str(analysis.get("error_code") or "unavailable")
                error_page = self.__io.display_error(code)
                advisor = error_page.get("speak_to_advisor")
                return {
                    "status": "pending",
                    "http_status": 503,
                    "payload": {
                        "message": ("We could not complete your check-in "
                                    "right now. Your answers are still "
                                    "here; please try again."),
                        "error_code": code,
                        "advisor": advisor,
                        "safety_flag": safety,
                    },
                    "safety_flag": safety,
                    "student_id": student_id,
                    "saved": bool(record_id),
                    "pending_id": record_id,
                    "fingerprint": fingerprint,
                    "result": None,
                }
            fields = analysis["fields"]
            assert isinstance(fields, dict)
            finished = CheckInRecord(fields)
            if pending_id:
                saved = self.__data.replace_pending_record(
                    pending_id, finished, opt_in=True)
            else:
                saved = self.__data.save(finished, opt_in=True)
            if not saved.get("ok"):
                return {
                    "status": "save_failed",
                    "http_status": 500,
                    "payload": {"message": (
                        "We could not save your check-in just now. Your "
                        "answers are still here; please try again.")},
                    "student_id": student_id,
                    "saved": False,
                    "pending_id": None,
                    "fingerprint": fingerprint,
                    "result": None,
                }
            record_id = str(saved.get("record_id") or "")
            self.__remember(owner, fingerprint, record_id)
            page = self.__io.display_result(fields)
            return {
                "status": "completed",
                "http_status": 200,
                "payload": {"ok": True, "result": page},
                "student_id": student_id,
                "saved": True,
                "pending_id": None,
                "fingerprint": fingerprint,
                "result": page,
            }

    def __run_job(self, job_id: str, record: JSONObject, owner: str,
                  pending_fingerprint: str, pending_record_id: str) -> None:
        with self.__jobs_lock:
            job = self.__jobs.get(job_id)
            if job is not None:
                job["status"] = "running"
        try:
            outcome = self.run_checkin(
                record, owner, pending_fingerprint, pending_record_id)
        except Exception as error:
            self.__logger.warning("Background check-in failed: %s",
                                  type(error).__name__)
            outcome = {
                "status": "failed",
                "http_status": 500,
                "payload": {"message": (
                    "We could not complete your check-in right now. "
                    "Your answers are still here; please try again.")},
                "student_id": str(record.get("student_id") or ""),
                "saved": False,
                "result": None,
            }
        with self.__jobs_lock:
            job = self.__jobs.get(job_id)
            if job is not None:
                job["outcome"] = outcome
                job["done"] = True
                job["status"] = str(outcome.get("status") or "failed")
                event = job.get("event")
                if isinstance(event, threading.Event):
                    event.set()

    def __save_pending(self, record: JSONObject) -> str:
        pending = PendingRecord({**record, "record_id": uuid.uuid4().hex})
        saved = self.__data.save(pending, opt_in=True)
        if not saved.get("ok"):
            self.__logger.warning("Pending check-in could not be saved")
            return ""
        return str(saved.get("record_id") or "")

    def __fingerprint(self, record: JSONObject) -> str:
        answers = [record.get(key) for key in self.__questionnaire.keys()]
        payload = json.dumps(
            [record.get("student_id"), answers, record.get("survey_version")],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def __match_pending(self, fingerprint: str, owner: str,
                        pending_fingerprint: str,
                        pending_record_id: str) -> str:
        if pending_fingerprint == fingerprint and pending_record_id:
            return pending_record_id
        entry = self.__submissions.get(f"{owner}:{fingerprint}")
        if entry:
            return str(entry.get("record_id") or "")
        return ""

    def __remember(self, owner: str, fingerprint: str,
                   record_id: str) -> None:
        self.__submissions[f"{owner}:{fingerprint}"] = {
            "owner": owner,
            "record_id": record_id,
            "created": time.monotonic(),
        }

    def __row_for_display(self, record) -> JSONObject:
        row = record.to_row()
        row["status"] = record.status
        return row


if __name__ == "__main__":
    from web_controller import WebController
    application = App()
    WebController(application, application.flask)
    application.flask.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"},
    )
