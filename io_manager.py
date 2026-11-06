"""Student input validation and presentation for the evidence-v3 (1-5) survey.

Question wording, scales and scoring definitions live in survey.py.
Student ID: seven ASCII digits beginning with 2. Reflection is ephemeral.
"""
from abc import ABC, abstractmethod
from copy import deepcopy
from typing import Any

import survey

FORM_FIELDS = {key:key for key in ['student_id', *survey.QUESTION_MAP, 'feelings_text']}
FORM_PROMPTS = {'student_id':'Student ID', 'feelings_text':'Anything on your mind about school or life lately?',
                **{q['key']:q['prompt'] for q in survey.QUESTIONS}}
RECORD_FIELD_ORDER = tuple(FORM_FIELDS)
REQUIRED_FORM_FIELDS = ('student_id', *(q['key'] for q in survey.QUESTIONS if not q.get('optional')))
STUDENT_ID_EXAMPLE = '2605581'

# ---------------------------------------------------------------------------
# Soft labels, tips allow-list, advisor contacts (hardcoded — never invent)
# ---------------------------------------------------------------------------

SOFT_LABELS = (
    "You're doing ok",
    "Worth a check-in",
    "Please reach out",
)

SOFT_LABEL_COPY = {
    "You're doing ok": {
        "label": "You're doing ok",
        "heading": "You're doing ok",
        "body": "Your check-in looks steady. Keep looking after yourself.",
        "tone": "reassuring",
    },
    "Worth a check-in": {
        "label": "Worth a check-in",
        "heading": "Worth a check-in",
        "body": (
            "Some things look a bit heavier right now. "
            "A conversation could help."
        ),
        "tone": "supportive",
    },
    "Please reach out": {
        "label": "Please reach out",
        "heading": "Please reach out",
        "body": (
            "Please reach out for support. "
            "You do not have to handle this on your own."
        ),
        "tone": "urgent",
    },
}

# Tip IDs that templates / other layers may pass into format_tips.
# Copy is student-facing. Do not add phone numbers or extra emails here.
TIPS_ALLOWLIST = {
    "sleep_routine": (
        "Try to keep a regular sleep schedule, including on weekends."
    ),
    "rest_a_little_more": (
        "If you can, give yourself a bit more rest — even 30 extra minutes "
        "can help."
    ),
    "short_breaks": (
        "Take short, planned breaks between study blocks instead of pushing "
        "through without a pause."
    ),
    "workload_chunks": (
        "Break larger assignments into smaller tasks and spread them across "
        "the week."
    ),
    "money_worries": (
        "If money is on your mind, campus support can help you find the "
        "right next step."
    ),
    "talk_to_someone": (
        "Reach out to a friend, classmate, or family member — you do not "
        "have to handle this alone."
    ),
    "keep_social_contact": (
        "Stay in touch with people who help you feel supported, even with "
        "a short check-in."
    ),
    "feelings_check_in": (
        "Name how you have been feeling and give yourself permission to "
        "ask for help if school feels heavy."
    ),
}

SPEAK_PROMINENCE = ("low", "medium", "high")

# Real contacts only. Model / callers must never invent others.
ADVISOR_EMAIL = "SITCounselling@SingaporeTech.edu.sg"
ADVISOR_HELPLINE = "6592 2030"
ADVISOR_MAILTO = "mailto:SITCounselling@SingaporeTech.edu.sg"
SOS_HELPLINE = "1767"
MINDLINE_HELPLINE = "1771"

ADVISOR_CONTACTS = {
    "email": ADVISOR_EMAIL,
    "helpline": ADVISOR_HELPLINE,
    "sos": SOS_HELPLINE,
    "mindline": MINDLINE_HELPLINE,
    "mailto": ADVISOR_MAILTO,
}

SPEAK_PANEL_COPY = {
    "low": {
        "heading": "Support is available",
        "body": (
            "If you would like to talk, you can contact SIT Counselling."
        ),
        "cta": "Optional: get in touch",
    },
    "medium": {
        "heading": "Consider speaking with someone",
        "body": (
            "It may help to talk with SIT Counselling about how you have "
            "been feeling."
        ),
        "cta": "Reach out when you are ready",
    },
    "high": {
        "heading": "Please reach out",
        "body": (
            "Please contact SIT Counselling. You do not have to handle "
            "this on your own."
        ),
        "cta": "Contact support now",
    },
}

# Gemini is mandatory for every check-in result. These formatters exist so
# Flask can show a hard-stop error page — not a logic-only / tips happy path.
AI_UNAVAILABLE_HEADING = "We couldn't complete your check-in"
AI_UNAVAILABLE_BODY = (
    "This check-in needs Gemini AI before we can show a result. "
    "AI is required for every record, so we cannot finish your check-in "
    "right now. Please try again later."
)
AI_UNAVAILABLE_ACTION_LABEL = "Try again"
AI_UNAVAILABLE_TONE = "urgent"
AI_REQUIRED_HINT = (
    "Operators/dev: Gemini AI is required for every check-in. Confirm "
    "GEMINI_API_KEY is set in the environment. Do not share or display the key."
)

AI_RATE_LIMITED_BODY = (
    "Our check-in assistant is busy right now. "
    "Your answers have been saved and will be reviewed soon."
)

AI_ERROR_CODES = (
    "missing_api_key",
    "timeout",
    "invalid_response",
    "retries_exhausted",
    "rate_limited",
    "unavailable",
)

AI_ERROR_HINTS = {
    "missing_api_key": (
        "Operators/dev: GEMINI_API_KEY is not set. Add it to the environment "
        "and restart the app. Never paste the key into the page or into "
        "student-facing copy."
    ),
    "timeout": (
        "Operators/dev: the Gemini request timed out. Confirm GEMINI_API_KEY "
        "is set and the service is reachable, then try again. Do not share "
        "the key."
    ),
    "invalid_response": (
        "Operators/dev: Gemini returned a response that could not be used. "
        "Confirm GEMINI_API_KEY is set and check server logs. Do not expose "
        "the key."
    ),
    "retries_exhausted": (
        "Operators/dev: Gemini failed after retries. Confirm GEMINI_API_KEY "
        "is set and the service is reachable. Do not expose the key."
    ),
    "rate_limited": (
        "Operators/dev: every Gemini model was rate-limited. "
        "The check-in is saved as pending. Do not share the API key."
    ),
    "unavailable": AI_REQUIRED_HINT,
}


# ---------------------------------------------------------------------------
# Internal helpers (pure)
# ---------------------------------------------------------------------------

class _InputText:
    """Stateless normalization and operator-detail redaction."""

    @staticmethod
    def _as_text(raw) -> str:
        """Normalize raw input to a stripped string. None becomes empty."""
        if raw is None:
            return ""
        return str(raw).strip()

    @staticmethod
    def _form_get(form_dict, key: str):
        """Read one key from a Flask request.form-like mapping."""
        if form_dict is None:
            return ""
        getter = getattr(form_dict, "get", None)
        if getter is None:
            return ""
        value = getter(key)
        if value is None:
            return ""
        return value

    @staticmethod
    def _looks_like_secret(text: str) -> bool:
        """True when operator text might contain a key or token — do not show it."""
        if not text:
            return False
        compact = "".join(text.split())
        lowered = compact.lower()
        if "gemini_api_key=" in lowered or "api_key=" in lowered:
            return True
        if "bearer" in lowered and len(compact) > 20:
            return True
        # Long token-like strings (Google API keys are typically 39+ chars).
        if len(compact) >= 32 and compact.isalnum():
            return True
        return False

    @staticmethod
    def _sanitize_operator_detail(raw) -> str | None:
        """Keep a short operator note; drop anything that looks like a secret."""
        text = _InputText._as_text(raw)
        if not text:
            return None
        if _InputText._looks_like_secret(text):
            return None
        if len(text) > 200:
            text = text[:200].rstrip() + "…"
        return text


# ---------------------------------------------------------------------------
# Object-oriented validation, formatting, and console adapters.
# ---------------------------------------------------------------------------


class FieldValidator(ABC):
    """Contract: validate raw input into (True, value) or (False, message).

    Invalid user input is reported, not raised. Implementations do not retain
    answers or mutate the input. Callers need no concrete-type checks.
    """

    @abstractmethod
    def validate(self, raw: Any) -> tuple[bool, Any]:
        """Return a normalized value or a user-facing validation error."""


class StudentIdValidator(FieldValidator):
    """Validate the institution's seven-digit student identifier."""

    def validate(self, raw: Any) -> tuple[bool, Any]:
        text = _InputText._as_text(raw)
        if len(text) != 7 or not text.isascii() or not text.isdigit() or not text.startswith("2"):
            return False, "Student ID must be exactly 7 digits and start with 2 (e.g. 2605581)."
        return True, text


class ReflectionValidator(FieldValidator):
    """Validate optional reflection without storing its contents."""

    def validate(self, raw: Any) -> tuple[bool, Any]:
        if raw is not None and not isinstance(raw, str):
            return False, 'Please enter text or leave this blank.'
        text = _InputText._as_text(raw)
        if len(text) > 2000:
            return False, 'Please keep your reflection within 2,000 characters.'
        return True, text


class SurveyQuestionValidator(FieldValidator):
    """Adapt a survey question to the shared validation contract."""

    def __init__(self, question, survey_definition=survey):
        self._question = deepcopy(question)
        self._survey = survey_definition

    def validate(self, raw: Any) -> tuple[bool, Any]:
        return self._survey.validate_question(raw, self._question)


class FormField:
    """A named input field associated with an independently usable policy."""

    def __init__(self, key: str, validator: FieldValidator):
        self._key = key
        self._validator = validator

    @property
    def key(self) -> str:
        return self._key

    def validate_from(self, values) -> tuple[bool, Any]:
        return self._validator.validate(_InputText._form_get(values, self._key))


class FormValidationResult:
    """Own one validation outcome; never expose partial or mutable records.

    Construction is for the validator, after all fields have been checked.
    Raw reflection is excluded even if a caller supplies it accidentally.
    """

    def __init__(self, *, record=None, errors=None):
        if (record is None) == (errors is None):
            raise ValueError('Supply either a valid record or field errors.')
        if errors is not None and not errors:
            raise ValueError('An invalid result must contain field errors.')
        self._errors = deepcopy(errors) if errors is not None else {}
        self._record = deepcopy(record) if record is not None else None
        if self._record is not None:
            self._record.pop('feelings_text', None)

    @property
    def is_valid(self) -> bool:
        return self._record is not None

    @property
    def errors(self) -> dict:
        return deepcopy(self._errors)

    def to_record(self) -> dict:
        """Export a detached record for the AI pipeline only after success."""
        if not self.is_valid:
            raise ValueError('Cannot export a record from invalid input.')
        return deepcopy(self._record)

    def as_legacy_tuple(self) -> tuple[bool, dict]:
        return self.is_valid, self.to_record() if self.is_valid else self.errors


class InputValidator:
    """Coordinate field validators without retaining student answers.

    Default field validators are owned parts. Injected validators are shared
    collaborators, allowing a policy to change without editing this class.
    """

    def __init__(self, survey_definition=survey, *, student_id_validator=None,
                 reflection_validator=None):
        self._survey = survey_definition
        self._student_id_validator = (student_id_validator if student_id_validator is not None
                                      else StudentIdValidator())
        self._reflection_validator = (reflection_validator if reflection_validator is not None
                                      else ReflectionValidator())
        self._questions = deepcopy(survey_definition.QUESTIONS)
        self._fields = (
            FormField('student_id', self._student_id_validator),
            *(FormField(q['key'], SurveyQuestionValidator(q, self._survey))
              for q in self._questions),
            FormField('feelings_text', self._reflection_validator),
        )

    @property
    def questions(self):
        """Return a defensive copy so callers cannot alter the survey."""
        return deepcopy(self._questions)

    def validate_question(self, raw, question):
        return SurveyQuestionValidator(question, self._survey).validate(raw)

    def normalize_form_value(self, raw) -> str:
        return _InputText._as_text(raw)

    def validate_student_id(self, raw) -> tuple[bool, str]:
        return self._student_id_validator.validate(raw)

    def validate_feelings_text(self, raw):
        return self._reflection_validator.validate(raw)

    def validate_student_form(self, form_dict):
        """Compatibility contract for callers that still expect a tuple."""
        return self.validate_form(form_dict).as_legacy_tuple()

    def validate_form(self, form_dict) -> FormValidationResult:
        """Validate a submission through the form's owned field objects."""
        record, errors = {}, {}
        text = ''
        for field in self._fields:
            key = field.key
            ok, value = field.validate_from(form_dict)
            if not ok:
                errors[key] = value
            elif key == 'feelings_text':
                text = value
            else:
                record[key] = value
        if errors:
            return FormValidationResult(errors=errors)
        # Reflection is checked locally on the server, then discarded. Never sent
        # to Gemini or retained in pending/saved records.
        record['safety_flag'] = self._survey.safety_check(text)
        record['survey_version'] = self._survey.VERSION
        return FormValidationResult(record=record)


class ResultFormatter:
    """Build presentation dictionaries without scoring or storing records."""

    def __init__(self, survey_definition=survey):
        self._questions = {q['key']: deepcopy(q) for q in survey_definition.QUESTIONS}
        self._prompts = {
            'student_id': FORM_PROMPTS['student_id'],
            **{key: q['prompt'] for key, q in self._questions.items()},
            'feelings_text': FORM_PROMPTS['feelings_text'],
        }

    def format_soft_label(self, soft_label) -> dict:
        """Return template copy for a soft label.

        soft_label must be one of SOFT_LABELS:
          "You're doing ok" | "Worth a check-in" | "Please reach out"
        """
        text = _InputText._as_text(soft_label)
        copy = SOFT_LABEL_COPY.get(text)
        if copy is None:
            allowed = ", ".join(f'"{label}"' for label in SOFT_LABELS)
            return {
                "label": "",
                "heading": "",
                "body": "",
                "tone": "",
                "error": f"Unknown soft label. Use one of: {allowed}.",
            }
        return {
            "label": copy["label"],
            "heading": copy["heading"],
            "body": copy["body"],
            "tone": copy["tone"],
            "error": None,
        }

    def format_tips(self, tips) -> dict:
        """Return template copy for an allow-listed tip list.

        `tips` is a list of tip IDs (preferred) or exact allow-list strings.
        Unknown tips are dropped — this formatter never invents copy.
        Duplicates keep the first occurrence only.
        """
        items = []
        seen = set()
        if tips is None:
            tips = []
        for raw in tips:
            text = _InputText._as_text(raw)
            if not text or text in seen:
                continue
            tip_id = None
            tip_text = None
            if text in TIPS_ALLOWLIST:
                tip_id = text
                tip_text = TIPS_ALLOWLIST[text]
            else:
                for known_id, known_text in TIPS_ALLOWLIST.items():
                    if text == known_text:
                        tip_id = known_id
                        tip_text = known_text
                        break
            if tip_id is None:
                continue
            seen.add(tip_id)
            seen.add(tip_text)
            items.append({"id": tip_id, "text": tip_text})
        return {
            "heading": "Suggestions for you",
            "items": items,
            "texts": [item["text"] for item in items],
        }

    def format_speak_to_advisor_panel(self, speak_prominence) -> dict:
        """Return the Speak-to-Advisor panel copy and hardcoded contacts.

        speak_prominence is "low" | "medium" | "high" and changes tone only.
        Contacts are always the same real values — never invented:
          email    SITCounselling@SingaporeTech.edu.sg
          helpline 6592 2030 (SIT Counselling 24-hour helpline)
          sos      1767
          mindline 1771
          mailto   mailto:SITCounselling@SingaporeTech.edu.sg

        Unknown prominence still includes those contacts and uses medium copy.
        """
        prominence = _InputText._as_text(speak_prominence).lower()
        copy = SPEAK_PANEL_COPY.get(prominence)
        error = None
        if copy is None:
            prominence = "medium"
            copy = SPEAK_PANEL_COPY["medium"]
            allowed = ", ".join(SPEAK_PROMINENCE)
            error = f"Unknown speak_prominence. Use one of: {allowed}."
        return {
            "prominence": prominence,
            "heading": copy["heading"],
            "body": copy["body"],
            "cta": copy["cta"],
            "email": ADVISOR_EMAIL,
            "helpline": ADVISOR_HELPLINE,
            "sos": SOS_HELPLINE,
            "mindline": MINDLINE_HELPLINE,
            "mailto": ADVISOR_MAILTO,
            "contacts": dict(ADVISOR_CONTACTS),
            "error": error,
        }

    def _ai_failure_copy(self, error_code, detail=None) -> dict:
        """Shared payload for AI-required failure pages (no soft-label happy path)."""
        code = _InputText._as_text(error_code).lower()
        unknown = False
        if code not in AI_ERROR_CODES:
            unknown = bool(code)
            code = "unavailable"
        if not code:
            code = "unavailable"

        body = AI_RATE_LIMITED_BODY if code == "rate_limited" else AI_UNAVAILABLE_BODY
        hint = AI_ERROR_HINTS[code]
        reason = _InputText._sanitize_operator_detail(detail)
        if reason:
            hint = f"{hint} Detail: {reason}."

        panel = self.format_speak_to_advisor_panel("high")
        error = None
        if unknown:
            allowed = ", ".join(AI_ERROR_CODES)
            error = f"Unknown AI error_code. Use one of: {allowed}."

        return {
            "heading": AI_UNAVAILABLE_HEADING,
            "body": body,
            "message": body,
            "hint": hint,
            "action_label": AI_UNAVAILABLE_ACTION_LABEL,
            "tone": AI_UNAVAILABLE_TONE,
            "ai_required": True,
            "error_code": code,
            "reason": reason,
            "speak_to_advisor": panel,
            "email": ADVISOR_EMAIL,
            "helpline": ADVISOR_HELPLINE,
            "mailto": ADVISOR_MAILTO,
            "contacts": {
                "email": ADVISOR_EMAIL,
                "helpline": ADVISOR_HELPLINE,
                "mailto": ADVISOR_MAILTO,
            },
            "error": error,
        }

    def format_ai_error(self, error_code, detail=None) -> dict:
        """Map an AI failure code to the same student-facing error dict.

        Known codes: missing_api_key, timeout, invalid_response,
        retries_exhausted, rate_limited, unavailable. rate_limited uses calm
        student copy. Unknown codes still return a valid error page
        (unavailable copy + contacts) and set `error`.
        """
        return self._ai_failure_copy(error_code, detail=detail)

    def format_student_record(self, record: dict) -> dict:
        """Return a plain dict of labelled values for a confirmation template."""
        if not record:
            return {
                "heading": "Your check-in",
                "fields": [],
                "empty": True,
            }
        fields = []
        for key in self._prompts:
            if key not in record:
                continue
            value = record[key]
            if key == "feelings_text":
                display = str(value).strip() if value is not None else ""
                if not display:
                    display = "(skipped)"
            elif key == "sleep_hours_avg" and value is not None:
                display = f"{float(value):.1f}"
            elif value is not None and self._questions.get(key, {}).get("options"):
                q = self._questions[key]
                display = f"{value} · {q['options'][int(value) - q['min']]}"
            else:
                display = "(skipped)" if value is None else str(value)
            fields.append({
                "key": key,
                "label": self._prompts[key],
                "value": display,
            })
        return {
            "heading": "Your check-in",
            "fields": fields,
            "empty": len(fields) == 0,
        }


class ConsoleIO:
    """Console adapter composed from validation and presentation services."""

    def __init__(self, validator=None, formatter=None, *, read=None, write=None):
        self._validator = validator if validator is not None else InputValidator()
        self._formatter = formatter if formatter is not None else ResultFormatter()
        self._read = read
        self._write = write

    def _read_line(self, prompt):
        return (self._read if self._read is not None else input)(prompt)

    def _write_line(self, message):
        (self._write if self._write is not None else print)(message)

    def print_message(self, message: str) -> None:
        self._write_line(message)

    def print_error(self, message: str) -> None:
        self._write_line(f"Error: {message}")

    def display_record(self, record: dict[str, Any]) -> None:
        """Print one check-in record using format_student_record."""
        view = self._formatter.format_student_record(record)
        self._write_line(view["heading"])
        for field in view["fields"]:
            self._write_line(f"  {field['label']}: {field['value']}")

    def display_list(self, records: list[dict[str, Any]]) -> None:
        """Print a short one-line summary for each saved record."""
        if not records:
            self._write_line("No records.")
            return
        for number, record in enumerate(records, 1):
            self._write_line(f"{number}. {record.get('student_id', '?')} | "
                  f"{record.get('risk_category', '?')} | {record.get('stress_score', '?')}")

    def display_result(self, result: dict[str, Any]) -> None:
        """Print the outcome of a check-in using the existing formatters."""
        if not result or not result.get("ok"):
            code = (result or {}).get("error_code") or (result or {}).get("error")
            copy = self._formatter.format_ai_error(code)
            self._write_line(copy.get("heading", "We couldn't complete your check-in"))
            self._write_line(copy.get("body", ""))
            return
        self._write_line(self._formatter.format_soft_label(result.get("soft_label"))["heading"] or result.get("soft_label"))
        self._write_line(f"Stress score: {result.get('stress_score')}")
        for text in self._formatter.format_tips(result.get("tips"))["texts"]:
            self._write_line(f"  - {text}")

    def _prompt_until_valid(self, prompt: str, validator):
        """Read a line, validate, and re-prompt with the error until valid."""
        while True:
            raw = self._read_line(prompt)
            ok, result = validator(raw)
            if ok:
                return result
            self.print_error(result)

    def get_student_id(self) -> str:
        return self._prompt_until_valid(
            "Student ID (7 digits starting with 2, e.g. 2605581): ",
            self._validator.validate_student_id,
        )

    def collect_student_record(self):
        """CLI uses the same question definitions and validation as the website."""
        values = {'student_id':self.get_student_id()}
        for q in self._validator.questions:
            self.print_message(q['prompt'])
            if q.get('options'):
                self.print_message(' | '.join(f"{i + q['min']}: {label}" for i, label in enumerate(q['options'])))
            values[q['key']] = self._prompt_until_valid(
                f"{q['min']}–{q['max']}" + (' (optional; Enter to skip)' if q.get('optional') else '') + ': ',
                lambda raw, item=q: self._validator.validate_question(raw, item))
        values['feelings_text'] = self._prompt_until_valid('Optional reflection (not saved): ', self._validator.validate_feelings_text)
        return self._validator.validate_form(values).to_record()


# Transitional bound-method aliases for Phase 1 integrations and tests.
# Production web routes use explicit objects; there is no duplicate behavior.
_default_validator = InputValidator()
_default_formatter = ResultFormatter()
_default_console = ConsoleIO(_default_validator, _default_formatter)

normalize_form_value = _default_validator.normalize_form_value
validate_student_id = _default_validator.validate_student_id
validate_feelings_text = _default_validator.validate_feelings_text
validate_student_form = _default_validator.validate_student_form
format_soft_label = _default_formatter.format_soft_label
format_tips = _default_formatter.format_tips
format_speak_to_advisor_panel = _default_formatter.format_speak_to_advisor_panel
_ai_failure_copy = _default_formatter._ai_failure_copy
format_ai_error = _default_formatter.format_ai_error
format_student_record = _default_formatter.format_student_record
print_message = _default_console.print_message
print_error = _default_console.print_error
display_record = _default_console.display_record
display_list = _default_console.display_list
display_result = _default_console.display_result
_prompt_until_valid = _default_console._prompt_until_valid
get_student_id = _default_console.get_student_id
collect_student_record = _default_console.collect_student_record


if __name__ == '__main__':
    _default_console.print_message(str(_default_formatter.format_student_record(
        _default_console.collect_student_record())))
