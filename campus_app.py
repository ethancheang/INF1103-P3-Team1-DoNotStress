"""CampusApp: composition root and HTTP controller for the campus check-in UI.

Wires the four managers (I/O, AI, Logic, Data) and the supporting services.
Route methods stay thin: they validate the request and delegate.
"""

from __future__ import annotations

import logging
import os
import secrets
import uuid

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

import survey
from admin_session_manager import AdminSessionManager
from ai_manager import GeminiAIManager
from checkin_pipeline import CheckinPipeline
from data_manager import DataStoreError, JsonRecordRepository
from io_manager import StudentIO
from logic_manager import AIScoreVerifier, LogicManager, ScoreCalculator
from pending_checkin_registry import PendingCheckinRegistry
from records_query_service import RecordsQueryService
from result_presenter import ResultPresenter
from submission_fingerprint import SubmissionFingerprint

logger = logging.getLogger(__name__)


class CampusApp:
    """One running campus application. create() returns the Flask app."""

    def create(self, test_config=None) -> Flask:
        app = Flask(__name__)
        app.config.update(
            SECRET_KEY=os.environ.get("FLASK_SECRET_KEY") or secrets.token_hex(32),
            SESSION_COOKIE_HTTPONLY=True,
            SESSION_COOKIE_SAMESITE="Lax",
            DATA_PATH=os.environ.get("DONOTSTRESS_DATA_PATH") or None,
            AI_GENERATE_FN=None,
            AI_MAX_ATTEMPTS=3,
            AI_RETRY_DELAY_SEC=0.5,
            PENDING_TTL_SECONDS=1800,
            MAX_CONTENT_LENGTH=64 * 1024,
            ADMIN_SESSION_SECONDS=1800,
            ADMIN_LOGIN_MAX_ATTEMPTS=5,
            ADMIN_LOGIN_WINDOW_SECONDS=300,
        )
        if test_config:
            app.config.update(test_config)

        calculator = ScoreCalculator()
        logic = LogicManager(calculator=calculator)
        verifier = AIScoreVerifier(calculator)
        store = JsonRecordRepository(app.config["DATA_PATH"])
        io = StudentIO()
        ai = GeminiAIManager(
            verifier=verifier,
            generate_fn=app.config["AI_GENERATE_FN"],
            max_attempts=app.config["AI_MAX_ATTEMPTS"],
            retry_delay_sec=app.config["AI_RETRY_DELAY_SEC"],
        )
        pipeline = CheckinPipeline(ai, logic, verifier)
        presenter = ResultPresenter(io)
        fingerprint = SubmissionFingerprint()
        pending = PendingCheckinRegistry()
        admin = AdminSessionManager(
            max_attempts=app.config["ADMIN_LOGIN_MAX_ATTEMPTS"],
            window_seconds=app.config["ADMIN_LOGIN_WINDOW_SECONDS"],
            session_seconds=app.config["ADMIN_SESSION_SECONDS"],
        )
        records_query = RecordsQueryService()

        app.extensions["store"] = store
        app.extensions["io"] = io
        app.extensions["ai"] = ai
        app.extensions["pending_checkins"] = pending.pending
        app.extensions["pending_submissions"] = pending.submissions
        app.extensions["admin_sessions"] = admin

        self._register_hooks(app, pending, admin)
        self._register_routes(
            app, store, io, ai, pipeline, presenter, fingerprint, pending, admin, records_query
        )
        return app

    def _register_hooks(self, app, pending: PendingCheckinRegistry, admin: AdminSessionManager) -> None:
        @app.before_request
        def expire_records_and_check_csrf():
            pending.expire(app.config["PENDING_TTL_SECONDS"])
            admin.expire()
            if request.method == "POST":
                expected = session.get("csrf_token", "")
                provided = request.headers.get("X-CSRF-Token", "")
                if not provided and not request.is_json:
                    provided = request.form.get("csrf_token", "")
                if not expected or not secrets.compare_digest(
                    provided.encode("utf-8"), expected.encode("utf-8")
                ):
                    return jsonify(message="This page has expired. Reload and try again."), 403

        @app.errorhandler(413)
        def oversized_request(error):
            return jsonify(
                message="Your response is too long. Please shorten it and try again."
            ), 413

        @app.after_request
        def prevent_answer_caching(response):
            if request.endpoint != "static":
                response.headers["Cache-Control"] = "no-store"
            return response

    def _register_routes(
        self,
        app,
        store,
        io,
        ai,
        pipeline: CheckinPipeline,
        presenter: ResultPresenter,
        fingerprint: SubmissionFingerprint,
        pending: PendingCheckinRegistry,
        admin: AdminSessionManager,
        records_query: RecordsQueryService,
    ) -> None:
        def render_campus(page: str = "home"):
            session.setdefault("csrf_token", secrets.token_urlsafe(32))
            entry = pending.current(session)
            return render_template(
                "checkin.html",
                boot={
                    "page": page,
                    "survey": survey.public_config(),
                    "isAdmin": admin.is_admin(session),
                    "adminLoginUrl": url_for("admin_login"),
                    "result": presenter.build(entry["record"], entry["saved"]) if entry else None,
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

        @app.get("/")
        def checkin():
            return render_campus()

        @app.get("/garden")
        def retired_page():
            return redirect(url_for("checkin"))

        @app.route("/admin/login", methods=["GET", "POST"])
        def admin_login():
            if admin.is_admin(session):
                return redirect(url_for("records_page"))
            session.setdefault("csrf_token", secrets.token_urlsafe(32))
            error, status = None, 200
            if request.method == "POST":
                values = request.get_json(silent=True) if request.is_json else request.form
                values = values if isinstance(values, dict) or hasattr(values, "get") else {}
                username, password = values.get("username", ""), values.get("password", "")
                address = request.remote_addr or "local"
                if admin.record_attempt(address):
                    error, status = (
                        "Too many sign-in attempts. Please try again in five minutes.",
                        429,
                    )
                elif admin.check_password(username, password):
                    admin.clear_attempts(address)
                    admin.grant(session)
                    return redirect(url_for("records_page"))
                else:
                    error, status = "Incorrect username or password.", 401
            return render_template(
                "admin_login.html", error=error, csrf_token=session["csrf_token"]
            ), status

        @app.post("/admin/logout")
        def admin_logout():
            admin.revoke(session)
            pending.clear(session)
            pending.forget_csrf(session.get("csrf_token"))
            session.clear()
            return redirect(url_for("checkin"))

        @app.post("/")
        def submit_checkin():
            values = request.get_json(silent=True) if request.is_json else request.form
            if not hasattr(values, "get"):
                return jsonify(message="Please submit a check-in form."), 400
            safety = survey.safety_check(values.get("feelings_text", ""))
            ok, record = io.validate_form(values)
            if not ok:
                return jsonify(
                    errors=record,
                    safety_flag=safety,
                    advisor=io.format_advisor("high") if safety else None,
                ), 400
            pending.clear(session)
            identity = fingerprint.of(record)
            try:
                ok, outcome = pipeline.process(
                    record,
                    generate_fn=app.config["AI_GENERATE_FN"],
                    max_attempts=app.config["AI_MAX_ATTEMPTS"],
                    retry_delay_sec=app.config["AI_RETRY_DELAY_SEC"],
                )
            except Exception:
                logger.warning("Check-in pipeline could not complete")
                ok, outcome = False, "unavailable"
            if not ok:
                self._save_pending(store, pending, session, identity, record)
                copy = io.format_ai_error(outcome)
                return jsonify(
                    message=(
                        "We could not complete your check-in right now. "
                        "Your answers are still here; please try again."
                    ),
                    error_code=outcome,
                    safety_flag=safety,
                    advisor=copy["speak_to_advisor"],
                ), 503
            saved, outcome = self._save_evaluated(store, pending, session, identity, outcome)
            if not saved.get("ok"):
                return jsonify(
                    message=(
                        "We could not save your check-in just now. "
                        "Your answers are still here; please try again."
                    )
                ), 500
            token = secrets.token_urlsafe(32)
            pending.store_result(token, outcome, saved=True)
            session["checkin_token"] = token
            return jsonify(ok=True, result=presenter.build(outcome, saved=True))

        @app.get("/records")
        def records_page():
            if not admin.is_admin(session):
                return redirect(url_for("admin_login"))
            return render_campus("records")

        @app.get("/api/records")
        def saved_records():
            if not admin.is_admin(session):
                return jsonify(message="Admin sign-in is required to view saved records."), 401
            try:
                loaded = store.load_all()
            except Exception as exc:
                logger.warning("Loading saved records failed: %s", type(exc).__name__)
                loaded = {"ok": False}
            if not loaded.get("ok") or loaded.get("error"):
                return jsonify(
                    message="Saved records could not be loaded. Please try again."
                ), 500
            records = records_query.current_version(loaded.get("records", []))
            cohorts = records_query.cohorts(records)
            query = request.args.get("student_id", "").strip()
            tier = request.args.get("tier", "").strip()
            cohort = request.args.get("cohort_year", "").strip()
            message = records_query.validate_filters(tier, cohort)
            if message:
                return jsonify(message=message), 400
            rows = records_query.rows(
                records, student_id=query, tier=tier, cohort=cohort, store=store
            )
            return jsonify(
                records=rows, total=len(records), matching=len(rows), cohorts=cohorts
            )

        @app.get("/result")
        def result():
            if not pending.current(session):
                return redirect(url_for("checkin"))
            return render_campus("result")

        @app.post("/save")
        def save_checkin():
            with pending.locked():
                entry = pending.current(session)
                if not entry:
                    return jsonify(
                        message="Your result has expired. Please start a new check-in."
                    ), 409
                if entry["saved"]:
                    return jsonify(ok=True, saved=True)
                try:
                    store.save(entry["record"])
                    entry["saved"] = True
                except DataStoreError as exc:
                    logger.warning("Retrying the pending save failed: %s", type(exc).__name__)
                    return jsonify(
                        message="Your check-in could not be saved. Please try again."
                    ), 500
                except Exception as exc:
                    logger.warning("Retrying the pending save failed: %s", type(exc).__name__)
                    return jsonify(
                        message="Your check-in could not be saved. Please try again."
                    ), 500
            return jsonify(ok=True, saved=True)

        @app.get("/new")
        def new_checkin():
            pending.clear(session)
            return redirect(url_for("checkin"))

    def _save_pending(self, store, pending, flask_session, identity, record) -> None:
        """AI did not finish. The same answers in this session are one pending row."""
        try:
            with pending.locked():
                pending_id = pending.matched_id(flask_session, identity)
                if pending_id is None:
                    record_id = uuid.uuid4().hex
                    try:
                        stored = store.save_pending({**record, "record_id": record_id})
                        pending.remember(
                            flask_session,
                            identity,
                            stored.get("record_id") or record_id,
                            pending_save=True,
                        )
                    except DataStoreError:
                        logger.warning("Pending check-in could not be saved")
                else:
                    pending.remember(flask_session, identity, pending_id, pending_save=True)
        except Exception:
            logger.warning("Pending check-in could not be saved")

    def _save_evaluated(self, store, pending, flask_session, identity, outcome) -> tuple[dict, dict]:
        try:
            with pending.locked():
                pending_id = pending.matched_id(flask_session, identity)
                try:
                    if pending_id:
                        outcome = {**outcome, "record_id": pending_id}
                        stored = store.replace_pending(pending_id, outcome)
                    else:
                        stored = store.save(outcome)
                    stored_id = stored.get("record_id")
                    if stored_id:
                        pending.remember(
                            flask_session, identity, stored_id, pending_save=False
                        )
                    return {"ok": True, "record": stored}, outcome
                except DataStoreError as exc:
                    logger.warning("Saving the check-in failed: %s", type(exc).__name__)
                    return {"ok": False}, outcome
        except Exception as exc:
            logger.warning("Saving the check-in failed: %s", type(exc).__name__)
            return {"ok": False}, outcome
