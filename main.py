"""DoNotStress entry point: campus UI → I/O → Gemini → Logic → records.

App is the composition root: it creates and owns the four managers and
wires them together. Flask routes live in WebController. App itself never
imports WebController: tests and the `python main.py` entry attach the
controller with WebController(App(...)). This module does not construct a
live App at import time.

Run locally with `python main.py`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import math
import os
import secrets
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ai.ai_provider import AIProvider
from ai.gemini_provider import GeminiProvider
from ai_manager import AIManager
from base_manager import BaseManager
from data_manager import DataManager
from io_manager import IOManager
from json_types import JSONObject
from logic_manager import LogicManager
from questionnaire import Questionnaire


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
    DELIVERED_TTL_SECONDS: float = 60.0
    WORKERS: int = 4
    MAX_RUNNING_PER_OWNER: int = 2
    MAX_ACTIVE_JOBS: int = 16

    def __init__(self, provider: AIProvider | None = None,
                 data_path: Path | str | None = None,
                 secret_key: str | None = None, testing: bool = False,
                 ai_max_attempts: int = 3,
                 ai_retry_delay_sec: float | None = None,
                 test_config: dict[str, object] | None = None) -> None:
        self.__logger: logging.Logger = logging.getLogger("main")
        cfg = test_config or {}
        if cfg.get("TESTING"):
            testing = True
        self.__testing: bool = bool(testing)
        configured_secret = str(
            secret_key
            or cfg.get("SECRET_KEY")
            or os.environ.get("FLASK_SECRET_KEY")
            or ""
        )
        if not configured_secret:
            if not self.__testing:
                self.__logger.warning(
                    "FLASK_SECRET_KEY is not set; using an ephemeral secret key."
                )
            configured_secret = secrets.token_hex(32)
        self.__secret_key: str = configured_secret
        configured = (
            str(data_path) if data_path is not None
            else str(cfg.get("DATA_PATH") or os.environ.get("DONOTSTRESS_DATA_PATH") or "")
        )
        path = Path(configured) if configured else self.DEFAULT_DATA_PATH

        questionnaire = Questionnaire.from_survey()
        self.__questionnaire = questionnaire
        self.__io: IOManager = IOManager(questionnaire)
        self.__logic: LogicManager = LogicManager(
            answer_keys=questionnaire.keys(),
            reversed_keys=questionnaire.reversed_keys(),
        )
        delay = (0.0 if testing else 0.5) if ai_retry_delay_sec is None else ai_retry_delay_sec
        self.__ai: AIManager = AIManager(
            provider if provider is not None else self.make_provider(),
            questionnaire,
            instructions=self.__logic.instructions,
            verify=self.__logic.verify,
            max_attempts=ai_max_attempts,
            retry_delay_sec=delay,
        )
        self.__data: DataManager = DataManager(path)

        self.__save_lock: threading.Lock = threading.Lock()
        self.__submissions_lock: threading.Lock = threading.Lock()
        self.__jobs_lock: threading.Lock = threading.Lock()
        self.__jobs: dict[str, dict[str, object]] = {}
        self.__submissions: dict[str, dict[str, object]] = {}
        self.__executor: ThreadPoolExecutor = ThreadPoolExecutor(
            max_workers=self.WORKERS, thread_name_prefix="checkin")
        self.__executor_stopped: bool = False

    @staticmethod
    def make_provider() -> AIProvider:
        """The live Gemini provider. Tests pass a different AIProvider in."""
        return GeminiProvider()

    @property
    def secret_key(self) -> str:
        return self.__secret_key

    @property
    def testing(self) -> bool:
        return self.__testing

    def health(self) -> JSONObject:
        """Every manager's health summary. Never includes secrets."""
        managers: tuple[BaseManager, ...] = (
            self.__io, self.__ai, self.__logic, self.__data
        )
        return {"status": "ok",
                "managers": [manager.health() for manager in managers]}

    def status_message(self, key: str) -> str:
        """Student-facing status wording owned by IOManager."""
        return self.__io.status_message(key)

    def page_config(self) -> JSONObject:
        return self.__io.page_config()

    def validate_student_id(self, raw: object) -> tuple[bool, str]:
        return self.__io.validate_student_id(raw)

    def validate_form(self, form: Mapping[str, object]) -> JSONObject:
        """Validate a submitted form. Never reaches into I/O from the web."""
        values: Mapping[str, object] = (
            form if isinstance(form, Mapping) else {})
        raw_text = values.get("feelings_text", "") if values else ""
        safety = self.__io.safety_fired(raw_text)
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
                       pending_fingerprint: str = "",
                       pending_record_id: str = "") -> JSONObject:
        """Start run_checkin on a worker thread and return at once.

        The same session sending the same answers again while a job runs
        gets that job back instead of a second Gemini call. Limits
        concurrent active jobs per owner and holds a threading.Event per job.
        """
        fingerprint = self.__fingerprint(record)
        with self.__jobs_lock:
            for job in self.__jobs.values():
                if (job.get("owner") == owner and job.get("key") == fingerprint
                        and not job.get("done")):
                    return {"status": "queued", "job_id": str(job["id"])}
            active = sum(
                1 for job in self.__jobs.values() if not job.get("done")
            )
            running = sum(
                1 for job in self.__jobs.values()
                if job.get("owner") == owner and not job.get("done")
            )
            if (running >= self.MAX_RUNNING_PER_OWNER
                    or active >= self.MAX_ACTIVE_JOBS):
                return {
                    "status": "busy",
                    "payload": {"message": self.__io.status_message("busy")},
                }
            if self.__executor_stopped:
                raise RuntimeError("Cannot submit check-in after App.close().")
            job_id = uuid.uuid4().hex
            event = threading.Event()
            job: dict[str, object] = {
                "id": job_id,
                "owner": owner,
                "key": fingerprint,
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

    def job_status(self, job_id: str, owner: str,
                   wait: float = 0.0) -> JSONObject:
        """The job, only for the session that submitted it.

        When wait > 0 and the job is still running, blocks briefly on
        the job's threading.Event before checking status again.
        """
        timeout = (
            min(float(wait), 2.0)
            if isinstance(wait, (int, float))
            and not isinstance(wait, bool)
            and math.isfinite(float(wait))
            and float(wait) > 0.0
            else 0.0
        )
        with self.__jobs_lock:
            job = self.__jobs.get(job_id)
            if job is None or not owner or job.get("owner") != owner:
                return {"status": "not_found",
                        "payload": {"message": self.__io.status_message("expired")}}
            done = bool(job.get("done"))
            event = job.get("event")
        if timeout > 0.0 and not done and isinstance(event, threading.Event):
            event.wait(timeout)
        with self.__jobs_lock:
            job = self.__jobs.get(job_id)
            if job is None or job.get("owner") != owner:
                return {"status": "not_found",
                        "payload": {"message": self.__io.status_message("expired")}}
            if not job.get("done"):
                status = str(job.get("status") or "running")
                return {"status": status,
                        "payload": {"status": status,
                                    "jobId": job_id}}
            job["delivered_at"] = job.get("delivered_at") or time.monotonic()
            outcome = job.get("outcome")
        if not isinstance(outcome, dict):
            return {"status": "failed",
                    "payload": {"message": self.__io.status_message("calm_failure")}}
        return copy.deepcopy(outcome)

    def wait_for_job(self, job_id: str, timeout: float = 5.0) -> JSONObject:
        """Block until a job ends. Reports running if the timeout expires.

        For tests and scripts that need the outcome synchronously; the web
        flow polls job_status() instead.
        """
        wait = (
            max(0.0, float(timeout))
            if isinstance(timeout, (int, float))
            and not isinstance(timeout, bool)
            and math.isfinite(float(timeout))
            else 0.0
        )
        with self.__jobs_lock:
            job = self.__jobs.get(job_id)
            if job is None:
                return {"status": "not_found"}
            event = job.get("event")
            owner = str(job.get("owner") or "")
        if isinstance(event, threading.Event):
            finished = event.wait(wait)
            if not finished:
                return {"status": "running", "job_id": job_id}
        return self.job_status(job_id, owner)

    def expire_jobs(self) -> None:
        """Forget finished jobs and submission keys past their TTL."""
        now = time.monotonic()
        cutoff = now - self.JOB_TTL_SECONDS
        delivered_cutoff = now - self.DELIVERED_TTL_SECONDS
        with self.__jobs_lock:
            self.__jobs = {
                job_id: job for job_id, job in self.__jobs.items()
                if self.__keep_job(job, cutoff, delivered_cutoff)
            }
        with self.__submissions_lock:
            self.__submissions = {
                key: entry for key, entry in self.__submissions.items()
                if self.__entry_fresh(entry.get("created"), cutoff)
            }

    @staticmethod
    def __entry_fresh(timestamp: object, cutoff: float) -> bool:
        if isinstance(timestamp, (int, float)) and not isinstance(
                timestamp, bool):
            return float(timestamp) > cutoff
        return False

    @classmethod
    def __keep_job(cls, job: dict[str, object], cutoff: float,
                   delivered_cutoff: float) -> bool:
        if not job.get("done"):
            return True
        if not cls.__entry_fresh(job.get("created"), cutoff):
            return False
        delivered = job.get("delivered_at")
        if delivered is None:
            return True
        return cls.__entry_fresh(delivered, delivered_cutoff)

    def forget_submission(self, owner: str) -> None:
        with self.__submissions_lock:
            to_drop = [key for key, entry in self.__submissions.items()
                       if entry.get("owner") == owner]
            for key in to_drop:
                self.__submissions.pop(key, None)
        with self.__jobs_lock:
            done_jobs = [
                job_id for job_id, job in self.__jobs.items()
                if job.get("owner") == owner and job.get("done")
            ]
            for job_id in done_jobs:
                self.__jobs.pop(job_id, None)

    def close(self) -> None:
        """Cancel queued check-ins, wait for active workers, and stop threads."""
        with self.__jobs_lock:
            if self.__executor_stopped:
                return
            self.__executor_stopped = True
        self.__executor.shutdown(wait=True, cancel_futures=True)

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

    def student_history(self, student_id: str,
                        visible: Callable[[str], bool] | None = None
                        ) -> JSONObject:
        """One student's history page, already shaped for the browser.

        When visible is supplied, only matching records are included in
        entries, pending counts, and trends. Returns {"ok": True, ...}
        or {"ok": False, "error": "storage"}.
        """
        try:
            history = self.__data.history_for(
                student_id, self.__questionnaire.version, visible)
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
                record_id = self.__save_pending(record, replace_id=pending_id)
                if record_id:
                    self.__remember(owner, fingerprint, record_id, pending=True)
                code = str(analysis.get("error_code") or "unavailable")
                error_page = self.__io.display_error(code)
                advisor = error_page.get("speak_to_advisor")
                return {
                    "status": "pending",
                    "payload": {
                        "message": self.__io.status_message("calm_failure"),
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
            if not isinstance(fields, dict):
                raise TypeError("Check-in analysis fields must be a dict.")
            saved = self.__data.save_checkin(
                fields, opt_in=True, replace_id=pending_id)
            if not saved.get("ok"):
                return {
                    "status": "save_failed",
                    "payload": {
                        "message": self.__io.status_message("save_failed"),
                    },
                    "student_id": student_id,
                    "saved": False,
                    "pending_id": None,
                    "fingerprint": fingerprint,
                    "result": None,
                }
            record_id = str(saved.get("record_id") or "")
            self.__remember(owner, fingerprint, record_id, pending=False)
            page = self.__io.display_result(fields)
            return {
                "status": "completed",
                "payload": {"ok": True, "result": copy.deepcopy(page)},
                "student_id": student_id,
                "record_id": record_id,
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
                "payload": {"message": self.__io.status_message("calm_failure")},
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

    def __save_pending(self, record: JSONObject,
                       replace_id: str = "") -> str:
        saved = self.__data.save_pending(
            record, opt_in=True, replace_id=replace_id)
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
        with self.__submissions_lock:
            entry = self.__submissions.get(f"{owner}:{fingerprint}")
        if entry is not None:
            if entry.get("pending") is True:
                return str(entry.get("record_id") or "")
            return ""
        if pending_fingerprint == fingerprint and pending_record_id:
            return pending_record_id
        return ""

    def __remember(self, owner: str, fingerprint: str,
                   record_id: str, *, pending: bool = True) -> None:
        with self.__submissions_lock:
            self.__submissions[f"{owner}:{fingerprint}"] = {
                "owner": owner,
                "record_id": record_id,
                "pending": pending,
                "created": time.monotonic(),
            }

    def __row_for_display(self, record) -> JSONObject:
        row = record.to_row()
        row["status"] = record.status
        return row


if __name__ == "__main__":
    from dotenv import load_dotenv
    from web_controller import WebController

    load_dotenv()
    application = App()
    try:
        WebController(application).run(
            host=os.environ.get("HOST", "127.0.0.1"),
            port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"},
        )
    finally:
        application.close()
