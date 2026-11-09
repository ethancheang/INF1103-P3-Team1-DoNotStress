"""CampusApp: composition root and HTTP controller for the campus check-in web app."""

from __future__ import annotations

import logging
import os
import secrets
import uuid
from collections.abc import Mapping
from typing import Any

from flask import Flask, Response, jsonify, redirect, render_template, request, session, url_for
from flask.typing import ResponseReturnValue

from admin_session_manager import AdminSessionManager
from ai_manager import GeminiAIManager, TextGenerator
from checkin_pipeline import CheckinPipeline
from data_manager import DataStoreError, JsonRecordRepository, RecordRepository
from io_manager import StudentIO
from logic_manager import AIScoreVerifier, LogicManager, ScoreCalculator
from pending_checkin_registry import PendingCheckinRegistry
from records_query_service import RecordsQueryService
from reports import CohortSummaryReport
from result_presenter import ResultPresenter
from submission_fingerprint import SubmissionFingerprint
from survey import Questionnaire, SafetyCheck

logger = logging.getLogger(__name__)


class CampusApp:
    """One running campus web application.

    The constructor wires the four managers and the supporting services
    (composition root); each HTTP route is a method that validates the
    request and delegates. ``flask_app`` is the WSGI app for Flask/Docker.

        browser -> StudentIO (I/O) -> GeminiAIManager (AI) -> LogicManager (Logic)
                -> JsonRecordRepository (Data) -> ResultPresenter -> browser

    ``text_generator`` replaces the live Gemini client (tests pass a fake);
    ``config`` overrides Flask settings such as DATA_PATH.
    """

    def __init__(self, config: Mapping[str, Any] | None = None, *, text_generator: TextGenerator | None = None) -> None:
        self.__app = Flask(__name__)
        self.__app.config.update(
            SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            DATA_PATH=os.environ.get("DONOTSTRESS_DATA_PATH") or None,
            AI_MAX_ATTEMPTS=3,
            AI_RETRY_DELAY_SEC=0.5,
            PENDING_TTL_SECONDS=1800,
            MAX_CONTENT_LENGTH=64 * 1024,
            ADMIN_SESSION_SECONDS=1800,
            ADMIN_LOGIN_MAX_ATTEMPTS=5,
            ADMIN_LOGIN_WINDOW_SECONDS=300,
        )
        if config:
            self.__app.config.update(config)
        settings = self.__app.config

        # The four managers. One ScoreCalculator is shared by Logic and by the
        # verifier the AI Manager uses, so the prompt, the reply check and the
        # final evaluation always use the same scoring rules.
        calculator = ScoreCalculator()
        verifier = AIScoreVerifier(calculator)
        self.__io = StudentIO()
        self.__ai = GeminiAIManager(
            verifier,
            text_generator,
            questions=Questionnaire.QUESTIONS,
            max_attempts=settings["AI_MAX_ATTEMPTS"],
            retry_delay_sec=settings["AI_RETRY_DELAY_SEC"],
        )
        self.__logic = LogicManager(calculator=calculator)
        self.__store: RecordRepository = JsonRecordRepository(settings["DATA_PATH"])

        # Supporting services.
        self.__safety = SafetyCheck()
        self.__pipeline = CheckinPipeline(self.__ai, self.__logic)
        self.__presenter = ResultPresenter(self.__io)
        self.__fingerprint = SubmissionFingerprint()
        self.__pending = PendingCheckinRegistry()
        self.__admin = AdminSessionManager(
            max_attempts=settings["ADMIN_LOGIN_MAX_ATTEMPTS"],
            window_seconds=settings["ADMIN_LOGIN_WINDOW_SECONDS"],
            session_seconds=settings["ADMIN_SESSION_SECONDS"],
        )
        self.__records_query = RecordsQueryService()
        self.__summary_report = CohortSummaryReport()

        self.__app.extensions["store"] = self.__store
        self.__register()

    @property
    def flask_app(self) -> Flask:
        return self.__app

    @property
    def store(self) -> RecordRepository:
        return self.__store

    def run(self) -> None:
        """Start the local development server (``python main.py``)."""
        self.__app.run(
            host="127.0.0.1",
            port=int(os.environ.get("PORT", "5000")),
            debug=os.environ.get("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"},
        )

    # -- wiring -------------------------------------------------------------

    def __register(self) -> None:
        app = self.__app
        app.before_request(self.before_request)
        app.after_request(self.after_request)
        app.register_error_handler(413, self.oversized_request)
        routes = (
            ("/", "checkin", self.checkin, ("GET",)),
            ("/", "submit_checkin", self.submit_checkin, ("POST",)),
            ("/garden", "retired_page", self.retired_page, ("GET",)),
            ("/admin/login", "admin_login", self.admin_login, ("GET", "POST")),
            ("/admin/logout", "admin_logout", self.admin_logout, ("POST",)),
            ("/records", "records_page", self.records_page, ("GET",)),
            ("/api/records", "saved_records", self.saved_records, ("GET",)),
            ("/result", "result", self.result, ("GET",)),
            ("/save", "save_checkin", self.save_checkin, ("POST",)),
            ("/new", "new_checkin", self.new_checkin, ("GET",)),
        )
        for rule, endpoint, view, methods in routes:
            app.add_url_rule(rule, endpoint, view, methods=list(methods))

    # -- request hooks ------------------------------------------------------

    def before_request(self) -> ResponseReturnValue | None:
        """Expire old in-memory state and require the CSRF token on every POST."""
        self.__pending.expire(self.__app.config["PENDING_TTL_SECONDS"])
        self.__admin.expire()
        if request.method != "POST":
            return None
        expected = session.get("csrf_token", "")
        provided = request.headers.get("X-CSRF-Token", "")
        if not provided and not request.is_json:
            provided = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(provided.encode("utf-8"), expected.encode("utf-8")):
            return jsonify(message="This page has expired. Reload and try again."), 403
        return None

    def after_request(self, response: Response) -> Response:
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    def oversized_request(self, error: Exception) -> ResponseReturnValue:
        return jsonify(message="Your response is too long. Please shorten it and try again."), 413

    # -- pages --------------------------------------------------------------

    def checkin(self) -> ResponseReturnValue:
        return self.__render_campus()

    def retired_page(self) -> ResponseReturnValue:
        """Legacy URL from the removed garden page."""
        return redirect(url_for("checkin"))

    def result(self) -> ResponseReturnValue:
        """Refreshing the result only reads memory; the check-in was saved once already."""
        if not self.__pending.current(session):
            return redirect(url_for("checkin"))
        return self.__render_campus("result")

    def new_checkin(self) -> ResponseReturnValue:
        self.__pending.clear(session)
        return redirect(url_for("checkin"))

    # -- check-in -----------------------------------------------------------

    def submit_checkin(self) -> ResponseReturnValue:
        values = request.get_json(silent=True) if request.is_json else request.form
        if not isinstance(values, Mapping):
            return jsonify(message="Please submit a check-in form."), 400
        safety = self.__safety.is_flagged(values.get("feelings_text", ""))
        ok, record = self.__io.validate_form(values)
        if not ok:
            return jsonify(
                errors=record, safety_flag=safety, advisor=self.__io.format_advisor("high") if safety else None
            ), 400
        self.__pending.clear(session)
        identity = self.__fingerprint.of(record)
        try:
            ok, outcome = self.__pipeline.process(record)
        except Exception:  # noqa: BLE001 - the student must never see a crash page
            logger.warning("Check-in pipeline could not complete")
            ok, outcome = False, "unavailable"
        if not ok:
            self.__save_pending(identity, record)
            copy = self.__io.format_ai_error(outcome)
            return jsonify(
                message="We could not complete your check-in right now. Your answers are still here; please try again.",
                error_code=outcome,
                safety_flag=safety,
                advisor=copy["speak_to_advisor"],
            ), 503
        saved, outcome = self.__save_evaluated(identity, outcome)
        if not saved:
            return jsonify(
                message="We could not save your check-in just now. Your answers are still here; please try again."
            ), 500
        token = secrets.token_urlsafe(32)
        self.__pending.store_result(token, outcome, saved=True)
        session["checkin_token"] = token
        return jsonify(ok=True, result=self.__presenter.build(outcome, saved=True))

    def save_checkin(self) -> ResponseReturnValue:
        """Retry a missed write. A result that is already saved is left as it is."""
        with self.__pending.locked():
            entry = self.__pending.current(session)
            if not entry:
                return jsonify(message="Your result has expired. Please start a new check-in."), 409
            if entry["saved"]:
                return jsonify(ok=True, saved=True)
            try:
                self.__store.save(entry["record"])
                entry["saved"] = True
            except Exception as exc:  # noqa: BLE001 - DataStoreError or anything unexpected
                logger.warning("Retrying the pending save failed: %s", type(exc).__name__)
                return jsonify(message="Your check-in could not be saved. Please try again."), 500
        return jsonify(ok=True, saved=True)

    # -- admin --------------------------------------------------------------

    def admin_login(self) -> ResponseReturnValue:
        if self.__admin.is_admin(session):
            return redirect(url_for("records_page"))
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        error, status = None, 200
        if request.method == "POST":
            values = request.get_json(silent=True) if request.is_json else request.form
            values = values if isinstance(values, Mapping) else {}
            username, password = values.get("username", ""), values.get("password", "")
            address = request.remote_addr or "local"
            if self.__admin.record_attempt(address):
                error, status = "Too many sign-in attempts. Please try again in five minutes.", 429
            elif self.__admin.check_password(username, password):
                self.__admin.clear_attempts(address)
                self.__admin.grant(session)
                return redirect(url_for("records_page"))
            else:
                error, status = "Incorrect username or password.", 401
        return render_template("admin_login.html", error=error, csrf_token=session["csrf_token"]), status

    def admin_logout(self) -> ResponseReturnValue:
        self.__admin.revoke(session)
        self.__pending.clear(session)
        self.__pending.forget_csrf(session.get("csrf_token"))
        session.clear()
        return redirect(url_for("checkin"))

    def records_page(self) -> ResponseReturnValue:
        if not self.__admin.is_admin(session):
            return redirect(url_for("admin_login"))
        return self.__render_campus("records")

    def saved_records(self) -> ResponseReturnValue:
        """Saved check-ins for the admin table, plus the cohort summary for the same filters."""
        if not self.__admin.is_admin(session):
            return jsonify(message="Admin sign-in is required to view saved records."), 401
        try:
            loaded = self.__store.load()
        except Exception as exc:  # noqa: BLE001 - DataStoreError (corrupt file) or an unexpected read error
            logger.warning("Loading saved records failed: %s", type(exc).__name__)
            return jsonify(message="Saved records could not be loaded. Please try again."), 500
        query = self.__records_query
        records = query.current_version(loaded)
        student_id = request.args.get("student_id", "").strip()
        tier = request.args.get("tier", "").strip()
        cohort = request.args.get("cohort_year", "").strip()
        message = query.validate_filters(tier, cohort)
        if message:
            return jsonify(message=message), 400
        matching = query.matching(records, student_id=student_id, tier=tier, cohort=cohort)
        rows = query.rows(matching)
        return jsonify(
            records=rows,
            total=len(records),
            matching=len(rows),
            cohorts=query.cohorts(records),
            summary=self.__io.format_summary(self.__summary_report.build(matching)),
        )

    # -- helpers ------------------------------------------------------------

    def __render_campus(self, page: str = "home") -> ResponseReturnValue:
        session.setdefault("csrf_token", secrets.token_urlsafe(32))
        entry = self.__pending.current(session)
        return render_template(
            "checkin.html",
            boot={
                "page": page,
                "survey": Questionnaire.public_config(),
                "isAdmin": self.__admin.is_admin(session),
                "adminLoginUrl": url_for("admin_login"),
                "result": self.__presenter.build(entry["record"], entry["saved"]) if entry else None,
                "csrfToken": session["csrf_token"],
                "submitUrl": url_for("submit_checkin"),
                "saveUrl": url_for("save_checkin"),
                "newUrl": url_for("new_checkin"),
                "homeUrl": url_for("checkin"),
                "resultUrl": url_for("result"),
                "recordsPageUrl": url_for("records_page"),
                "recordsUrl": url_for("saved_records"),
            },
        )

    def __save_pending(self, identity: str, record: Mapping[str, Any]) -> None:
        """AI did not finish. The same answers in this session stay one pending row."""
        try:
            with self.__pending.locked():
                pending_id = self.__pending.matched_id(session, identity)
                if pending_id is not None:
                    self.__pending.remember(session, identity, pending_id, pending_save=True)
                    return
                record_id = uuid.uuid4().hex
                stored = self.__store.save_pending({**record, "record_id": record_id})
                self.__pending.remember(session, identity, stored.get("record_id") or record_id, pending_save=True)
        except Exception as exc:  # noqa: BLE001 - DataStoreError or unexpected; the student still sees retry copy
            logger.warning("Pending check-in could not be saved: %s", type(exc).__name__)

    def __save_evaluated(self, identity: str, outcome: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
        """Save the evaluated record, upgrading this session's pending row if there is one."""
        try:
            with self.__pending.locked():
                pending_id = self.__pending.matched_id(session, identity)
                if pending_id:
                    outcome = {**outcome, "record_id": pending_id}
                    stored = self.__store.replace_pending(pending_id, outcome)
                else:
                    stored = self.__store.save(outcome)
                stored_id = stored.get("record_id")
                if stored_id:
                    self.__pending.remember(session, identity, stored_id, pending_save=False)
                return True, outcome
        except Exception as exc:  # noqa: BLE001 - DataStoreError or unexpected
            logger.warning("Saving the check-in failed: %s", type(exc).__name__)
            return False, outcome
