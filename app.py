"""DoNotStress — student-facing Flask check-in app.

This checkout wires the layers that are already here:

  1. io_manager.validate_student_form(...)
  2. ai_manager.analyse_student(...) — MUST succeed (Gemini)
  3. io_manager format_soft_label / format_tips / format_speak_to_advisor_panel

Logic and Data are later steps. Importing them is optional so the server
still starts when those modules are absent. The call sites are marked below.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

import ai_manager
import io_manager

# Logic plugs in later via logic_manager.apply_logic (source becomes ai_logic).
# Data plugs in later via data_manager.save_record(..., opt_in=True).
try:
    import logic_manager
except ImportError:
    logic_manager = None

try:
    import data_manager
except ImportError:
    data_manager = None

logger = logging.getLogger(__name__)

SESSION_RECORD_KEY = "pending_record"
SESSION_SAVED_KEY = "checkin_saved"
AI_FAILURE_HTTP_STATUS = 503
_AI_SUCCESS_SOURCES = frozenset({
    "gemini",
    "ai",
    "ai_manager",
    "gemini+logic",
    "ai_logic",
})
_BLOCKED_SOURCES = frozenset({
    "logic_fallback",
    "fallback",
    "logic_only",
    "logic",
})


def _ai_error_copy(error: Any) -> dict[str, Any]:
    """Map analyse_student's error payload to io_manager error-page copy."""
    if error is None:
        return io_manager.format_ai_unavailable_error()
    if isinstance(error, dict):
        code = error.get("error_code")
        detail = error.get("detail")
        if code:
            return io_manager.format_ai_error(code, detail=detail)
        return io_manager.format_ai_unavailable_error(detail)
    code = ai_manager.classify_ai_error(error)
    return io_manager.format_ai_error(code, detail=str(error))


def _is_successful_ai_record(record: Any) -> bool:
    """True for a Gemini record (or a later Logic finalize of one)."""
    if not isinstance(record, dict):
        return False
    if record.get("ok") is False:
        return False
    source = str(record.get("source", "")).strip().lower()
    if source in _BLOCKED_SOURCES:
        return False
    required = ("soft_label", "tips", "speak_prominence")
    if any(key not in record for key in required):
        return False
    return record.get("ai_ok") is True or source in _AI_SUCCESS_SOURCES


def process_checkin(
    record: dict[str, Any],
    *,
    generate_fn: Callable[[str, str, str], str] | None = None,
    max_attempts: int = 3,
    retry_delay_sec: float = 0.5,
) -> tuple[bool, dict[str, Any]]:
    """Run mandatory AI. Finalize with Logic only when that module exists.

    Returns (True, record) on success.
    Returns (False, io_manager error-copy dict) on AI failure, or when
    Logic is present and refuses the record. Never invents a Logic-only outcome.
    """
    ok, enriched, error = ai_manager.analyse_student(
        record,
        generate_fn=generate_fn,
        max_attempts=max_attempts,
        retry_delay_sec=retry_delay_sec,
    )
    if not ok or not isinstance(enriched, dict):
        copy = _ai_error_copy(error)
        logger.warning(
            "AI check-in failed (%s): %s",
            copy.get("error_code"),
            copy.get("hint"),
        )
        return False, copy

    # Logic plugs in here later. apply_logic finalizes the Gemini record
    # (ok=True, source="ai_logic", ai_ok=True). Until logic_manager.py is
    # added, the result page shows the AI fields directly.
    if logic_manager is None:
        return True, enriched

    finalized = logic_manager.apply_logic(enriched)
    if not isinstance(finalized, dict) or not finalized.get("ok"):
        reason = None
        if isinstance(finalized, dict):
            reason = finalized.get("message") or finalized.get("error")
        logger.warning("Logic refused to finalize an AI record: %s", reason)
        return False, io_manager.format_ai_unavailable_error(reason)

    return True, finalized


def _result_view(record: dict[str, Any]) -> dict[str, Any]:
    """Build template context from an evaluated record via io_manager formatters."""
    return {
        "soft": io_manager.format_soft_label(record.get("soft_label")),
        "tips": io_manager.format_tips(record.get("tips")),
        "advisor": io_manager.format_speak_to_advisor_panel(
            record.get("speak_prominence")
        ),
        "summary": io_manager.format_student_record(record),
        "saved": bool(session.get(SESSION_SAVED_KEY)),
        "can_save": data_manager is not None,
    }


def _form_values(form=None) -> dict[str, str]:
    values = {key: "" for key in io_manager.FORM_FIELDS}
    if form is None:
        return values
    getter = getattr(form, "get", None)
    if getter is None:
        return values
    for key in io_manager.FORM_FIELDS:
        raw = getter(key)
        values[key] = "" if raw is None else str(raw)
    return values


def _clear_pending_checkin() -> None:
    session.pop(SESSION_RECORD_KEY, None)
    session.pop(SESSION_SAVED_KEY, None)


def _render_ai_error(copy: dict[str, Any], *, status: int = AI_FAILURE_HTTP_STATUS):
    flash(copy.get("heading") or "We couldn't complete your check-in", "error")
    return render_template("ai_error.html", **copy), status


def create_app(test_config: dict[str, Any] | None = None) -> Flask:
    app = Flask(__name__)
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "dev-insecure-donotstress"),
        DATA_PATH=os.environ.get("DONOTSTRESS_DATA_PATH") or None,
        AI_GENERATE_FN=None,
        AI_MAX_ATTEMPTS=int(os.environ.get("AI_MAX_ATTEMPTS", "3")),
        AI_RETRY_DELAY_SEC=float(os.environ.get("AI_RETRY_DELAY_SEC", "0.5")),
    )
    if test_config:
        app.config.update(test_config)

    @app.context_processor
    def inject_form_meta():
        return {
            "form_fields": io_manager.FORM_FIELDS,
            "form_prompts": io_manager.FORM_PROMPTS,
            "scale_min": io_manager.SCALE_MIN,
            "scale_max": io_manager.SCALE_MAX,
            "sleep_min": io_manager.SLEEP_HOURS_MIN,
            "sleep_max": io_manager.SLEEP_HOURS_MAX,
            "sleep_step": io_manager.SLEEP_HOURS_STEP,
            "student_id_example": io_manager.STUDENT_ID_EXAMPLE,
            "scale_fields": (
                "stress_level",
                "academic_workload",
                "financial_stress",
                "social_support",
            ),
        }

    @app.get("/")
    def checkin():
        return render_template(
            "checkin.html",
            values=_form_values(),
            errors={},
        )

    @app.post("/")
    def submit_checkin():
        ok, payload = io_manager.validate_student_form(request.form)
        if not ok:
            return render_template(
                "checkin.html",
                values=_form_values(request.form),
                errors=payload,
            ), 400

        ok, result = process_checkin(
            payload,
            generate_fn=app.config.get("AI_GENERATE_FN"),
            max_attempts=app.config.get("AI_MAX_ATTEMPTS", 3),
            retry_delay_sec=app.config.get("AI_RETRY_DELAY_SEC", 0.5),
        )
        if not ok:
            _clear_pending_checkin()
            return _render_ai_error(result)

        session[SESSION_RECORD_KEY] = result
        session[SESSION_SAVED_KEY] = False
        return redirect(url_for("result"))

    @app.get("/result")
    def result():
        record = session.get(SESSION_RECORD_KEY)
        if not record:
            flash("Start with a check-in first.", "info")
            return redirect(url_for("checkin"))
        if not _is_successful_ai_record(record):
            _clear_pending_checkin()
            return _render_ai_error(io_manager.format_ai_unavailable_error())
        return render_template("result.html", **_result_view(record))

    @app.post("/save")
    def save_checkin():
        record = session.get(SESSION_RECORD_KEY)
        if not record:
            flash("Start with a check-in first.", "info")
            return redirect(url_for("checkin"))
        if not _is_successful_ai_record(record):
            _clear_pending_checkin()
            return _render_ai_error(io_manager.format_ai_unavailable_error())

        # Data plugs in here later. data_manager.save_record(record, opt_in=True)
        # writes the check-in only after the student ticks the box. Until
        # data_manager.py exists, the opt-in form stays hidden and nothing
        # is written.
        if data_manager is None:
            flash("Saving isn't available yet.", "info")
            return redirect(url_for("result"))

        opted_in = request.form.get("opt_in")
        if not opted_in:
            flash(
                "Nothing was saved. Tick the box if you want to save this check-in.",
                "info",
            )
            return redirect(url_for("result"))

        saved = data_manager.save_record(
            record,
            data_path=app.config.get("DATA_PATH"),
            opt_in=True,
        )
        if saved.get("ok"):
            session[SESSION_SAVED_KEY] = True
            flash("Your check-in was saved on this computer.", "success")
        else:
            flash(saved.get("error") or "Could not save your check-in.", "error")
        return redirect(url_for("result"))

    @app.get("/new")
    def new_checkin():
        _clear_pending_checkin()
        return redirect(url_for("checkin"))

    return app


app = create_app()


if __name__ == "__main__":
    # Fail fast before the server binds. Request-time AI errors still use
    # analyse_student; this only stops a start with a missing/blank key.
    ai_manager.require_gemini_api_key()
    debug = os.environ.get("FLASK_DEBUG", "1").lower() not in {"0", "false", "no"}
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=debug)
