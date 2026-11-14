"""The Flask routes: HTTP and session handling only.

WebController talks only to App use-case methods. It never constructs a
CheckInRecord, never catches a storage exception, and never reaches into
app.io or app.jobs. History cookies, the result store and admin sessions
are private methods and fields on this controller.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections.abc import Mapping
from typing import TYPE_CHECKING

from flask import (Flask, Response, jsonify, redirect, render_template,
                   request, session, url_for)
from flask.typing import ResponseReturnValue
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.security import check_password_hash

from json_types import JSONObject

if TYPE_CHECKING:
    from main import App


class WebController:
    """Registers every route on the Flask app and answers each request.

    It knows the App it serves (association) and calls into it for every
    check-in, record and page. Flask lives here so App stays independent
    of the web framework.
    """

    CALM_FAILURE: str = ("We could not complete your check-in right now. "
                         "Your answers are still here; please try again.")
    HISTORY_LOCKED: str = (
        "To keep check-ins private, history is only shown for check-ins "
        "completed on this device. Complete a check-in here first.")
    HISTORY_COOKIE_NAME: str = "dns_history"
    HISTORY_MAX_AGE: int = 180 * 24 * 60 * 60
    HISTORY_MAX_IDS: int = 24
    HISTORY_DIGEST_LENGTH: int = 32
    ADMIN_USERNAME: str = "admin"
    ADMIN_MAX_PASSWORD_LENGTH: int = 256
    ADMIN_SESSION_SECONDS: float = 1800
    ADMIN_MAX_ATTEMPTS: int = 5
    ADMIN_WINDOW_SECONDS: float = 300
    RESULT_TTL_SECONDS: float = 1800

    def __init__(self, app: App, flask: Flask | None = None, *,
                 test_config: Mapping[str, object] | None = None) -> None:
        self.__app: App = app
        if flask is None:
            flask = Flask(__name__, root_path=str(app.ROOT))
            secure_cookie = os.environ.get(
                "SESSION_COOKIE_SECURE", "").strip().lower() in {
                    "1", "true", "yes"}
            flask.config.update(
                SECRET_KEY=app.secret_key,
                SESSION_COOKIE_HTTPONLY=True,
                SESSION_COOKIE_SAMESITE="Lax",
                SESSION_COOKIE_SECURE=secure_cookie,
                MAX_CONTENT_LENGTH=app.MAX_CONTENT_LENGTH,
                TESTING=app.testing,
            )
        if test_config:
            flask.config.update(test_config)
        self.__flask: Flask = flask
        self.__secret: bytes = str(flask.config["SECRET_KEY"]).encode("utf-8")
        self.__results: dict[str, dict[str, object]] = {}
        self.__results_lock: threading.Lock = threading.Lock()
        self.__admin_tokens: dict[str, float] = {}
        self.__admin_attempts: dict[str, list[float]] = {}
        self.__admin_lock: threading.Lock = threading.Lock()
        flask.extensions["admin_sessions"] = self.__admin_tokens
        self.__register(flask)

    @property
    def flask(self) -> Flask:
        return self.__flask

    def run(self, host: str, port: int, debug: bool) -> None:
        """Start the Flask server."""
        self.__flask.run(host=host, port=port, debug=debug)

    # --- Student pages ---------------------------------------------------

    def home(self) -> ResponseReturnValue:
        return self.__render_campus()

    def retired_page(self) -> ResponseReturnValue:
        """Legacy URL from the removed garden page."""
        return redirect(url_for("checkin"))

    def submit_checkin(self) -> ResponseReturnValue:
        values = (request.get_json(silent=True) if request.is_json
                  else request.form)
        if not isinstance(values, Mapping):
            return jsonify(message="Please submit a check-in form."), 400
        checked = self.__app.validate_form(values)
        if not checked.get("ok"):
            return jsonify(errors=checked.get("errors"),
                           safety_flag=checked.get("safety_flag"),
                           advisor=checked.get("advisor")), 400
        self.__clear_result()
        record = checked["record"]
        if not isinstance(record, dict):
            raise TypeError("Validated record must be a dict.")
        job = self.__app.submit_checkin(
            record,
            self.__owner_id(),
            str(session.get("pending_fingerprint", "")),
            str(session.get("pending_record_id", "")),
        )
        if int(job.get("http_status") or 0) == 429:
            return jsonify(job.get("payload") or {
                "message": "Too many check-ins are running right now."}), 429
        job_id = str(job["job_id"])
        return jsonify(status=job.get("status") or "queued", jobId=job_id,
                       statusUrl=url_for("checkin_status", job_id=job_id)
                       ), 202

    def checkin_status(self, job_id: str) -> ResponseReturnValue:
        """Still working (202), or the check-in's final response."""
        raw_wait = request.args.get("wait", default=0.0, type=float)
        wait = min(max(raw_wait or 0.0, 0.0), 2.0)
        owner = self.__owner_id()
        outcome = self.__app.job_status(job_id, owner, wait=wait)
        http_status = int(outcome.get("http_status") or 500)
        if http_status == 202:
            return jsonify(outcome.get("payload") or {"status": "running",
                                                      "jobId": job_id}), 202
        response = self.__respond(outcome)
        if http_status in (200, 500, 503):
            self.__app.forget_job(job_id, owner)
        return response

    def result(self) -> ResponseReturnValue:
        """Refreshing only reads the stored result; nothing is re-saved."""
        if self.__current_result() is None:
            return redirect(url_for("checkin"))
        return self.__render_campus("result")

    def save_checkin(self) -> ResponseReturnValue:
        """Every result is saved before it is shown, so this only confirms."""
        if self.__current_result() is None:
            return jsonify(message="Your result has expired. Please start "
                           "a new check-in."), 409
        return jsonify(ok=True, saved=True)

    def new_checkin(self) -> ResponseReturnValue:
        self.__clear_result()
        return redirect(url_for("checkin"))

    def history_page(self) -> ResponseReturnValue:
        return self.__render_campus("history")

    def lookup_history(self) -> ResponseReturnValue:
        """This browser's own check-in scores and trend for a Student ID.

        Non-admin browsers only see check-ins whose record_id matches a
        signed digest in the dns_history cookie, never another browser's
        submissions for the same Student ID.
        """
        values = (request.get_json(silent=True) if request.is_json
                  else request.form)
        form = values if isinstance(values, Mapping) else {}
        ok, student_id = self.__app.validate_student_id(form.get("student_id"))
        if not ok:
            return jsonify(message=student_id), 400
        held = set(self.__history_digests(
            request.cookies.get(self.HISTORY_COOKIE_NAME)))
        visible = None if self.__is_admin() else (
            lambda record_id: self.__history_digest(record_id) in held)
        page = self.__app.student_history(student_id, visible)
        if not page.get("ok"):
            return jsonify(message="Your history could not be loaded. "
                           "Please try again."), 500
        history = page.get("history") or {}
        if (visible is not None and isinstance(history, dict)
                and not (history.get("entries") or history.get("pending"))):
            return jsonify(message=self.HISTORY_LOCKED), 403
        return jsonify(history=history)

    # --- Admin pages -----------------------------------------------------

    def admin_login(self) -> ResponseReturnValue:
        if self.__is_admin():
            return redirect(url_for("records_page"))
        token = self.__csrf_token()
        error, status = None, 200
        if request.method == "POST":
            values = (request.get_json(silent=True) if request.is_json
                      else request.form)
            form = values if isinstance(values, Mapping) else {}
            address = request.remote_addr or "local"
            if not self.__admin_record_attempt(address):
                error, status = ("Too many sign-in attempts. Please try "
                                 "again in five minutes."), 429
            elif self.__admin_credentials_match(form.get("username", ""),
                                                form.get("password", "")):
                self.__admin_revoke(session.get("admin_token"))
                session["admin_token"] = self.__admin_issue(address)
                session["csrf_token"] = secrets.token_urlsafe(32)
                return redirect(url_for("records_page"))
            else:
                error, status = "Incorrect username or password.", 401
        page = render_template("admin_login.html", error=error,
                               csrf_token=token)
        return page, status

    def admin_logout(self) -> ResponseReturnValue:
        self.__admin_revoke(session.pop("admin_token", None))
        self.__clear_result()
        self.__app.forget_submission(str(session.get("owner_id", "")))
        session.clear()
        response = redirect(url_for("checkin"))
        response.delete_cookie(self.HISTORY_COOKIE_NAME)
        return response

    def records_page(self) -> ResponseReturnValue:
        if not self.__is_admin():
            return redirect(url_for("admin_login"))
        return self.__render_campus("records")

    def saved_records(self) -> ResponseReturnValue:
        """Saved check-ins for staff; never free text or keys."""
        if not self.__is_admin():
            return jsonify(message="Admin sign-in is required to view "
                           "saved records."), 401
        tier = request.args.get("tier", "").strip()
        cohort = request.args.get("cohort_year", "").strip()
        problem = self.__app.validate_record_filters(tier, cohort)
        if problem:
            return jsonify(message=problem), 400
        page = self.__app.admin_records(
            tier, cohort, request.args.get("student_id", "").strip())
        if not page.get("ok"):
            return jsonify(message="Saved records could not be loaded. "
                           "Please try again."), 500
        payload = {key: value for key, value in page.items() if key != "ok"}
        return jsonify(payload)

    # --- Service ---------------------------------------------------------

    def health(self) -> ResponseReturnValue:
        return jsonify(self.__app.health())

    def check_request(self) -> ResponseReturnValue | None:
        """Expire old state, then require the CSRF token on every POST."""
        if request.endpoint == "static":
            return None
        self.__expire_results()
        self.__admin_expire()
        self.__app.expire_jobs()
        if request.method != "POST":
            return None
        expected = str(session.get("csrf_token", ""))
        provided = request.headers.get("X-CSRF-Token", "")
        if not provided and not request.is_json:
            provided = request.form.get("csrf_token", "")
        if not expected or not secrets.compare_digest(
                provided.encode("utf-8"), expected.encode("utf-8")):
            return jsonify(message="This page has expired. Reload and try "
                           "again."), 403
        return None

    def prevent_caching(self, response: Response) -> Response:
        if request.endpoint != "static":
            response.headers["Cache-Control"] = "no-store"
        return response

    def too_large(self, error: RequestEntityTooLarge) -> ResponseReturnValue:
        return jsonify(message="Your response is too long. Please shorten "
                       "it and try again."), 413

    # --- Helpers ---------------------------------------------------------

    def __register(self, flask: Flask) -> None:
        flask.before_request(self.check_request)
        flask.after_request(self.prevent_caching)
        flask.register_error_handler(413, self.too_large)
        routes = (
            ("/", "checkin", self.home, ("GET",)),
            ("/", "submit_checkin", self.submit_checkin, ("POST",)),
            ("/checkin/status/<job_id>", "checkin_status",
             self.checkin_status, ("GET",)),
            ("/garden", "retired_page", self.retired_page, ("GET",)),
            ("/result", "result", self.result, ("GET",)),
            ("/save", "save_checkin", self.save_checkin, ("POST",)),
            ("/new", "new_checkin", self.new_checkin, ("GET",)),
            ("/admin/login", "admin_login", self.admin_login,
             ("GET", "POST")),
            ("/admin/logout", "admin_logout", self.admin_logout, ("POST",)),
            ("/records", "records_page", self.records_page, ("GET",)),
            ("/api/records", "saved_records", self.saved_records, ("GET",)),
            ("/history", "history_page", self.history_page, ("GET",)),
            ("/api/history", "lookup_history", self.lookup_history,
             ("POST",)),
            ("/health", "health", self.health, ("GET",)),
        )
        for rule, endpoint, view, methods in routes:
            flask.add_url_rule(rule, endpoint, view, methods=list(methods))

    def __respond(self, outcome: JSONObject) -> Response:
        """Turn a pipeline outcome into the session update and response."""
        http_status = int(outcome.get("http_status") or 500)
        payload = outcome.get("payload")
        if not isinstance(payload, dict):
            payload = {"message": self.CALM_FAILURE}
        if outcome.get("status") == "save_failed":
            response = jsonify(payload)
            response.status_code = 500
            return response
        if http_status == 503:
            if outcome.get("saved"):
                session["pending_fingerprint"] = str(
                    outcome.get("fingerprint") or "")
                session["pending_record_id"] = str(
                    outcome.get("pending_id") or "")
            response = jsonify(payload)
            response.status_code = 503
        elif http_status == 200 and outcome.get("result") is not None:
            session.pop("pending_fingerprint", None)
            session.pop("pending_record_id", None)
            result = outcome["result"]
            if not isinstance(result, dict):
                raise TypeError("Check-in result payload must be a dict.")
            self.__clear_result()
            session["checkin_token"] = self.__put_result(result)
            response = jsonify(payload)
            response.status_code = 200
        else:
            response = jsonify(payload)
            response.status_code = http_status
        if outcome.get("saved"):
            record_id = str(outcome.get("record_id")
                            or outcome.get("pending_id") or "")
            if record_id:
                self.__grant_history(response, record_id)
        return response

    def __grant_history(self, response: Response, record_id: str) -> None:
        held = request.cookies.get(self.HISTORY_COOKIE_NAME)
        response.set_cookie(
            self.HISTORY_COOKIE_NAME,
            self.__history_grant(held, record_id),
            max_age=self.HISTORY_MAX_AGE, httponly=True,
            samesite="Lax", secure=request.is_secure)

    def __history_grant(self, cookie: str | None, record_id: str) -> str:
        wanted = self.__history_digest(record_id)
        held = [digest for digest in self.__history_digests(cookie)
                if digest != wanted]
        return ".".join((held + [wanted])[-self.HISTORY_MAX_IDS:])

    def __history_digests(self, cookie: str | None) -> list[str]:
        parts = (cookie or "").split(".")
        return [part for part in parts
                if len(part) == self.HISTORY_DIGEST_LENGTH and part.isalnum()]

    def __history_digest(self, record_id: str) -> str:
        mac = hmac.new(self.__secret, record_id.strip().encode("utf-8"),
                       hashlib.sha256)
        return mac.hexdigest()[:self.HISTORY_DIGEST_LENGTH]

    def __render_campus(self, page: str = "home") -> str:
        csrf = self.__csrf_token()
        self.__owner_id()
        stored = self.__current_result()
        return render_template("checkin.html", boot={
            "page": page,
            "survey": self.__app.page_config(),
            "isAdmin": self.__is_admin(),
            "adminLoginUrl": url_for("admin_login"),
            "result": stored,
            "csrfToken": csrf,
            "submitUrl": url_for("submit_checkin"),
            "saveUrl": url_for("save_checkin"),
            "newUrl": url_for("new_checkin"),
            "homeUrl": url_for("checkin"),
            "resultUrl": url_for("result"),
            "recordsPageUrl": url_for("records_page"),
            "recordsUrl": url_for("saved_records"),
            "historyPageUrl": url_for("history_page"),
            "historyUrl": url_for("lookup_history"),
        })

    def __csrf_token(self) -> str:
        return str(session.setdefault("csrf_token", secrets.token_urlsafe(32)))

    def __owner_id(self) -> str:
        return str(session.setdefault("owner_id", secrets.token_urlsafe(16)))

    def __is_admin(self) -> bool:
        token = session.get("admin_token")
        if self.__admin_is_valid(token):
            return True
        session.pop("admin_token", None)
        return False

    def __put_result(self, result: JSONObject) -> str:
        token = secrets.token_urlsafe(32)
        with self.__results_lock:
            self.__results[token] = {
                "record": result, "created": time.monotonic()}
        return token

    def __current_result(self) -> JSONObject | None:
        token = session.get("checkin_token")
        if not token:
            return None
        with self.__results_lock:
            entry = self.__results.get(str(token))
        if not entry:
            return None
        record = entry.get("record")
        return record if isinstance(record, dict) else None

    def __clear_result(self) -> None:
        token = session.pop("checkin_token", None)
        if token:
            with self.__results_lock:
                self.__results.pop(str(token), None)

    def __expire_results(self) -> None:
        ttl = float(
            self.__flask.config.get("PENDING_TTL_SECONDS", self.RESULT_TTL_SECONDS)
        )
        cutoff = time.monotonic() - ttl
        with self.__results_lock:
            self.__results = {
                token: entry for token, entry in self.__results.items()
                if float(entry.get("created") or 0) > cutoff}

    def __admin_credentials_match(self, username: object,
                                  password: object) -> bool:
        expected_hash = str(
            self.__flask.config.get("ADMIN_PASSWORD_HASH")
            or os.environ.get("ADMIN_PASSWORD_HASH", "")
        ).strip()
        if not expected_hash:
            return False
        user = str(username or "")
        secret = str(password or "")
        if (user != self.ADMIN_USERNAME
                or len(secret) > self.ADMIN_MAX_PASSWORD_LENGTH):
            # Still hash a dummy value so timing does not leak the username.
            check_password_hash(expected_hash, secret or "x")
            return False
        return check_password_hash(expected_hash, secret)

    def __admin_issue(self, address: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.__admin_lock:
            self.__admin_tokens[token] = time.monotonic()
        return token

    def __admin_is_valid(self, token: object) -> bool:
        if not isinstance(token, str) or not token:
            return False
        session_ttl = float(
            self.__flask.config.get(
                "ADMIN_SESSION_SECONDS", self.ADMIN_SESSION_SECONDS)
        )
        with self.__admin_lock:
            issued = self.__admin_tokens.get(token)
            if issued is None:
                return False
            if time.monotonic() - issued >= session_ttl:
                self.__admin_tokens.pop(token, None)
                return False
            return True

    def __admin_revoke(self, token: object) -> None:
        if isinstance(token, str) and token:
            with self.__admin_lock:
                self.__admin_tokens.pop(token, None)

    def __admin_record_attempt(self, address: str) -> bool:
        """True when this address is still allowed to try. False if throttled."""
        now = time.monotonic()
        window = float(
            self.__flask.config.get(
                "ADMIN_LOGIN_WINDOW_SECONDS", self.ADMIN_WINDOW_SECONDS)
        )
        cutoff = now - window
        with self.__admin_lock:
            stamps = [stamp for stamp in self.__admin_attempts.get(address, [])
                      if stamp > cutoff]
            if len(stamps) >= self.ADMIN_MAX_ATTEMPTS:
                self.__admin_attempts[address] = stamps
                return False
            stamps.append(now)
            self.__admin_attempts[address] = stamps
            return True

    def __admin_expire(self) -> None:
        now = time.monotonic()
        session_ttl = float(
            self.__flask.config.get(
                "ADMIN_SESSION_SECONDS", self.ADMIN_SESSION_SECONDS)
        )
        window = float(
            self.__flask.config.get(
                "ADMIN_LOGIN_WINDOW_SECONDS", self.ADMIN_WINDOW_SECONDS)
        )
        session_cutoff = now - session_ttl
        attempt_cutoff = now - window
        with self.__admin_lock:
            self.__admin_tokens = {
                token: issued for token, issued in self.__admin_tokens.items()
                if issued > session_cutoff}
            self.__admin_attempts = {
                address: [stamp for stamp in stamps if stamp > attempt_cutoff]
                for address, stamps in self.__admin_attempts.items()
                if any(stamp > attempt_cutoff for stamp in stamps)}
