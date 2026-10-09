"""DoNotStress — student-facing Flask check-in app.

Workflow:
1. Validate student inputs using io_manager.
2. Save inputs immediately if the student has consented.
3. Call Gemini through ai_manager.
4. Apply Logic only when Gemini succeeds.
5. Display the result or an AI error page.

Student inputs can be saved even when Gemini is unavailable.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable

from dotenv import load_dotenv
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
import data_manager
import io_manager
import Logic_manager


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()

logger = logging.getLogger(__name__)

SESSION_RECORD_KEY = "pending_record"
SESSION_SAVED_KEY = "checkin_saved"
SESSION_INPUT_KEY = "pending_student_input"
SESSION_CONSENT_KEY = "checkin_consent"

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


# ============================================================
# AI ERROR HANDLING
# ============================================================

def _ai_error_copy(error: Any) -> dict[str, Any]:
    """Convert AI errors into user-friendly messages."""

    if error is None:
        return io_manager.format_ai_unavailable_error()

    if isinstance(error, dict):
        code = error.get("error_code")
        detail = error.get("detail")

        if code:
            return io_manager.format_ai_error(
                code,
                detail=detail,
            )

        return io_manager.format_ai_unavailable_error(detail)

    code = ai_manager.classify_ai_error(error)

    return io_manager.format_ai_error(
        code,
        detail=str(error),
    )


def _is_successful_ai_record(record: Any) -> bool:
    """Check whether a record was successfully processed by Gemini."""

    if not isinstance(record, dict):
        return False

    if record.get("ok") is False:
        return False

    source = str(
        record.get("source", "")
    ).strip().lower()

    if source in _BLOCKED_SOURCES:
        return False

    required = (
        "soft_label",
        "tips",
        "speak_prominence",
    )

    if any(key not in record for key in required):
        return False

    return (
        record.get("ai_ok") is True
        or source in _AI_SUCCESS_SOURCES
    )


# ============================================================
# AI + LOGIC PROCESSING
# ============================================================

def process_checkin(
    record: dict[str, Any],
    *,
    generate_fn: Callable[[str, str, str], str] | None = None,
    max_attempts: int = 3,
    retry_delay_sec: float = 0.5,
) -> tuple[bool, dict[str, Any]]:
    """
    Run Gemini first, followed by Logic.

    Gemini failure does not prevent the student's
    previously consented inputs from being saved.
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

    finalized = Logic_manager.apply_logic(enriched)

    if not isinstance(finalized, dict) or not finalized.get("ok"):
        reason = None

        if isinstance(finalized, dict):
            reason = (
                finalized.get("message")
                or finalized.get("error")
            )

        logger.warning(
            "Logic refused to finalize an AI record: %s",
            reason,
        )

        return False, io_manager.format_ai_unavailable_error(
            reason
        )

    return True, finalized


# ============================================================
# RESULT PAGE
# ============================================================

def _result_view(record: dict[str, Any]) -> dict[str, Any]:
    """Prepare the result page using io_manager formatters."""

    return {
        "soft": io_manager.format_soft_label(
            record.get("soft_label")
        ),
        "tips": io_manager.format_tips(
            record.get("tips")
        ),
        "advisor": io_manager.format_speak_to_advisor_panel(
            record.get("speak_prominence")
        ),
        "summary": io_manager.format_student_record(record),
        "saved": bool(session.get(SESSION_SAVED_KEY)),
    }


# ============================================================
# FORM HELPERS
# ============================================================

def _form_values(form=None) -> dict[str, str]:
    """Get student form values."""

    values = {
        key: ""
        for key in io_manager.FORM_FIELDS
    }

    if form is None:
        return values

    getter = getattr(form, "get", None)

    if getter is None:
        return values

    for key in io_manager.FORM_FIELDS:
        raw = getter(key)

        values[key] = (
            ""
            if raw is None
            else str(raw)
        )

    return values


def _clear_pending_checkin() -> None:
    """Remove the previous check-in from the session."""

    session.pop(SESSION_RECORD_KEY, None)
    session.pop(SESSION_SAVED_KEY, None)
    session.pop(SESSION_INPUT_KEY, None)
    session.pop(SESSION_CONSENT_KEY, None)


def _render_ai_error(
    copy: dict[str, Any],
    *,
    status: int = AI_FAILURE_HTTP_STATUS,
):
    """Display the Gemini error page."""

    flash(
        copy.get("heading")
        or "We couldn't complete your check-in",
        "error",
    )

    return render_template(
        "ai_error.html",
        **copy,
    ), status


# ============================================================
# CREATE FLASK APP
# ============================================================

def create_app(
    test_config: dict[str, Any] | None = None,
) -> Flask:

    app = Flask(__name__)

    app.config.from_mapping(
        SECRET_KEY=os.environ.get(
            "FLASK_SECRET_KEY",
            "dev-insecure-donotstress",
        ),
        DATA_PATH=(
            os.environ.get("DONOTSTRESS_DATA_PATH")
            or None
        ),
        AI_GENERATE_FN=None,
        AI_MAX_ATTEMPTS=int(
            os.environ.get("AI_MAX_ATTEMPTS", "3")
        ),
        AI_RETRY_DELAY_SEC=float(
            os.environ.get("AI_RETRY_DELAY_SEC", "0.5")
        ),
    )

    if test_config:
        app.config.update(test_config)

    # ========================================================
    # FORM METADATA
    # ========================================================

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

    # ========================================================
    # CHECK-IN PAGE
    # ========================================================

    @app.get("/")
    def checkin():

        return render_template(
            "checkin.html",
            values=_form_values(),
            errors={},
        )

    # ========================================================
    # SUBMIT CHECK-IN
    # ========================================================

    @app.post("/")
    def submit_checkin():

        # Step 1: Validate student form
        ok, payload = io_manager.validate_student_form(
            request.form
        )

        if not ok:
            return render_template(
                "checkin.html",
                values=_form_values(request.form),
                errors=payload,
            ), 400

        # Clear any previous submission
        _clear_pending_checkin()

        # Step 2: Read student consent from checkin.html
        student_consent = request.form.get("opt_in")

        consent_given = str(
            student_consent or ""
        ).strip().lower() in {
            "yes",
            "true",
            "1",
            "on",
        }

        session[SESSION_CONSENT_KEY] = consent_given
        session[SESSION_INPUT_KEY] = payload

        # Step 3: Save inputs BEFORE Gemini
        if consent_given:

            save_result = data_manager.save_student_input(
                payload,
                data_path=app.config.get("DATA_PATH"),
                opt_in=True,
            )

            if save_result.get("ok"):
                session[SESSION_SAVED_KEY] = True

                logger.info(
                    "Student input saved successfully."
                )

            else:
                session[SESSION_SAVED_KEY] = False

                logger.error(
                    "Unable to save student input: %s",
                    save_result.get("error"),
                )

                flash(
                    "Your check-in could not be saved.",
                    "error",
                )

        else:
            session[SESSION_SAVED_KEY] = False

        # Step 4: Process through Gemini
        ok, result = process_checkin(
            payload,
            generate_fn=app.config.get("AI_GENERATE_FN"),
            max_attempts=app.config.get(
                "AI_MAX_ATTEMPTS",
                3,
            ),
            retry_delay_sec=app.config.get(
                "AI_RETRY_DELAY_SEC",
                0.5,
            ),
        )

        # Step 5: Gemini failed
        # Student inputs were already saved if consent was given
        if not ok:
            _clear_pending_checkin()
            return _render_ai_error(result)

        # Step 6: Gemini succeeded
        session[SESSION_RECORD_KEY] = result

        return redirect(url_for("result"))

    # ========================================================
    # RESULT PAGE
    # ========================================================

    @app.get("/result")
    def result():

        record = session.get(SESSION_RECORD_KEY)

        if not record:
            flash(
                "Start with a check-in first.",
                "info",
            )
            return redirect(url_for("checkin"))

        if not _is_successful_ai_record(record):
            _clear_pending_checkin()

            return _render_ai_error(
                io_manager.format_ai_unavailable_error()
            )

        return render_template(
            "result.html",
            **_result_view(record),
        )

    # ========================================================
    # SAVE RESULT
    # ========================================================

    @app.post("/save")
    def save_checkin():

        record = session.get(SESSION_RECORD_KEY)

        if not record:
            flash(
                "Start with a check-in first.",
                "info",
            )
            return redirect(url_for("checkin"))

        if not _is_successful_ai_record(record):
            _clear_pending_checkin()

            return _render_ai_error(
                io_manager.format_ai_unavailable_error()
            )

        # Prevent duplicate saves
        if session.get(SESSION_SAVED_KEY):
            flash(
                "Your check-in has already been saved.",
                "info",
            )
            return redirect(url_for("result"))

        # Check explicit consent on result page
        opted_in = request.form.get("opt_in")

        if not opted_in:
            flash(
                "Nothing was saved. Tick the box "
                "if you want to save this check-in.",
                "info",
            )
            return redirect(url_for("result"))

        # Save AI-processed record
        saved = data_manager.save_record(
            record,
            data_path=app.config.get("DATA_PATH"),
            opt_in=True,
        )

        if saved.get("ok"):
            session[SESSION_SAVED_KEY] = True

            flash(
                "Your check-in was saved on this computer.",
                "success",
            )

        else:
            flash(
                saved.get("error")
                or "Could not save your check-in.",
                "error",
            )

        return redirect(url_for("result"))

    # ========================================================
    # NEW CHECK-IN
    # ========================================================

    @app.get("/new")
    def new_checkin():

        _clear_pending_checkin()

        return redirect(url_for("checkin"))

    return app


# ============================================================
# START APP
# ============================================================

app = create_app()


if __name__ == "__main__":

    debug = os.environ.get(
        "FLASK_DEBUG",
        "1",
    ).lower() not in {
        "0",
        "false",
        "no",
    }

    port = int(
        os.environ.get("PORT", "5000")
    )

    app.run(
        host="127.0.0.1",
        port=port,
        debug=debug,
    )