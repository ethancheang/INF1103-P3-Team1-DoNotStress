"""Student input validation and presentation for the evidence-v2 survey.

Question wording, scales and scoring definitions live in survey.py.
Student ID: seven ASCII digits beginning with 2. Reflection is ephemeral.
"""
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

ADVISOR_CONTACTS = {
    "email": ADVISOR_EMAIL,
    "helpline": ADVISOR_HELPLINE,
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

AI_ERROR_CODES = (
    "missing_api_key",
    "timeout",
    "invalid_response",
    "retries_exhausted",
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
    "unavailable": AI_REQUIRED_HINT,
}


# ---------------------------------------------------------------------------
# Internal helpers (pure)
# ---------------------------------------------------------------------------

def _as_text(raw) -> str:
    """Normalize raw input to a stripped string. None becomes empty."""
    if raw is None:
        return ""
    return str(raw).strip()


def _looks_like_int(text: str) -> bool:
    """True when text is a base-10 integer (optional leading + or -)."""
    if not text:
        return False
    if text[0] in "+-":
        return len(text) > 1 and text[1:].isdigit()
    return text.isdigit()


def _parse_int(raw) -> tuple[bool, int | str]:
    text = _as_text(raw)
    if not _looks_like_int(text):
        return False, "must be a whole number (integer)"
    return True, int(text)


def _parse_float(raw) -> tuple[bool, float | str]:
    text = _as_text(raw)
    if text == "":
        return False, "must be a number"
    lowered = text.lower()
    if lowered in {"nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        return False, "must be a finite number"
    try:
        value = float(text)
    except ValueError:
        return False, "must be a number"
    if value != value:  # NaN
        return False, "must be a finite number"
    if value == float("inf") or value == float("-inf"):
        return False, "must be a finite number"
    return True, value


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


def _sanitize_operator_detail(raw) -> str | None:
    """Keep a short operator note; drop anything that looks like a secret."""
    text = _as_text(raw)
    if not text:
        return None
    if _looks_like_secret(text):
        return None
    if len(text) > 200:
        text = text[:200].rstrip() + "…"
    return text


# ---------------------------------------------------------------------------
# Normalize helpers (Flask request.form strings)
# ---------------------------------------------------------------------------

def normalize_form_value(raw) -> str:
    """Strip a single form value. None becomes ''."""
    return _as_text(raw)


def extract_form_fields(form_dict) -> dict:
    """Return only the canonical FORM_FIELDS keys from a form mapping."""
    return {key: normalize_form_value(_form_get(form_dict, key)) for key in FORM_FIELDS}


# ---------------------------------------------------------------------------
# Validators — validate_X(raw) -> (ok, value_or_error)
# ---------------------------------------------------------------------------

def validate_student_id(raw) -> tuple[bool, str]:
    """Require exactly seven ASCII digits, beginning with 2."""
    text = _as_text(raw)
    if len(text) != 7 or not text.isascii() or not text.isdigit() or not text.startswith("2"):
        return False, "Student ID must be exactly 7 digits and start with 2 (e.g. 2605581)."
    return True, text

def validate_feelings_text(raw):
    if raw is not None and not isinstance(raw, str):
        return False, 'Please enter text or leave this blank.'
    text = _as_text(raw)
    if len(text) > 2000:
        return False, 'Please keep your reflection within 2,000 characters.'
    return True, text


def validate_student_form(form_dict):
    record, errors = {}, {}
    ok, value = validate_student_id(_form_get(form_dict, 'student_id'))
    (record if ok else errors)['student_id'] = value
    for q in survey.QUESTIONS:
        ok, value = survey.validate_question(_form_get(form_dict, q['key']), q)
        (record if ok else errors)[q['key']] = value
    ok, text = validate_feelings_text(_form_get(form_dict, 'feelings_text'))
    if not ok:
        errors['feelings_text'] = text
    if errors:
        return False, errors
    # Reflection is checked locally on the server, then discarded. Never sent
    # to Gemini or retained in pending/saved records.
    record['safety_flag'] = survey.safety_check(text)
    record['survey_version'] = survey.VERSION
    record.update(survey.score(record))
    return True, record


def collect_student_record_from_form(form_dict) -> tuple[bool, dict]:
    """Alias of validate_student_form for Flask call sites."""
    return validate_student_form(form_dict)


# ---------------------------------------------------------------------------
# Formatters for web templates — strings / plain dicts of copy; no print
# ---------------------------------------------------------------------------

def format_soft_label(soft_label) -> dict:
    """Return template copy for a soft label.

    soft_label must be one of SOFT_LABELS:
      "You're doing ok" | "Worth a check-in" | "Please reach out"
    """
    text = _as_text(soft_label)
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


def format_tips(tips) -> dict:
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
        text = _as_text(raw)
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


def format_speak_to_advisor_panel(speak_prominence) -> dict:
    """Return the Speak-to-Advisor panel copy and hardcoded contacts.

    speak_prominence is "low" | "medium" | "high" and changes tone only.
    Contacts are always the same real values — never invented:
      email    SITCounselling@SingaporeTech.edu.sg
      helpline 6592 2030
      mailto   mailto:SITCounselling@SingaporeTech.edu.sg

    Unknown prominence still includes those contacts and uses medium copy.
    """
    prominence = _as_text(speak_prominence).lower()
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
        "mailto": ADVISOR_MAILTO,
        "contacts": {
            "email": ADVISOR_EMAIL,
            "helpline": ADVISOR_HELPLINE,
            "mailto": ADVISOR_MAILTO,
        },
        "error": error,
    }


def _ai_failure_copy(error_code, detail=None) -> dict:
    """Shared payload for AI-required failure pages (no soft-label happy path)."""
    code = _as_text(error_code).lower()
    unknown = False
    if code not in AI_ERROR_CODES:
        unknown = bool(code)
        code = "unavailable"
    if not code:
        code = "unavailable"

    body = AI_UNAVAILABLE_BODY
    hint = AI_ERROR_HINTS[code]
    reason = _sanitize_operator_detail(detail)
    if reason:
        hint = f"{hint} Detail: {reason}."

    panel = format_speak_to_advisor_panel("high")
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


def format_ai_unavailable_error(reason=None) -> dict:
    """Return template copy when Gemini is required but unavailable.

    Plain dict for Flask error pages. Students are told AI is required and
    to try again later. Operators get a GEMINI_API_KEY hint (no secrets).
    Official SIT Counselling contacts stay visible via speak_to_advisor
    (high prominence) — this is not a logic-only / tips happy path.
    """
    return _ai_failure_copy("unavailable", detail=reason)


def format_ai_error(error_code, detail=None) -> dict:
    """Map an AI failure code to the same student-facing error dict.

    Known codes: missing_api_key, timeout, invalid_response,
    retries_exhausted, unavailable. Unknown codes still return a valid
    error page (unavailable copy + contacts) and set `error`.
    """
    return _ai_failure_copy(error_code, detail=detail)


def format_student_record(record: dict) -> dict:
    """Return a plain dict of labelled values for a confirmation template."""
    if not record:
        return {
            "heading": "Your check-in",
            "fields": [],
            "empty": True,
        }
    fields = []
    for key in RECORD_FIELD_ORDER:
        if key not in record:
            continue
        value = record[key]
        if key == "feelings_text":
            display = str(value).strip() if value is not None else ""
            if not display:
                display = "(skipped)"
        elif key == "sleep_hours_avg":
            display = f"{float(value):.1f}"
        else:
            display = "(skipped)" if value is None else str(value)
        fields.append({
            "key": key,
            "label": FORM_PROMPTS[key],
            "value": display,
        })
    return {
        "heading": "Your check-in",
        "fields": fields,
        "empty": len(fields) == 0,
    }


# ---------------------------------------------------------------------------
# Thin CLI helper — smoke tests only; field names match the web form
# ---------------------------------------------------------------------------

def print_message(message: str) -> None:
    print(message)


def print_error(message: str) -> None:
    print(f"Error: {message}")


def _prompt_until_valid(prompt: str, validator):
    """Read a line, validate, and re-prompt with the error until valid."""
    while True:
        raw = input(prompt)
        ok, result = validator(raw)
        if ok:
            return result
        print_error(result)


def get_student_id() -> str:
    return _prompt_until_valid(
        "Student ID (7 digits starting with 2, e.g. 2605581): ",
        validate_student_id,
    )


def collect_student_record():
    """CLI uses the same question definitions and validation as the website."""
    values = {'student_id':get_student_id()}
    for q in survey.QUESTIONS:
        print_message(q['prompt'])
        if q.get('options'):
            print_message(' | '.join(f"{i + q['min']}: {label}" for i, label in enumerate(q['options'])))
        values[q['key']] = _prompt_until_valid(
            f"{q['min']}–{q['max']}" + (' (optional; Enter to skip)' if q.get('optional') else '') + ': ',
            lambda raw, item=q: survey.validate_question(raw, item))
    values['feelings_text'] = _prompt_until_valid('Optional reflection (not saved): ', validate_feelings_text)
    return validate_student_form(values)[1]


if __name__ == '__main__':
    print_message(str(format_student_record(collect_student_record())))
