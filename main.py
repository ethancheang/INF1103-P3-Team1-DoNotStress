"""Front-end demo. Requires Flask and the existing templates/ and static/.

No manager modules, AI calls, database, or file saves are used.
Submitted answers are validated but not retained; results are fixed samples.
"""

import os
import re
from decimal import Decimal, InvalidOperation

from flask import Flask, flash, redirect, render_template, request, session, url_for


SCALE_FIELDS = (
    "stress_level", "academic_workload", "financial_stress", "social_support"
)
FORM_PROMPTS = {
    "student_id": "Student ID",
    "sleep_hours": "How many hours did you sleep last night?",
    "stress_level": "How stressed do you feel? (1 = low, 10 = high)",
    "academic_workload": "How heavy is your academic workload? (1 = low, 10 = high)",
    "financial_stress": "How much financial stress do you feel? (1 = low, 10 = high)",
    "social_support": "How supported do you feel? (1 = low, 10 = high)",
    "feelings_text": "Anything else you would like to share?",
}
FORM_FIELDS = tuple(FORM_PROMPTS)


def form_values(form=None):
    return {key: form.get(key, "") if form is not None else "" for key in FORM_FIELDS}


def validate_form(values):
    errors = {}
    if not re.fullmatch(r"(?:23|24|25|26)[0-9]{5}", values["student_id"].strip()):
        errors["student_id"] = "Enter 7 digits starting with 23, 24, 25, or 26."
    try:
        hours = Decimal(values["sleep_hours"])
        if not hours.is_finite() or not 0 <= hours <= 24 or hours % Decimal("0.5"):
            raise ValueError
    except (InvalidOperation, ValueError):
        errors["sleep_hours"] = "Enter 0 to 24 hours in steps of 0.5."
    for key in SCALE_FIELDS:
        if values[key] not in {str(n) for n in range(1, 11)}:
            errors[key] = "Choose a value from 1 to 10."
    if len(values["feelings_text"]) > 2000:
        errors["feelings_text"] = "Use 2000 characters or fewer."
    return errors


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.environ.get("FLASK_SECRET_KEY", "frontend-demo-only"))
    if test_config:
        app.config.update(test_config)

    @app.context_processor
    def inject_form_meta():
        return dict(
            form_fields=FORM_FIELDS, form_prompts=FORM_PROMPTS,
            scale_fields=SCALE_FIELDS, scale_min=1, scale_max=10,
            sleep_min=0, sleep_max=24, sleep_step=0.5,
            student_id_example="2605581", demo_mode=True,
        )

    @app.get("/")
    def checkin():
        flash("Front-end demo: results are samples and saving is simulated.", "info")
        return render_template("checkin.html", values=form_values(), errors={})

    @app.post("/")
    def submit_checkin():
        values = form_values(request.form)
        errors = validate_form(values)
        if errors:
            return render_template("checkin.html", values=values, errors=errors), 400
        # Store only demo UI flags, not student answers.
        session["frontend_demo_ready"] = True
        session["frontend_demo_saved"] = False
        return redirect(url_for("result"))

    @app.get("/result")
    def result():
        if not session.get("frontend_demo_ready"):
            flash("Start with a check-in first.", "info")
            return redirect(url_for("checkin"))
        return render_template(
            "result.html",
            soft={
                "tone": "supportive",
                "heading": "Your sample check-in result",
                "label": "Demo result",
                "body": "This is fixed sample content for testing the layout. "
                        "It is not an assessment of your answers.",
            },
            tips={
                "heading": "Sample tips",
                "items": [
                    {"text": "Take a short break between study sessions."},
                    {"text": "Divide an assignment into smaller tasks."},
                    {"text": "Make time to connect with someone you trust."},
                ],
            },
            advisor={
                "prominence": "medium",
                "heading": "Sample advisor panel",
                "body": "This panel is for layout testing only.",
                "cta": "Contact details below are demo placeholders.",
                "mailto": "#", "email": "Demo email (not configured)",
                "helpline": "Demo helpline (not configured)",
            },
            summary="Demo only; submitted answers are not retained.",
            saved=bool(session.get("frontend_demo_saved")),
        )

    @app.post("/save")
    def save_checkin():
        if not session.get("frontend_demo_ready"):
            return redirect(url_for("checkin"))
        if request.form.get("opt_in", "").lower() not in {"yes", "on", "true", "1"}:
            flash("Tick the box to test the saved state. Nothing was saved.", "info")
        else:
            session["frontend_demo_saved"] = True
            flash("Demo: saved state simulated. No check-in was saved to a file or database.", "success")
        return redirect(url_for("result"))

    @app.get("/new")
    def new_checkin():
        session.pop("frontend_demo_ready", None)
        session.pop("frontend_demo_saved", None)
        return redirect(url_for("checkin"))

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", "5000")), debug=True)