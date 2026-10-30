"""
DoNotStress — AI Processing Layer (ai_manager)

Sole owner of Gemini prompt construction, structured JSON API calls,
schema validation, and graceful retries.

Audience: students (local Flask web UI). Gemini calculates the stress
average from the 11 raw answers. This layer holds no domain logic: the
caller (main.py) passes in the scoring instructions for the prompt and a
check function, both from logic_manager, so the rules live in one place.
A reply that fails that check is treated like any other invalid response
and retried. This layer itself only builds the prompt, calls the API and
validates the reply's schema: required keys, types, ranges and allow-lists.

It does not send a student id, a reflection, or any precomputed score,
flag, or tier. It never invents soft_label / tips / speak_prominence when
Gemini fails, and it never falls back to logic_manager.

Pure procedural Python: functions only.
No terminal I/O (print / input), no business rules, no file persistence.

Pipeline position:
  User → io_manager → ai_manager (required) → data_manager
  On failure: structured error for io_manager.format_ai_error (no Logic substitute)
"""

from __future__ import annotations

import json
import math
import logging
import os
import time
from typing import Any, Callable, Mapping, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# I/O fields this layer may send to Gemini (student check-in only)
# ---------------------------------------------------------------------------

# Raw answers plus the questionnaire version. No student id, reflection,
# score, flag, or tier. Gemini calculates stress_score from these answers.
RAW_ANSWER_KEYS = (
    "pss_1",
    "pss_2",
    "pss_3",
    "pss_4",
    "sleep_hours_avg",
    "sleep_quality",
    "pas_workload",
    "pas_catchup",
    "fin_stress",
    "mspss_friends",
    "mspss_family",
)
STUDENT_PROMPT_FIELDS = RAW_ANSWER_KEYS + ("survey_version",)

# Wording and answer labels only. Scoring stays outside this module.
# Callers may pass survey.QUESTIONS (same key / prompt / options shape).
DEFAULT_QUESTIONS: tuple[dict[str, Any], ...] = (
    {
        "key": "pss_1",
        "prompt": (
            "In the past month, how often have you felt you couldn't "
            "control the important things in your life?"
        ),
        "options": ("Never", "Almost never", "Sometimes", "Fairly often", "Very often"),
    },
    {
        "key": "pss_2",
        "prompt": (
            "In the past month, how often have you felt confident "
            "handling your personal problems?"
        ),
        "options": ("Never", "Almost never", "Sometimes", "Fairly often", "Very often"),
        "reverse": True,
    },
    {
        "key": "pss_3",
        "prompt": (
            "In the past month, how often have you felt things were "
            "going well for you?"
        ),
        "options": ("Never", "Almost never", "Sometimes", "Fairly often", "Very often"),
        "reverse": True,
    },
    {
        "key": "pss_4",
        "prompt": (
            "In the past month, how often have you felt problems were "
            "piling up too much to handle?"
        ),
        "options": ("Never", "Almost never", "Sometimes", "Fairly often", "Very often"),
    },
    {
        "key": "sleep_hours_avg",
        "prompt": (
            "On average, how many hours of sleep have you gotten "
            "each night this week?"
        ),
        "min": 0,
        "max": 14,
        "step": 0.5,
        "low": "0 hours",
        "high": "14 hours",
    },
    {
        "key": "sleep_quality",
        "prompt": "During the past week, how would you rate your sleep quality overall?",
        "options": ("Very good", "Fairly good", "Okay", "Fairly bad", "Very bad"),
    },
    {
        "key": "pas_workload",
        "prompt": "I feel my coursework is too much to handle.",
        "options": ("Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"),
    },
    {
        "key": "pas_catchup",
        "prompt": "When I fall behind on my work, I find it hard to catch up.",
        "options": ("Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"),
    },
    {
        "key": "fin_stress",
        "prompt": "How stressed do you feel about your personal finances in general?",
        "options": (
            "No stress at all",
            "A little stress",
            "Moderate stress",
            "High stress",
            "Overwhelming stress",
        ),
    },
    {
        "key": "mspss_friends",
        "prompt": "I can count on my friends when things go wrong.",
        "options": ("Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"),
        "reverse": True,
    },
    {
        "key": "mspss_family",
        "prompt": "I get the emotional help and support I need from my family.",
        "options": ("Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"),
        "reverse": True,
    },
)

# ---------------------------------------------------------------------------
# Allow-lists. Tip copy lives in io_manager.format_tips — return IDs only.
# Every tip ID here is also in io_manager.TIPS_ALLOWLIST.
# emotional_distress and feelings_check_in are omitted: they need the
# reflection, and that text is never sent to Gemini.
# ---------------------------------------------------------------------------

SOFT_LABEL_OK = "You're doing ok"
SOFT_LABEL_CHECK_IN = "Worth a check-in"
SOFT_LABEL_REACH_OUT = "Please reach out"
SOFT_LABEL_OK_CURLY = "You’re doing ok"

SOFT_LABELS = (
    SOFT_LABEL_OK,
    SOFT_LABEL_CHECK_IN,
    SOFT_LABEL_REACH_OUT,
)
ALLOWED_SOFT_LABELS = frozenset(SOFT_LABELS)
_SOFT_LABEL_ALIASES = {
    SOFT_LABEL_OK: SOFT_LABEL_OK,
    SOFT_LABEL_OK_CURLY: SOFT_LABEL_OK,
    SOFT_LABEL_CHECK_IN: SOFT_LABEL_CHECK_IN,
    SOFT_LABEL_REACH_OUT: SOFT_LABEL_REACH_OUT,
}

SPEAK_PROMINENCE = ("low", "medium", "high")
ALLOWED_SPEAK_PROMINENCE = frozenset(SPEAK_PROMINENCE)
ALLOWED_RISK_CATEGORIES = frozenset({"Low", "Moderate", "High"})

ALLOWED_PRIMARY_STRESSORS = frozenset(
    {
        "sleep_deprivation",
        "high_stress",
        "academic_overload",
        "financial_pressure",
        "low_social_support",
    }
)

# IDs only — same keys as io_manager.TIPS_ALLOWLIST. Do not invent tip text.
ALLOWED_TIP_IDS = frozenset(
    {
        "sleep_routine",
        "rest_a_little_more",
        "short_breaks",
        "workload_chunks",
        "money_worries",
        "talk_to_someone",
        "keep_social_contact",
    }
)

# Allowed range for stress_score in Gemini's reply (a schema range check).
# The tier cut-offs are logic_manager's, not this module's.
STRESS_SCORE_MIN = 1.0
STRESS_SCORE_MAX = 5.0

# What Gemini must return. risk_score and recommended_support are added by logic_manager.
_REQUIRED_FIELDS = (
    "scored_items",
    "stress_score",
    "risk_category",
    "primary_stressors",
    "confidence",
    "reasoning",
    "soft_label",
    "tips",
    "speak_prominence",
)

# Named models only. gemini-3.6-flash first, then older fixed names.
# No moving alias such as gemini-flash-latest.
MODEL_CHAIN = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
)
_DEFAULT_MODEL = MODEL_CHAIN[0]
_FALLBACK_MODELS = MODEL_CHAIN[1:]
# 0 = most repeatable replies for the same answers (brief C4).
_DEFAULT_TEMPERATURE = 0.0
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY_SEC = 0.5
_DEFAULT_TIMEOUT_SEC = 30.0
# One check-in must not spend more than this many Gemini calls (daily quota).
MAX_TOTAL_CALLS = 4
# Extra try on the same model, and only for a timeout or bad JSON.
_SAME_MODEL_RETRIES = 1
_TIPS_MIN = 1
_TIPS_MAX = 3

# ---------------------------------------------------------------------------
# Structured AI failures — codes MUST match io_manager.format_ai_error
# ---------------------------------------------------------------------------

AI_SOURCE = "gemini"

ERROR_CODE_MISSING_API_KEY = "missing_api_key"
ERROR_CODE_TIMEOUT = "timeout"
ERROR_CODE_INVALID_RESPONSE = "invalid_response"
ERROR_CODE_RETRIES_EXHAUSTED = "retries_exhausted"
ERROR_CODE_RATE_LIMITED = "rate_limited"
ERROR_CODE_UNAVAILABLE = "unavailable"

AI_ERROR_CODES = (
    ERROR_CODE_MISSING_API_KEY,
    ERROR_CODE_TIMEOUT,
    ERROR_CODE_INVALID_RESPONSE,
    ERROR_CODE_RETRIES_EXHAUSTED,
    ERROR_CODE_RATE_LIMITED,
    ERROR_CODE_UNAVAILABLE,
)

_TIMEOUT_MARKERS = (
    "timeout",
    "timed out",
    "timed_out",
    "deadlineexceeded",
    "deadline exceeded",
    "read timed out",
)
_SCHEMA_MARKERS = (
    "schema validation",
    "not valid json",
    "jsondecodeerror",
    "jsondecode",
    "malformed",
    "missing required fields",
    "must be a json object",
    "empty ai response",
    "allow-list",
    "invalid json",
    "ai response must be",
)
_MISSING_KEY_MARKERS = (
    "missing_api_key",
    "gemini_api_key is not set",
    "api key is not set",
    "api_key is not set",
)
_RATE_LIMIT_MARKERS = (
    "429",
    "resource exhausted",
    "resourceexhausted",
    "too many requests",
    "toomanyrequests",
    "rate limit",
    "ratelimit",
    "quota",
)


def classify_ai_error(exc_or_message: Any) -> str:
    """
    Map an exception or message to one of AI_ERROR_CODES.

    Used by call_gemini and by Flask/I/O to pick format_ai_error copy.
    Unknown inputs map to "unavailable" (never invent a product outcome).
    """
    if isinstance(exc_or_message, dict):
        code = str(exc_or_message.get("error_code", "")).strip().lower()
        if code in AI_ERROR_CODES:
            return code
        exc_or_message = exc_or_message.get("detail", "")

    type_name = ""
    if isinstance(exc_or_message, BaseException):
        type_name = type(exc_or_message).__name__
        text = str(exc_or_message)
    elif exc_or_message is None:
        text = ""
    else:
        text = str(exc_or_message)

    combined = f"{type_name} {text}".strip().lower()
    if not combined:
        return ERROR_CODE_UNAVAILABLE

    if any(marker in combined for marker in _MISSING_KEY_MARKERS):
        return ERROR_CODE_MISSING_API_KEY
    if "gemini_api_key" in combined and (
        "not set" in combined or "missing" in combined or "blank" in combined
    ):
        return ERROR_CODE_MISSING_API_KEY

    if isinstance(exc_or_message, BaseException) and _is_rate_limited(exc_or_message):
        return ERROR_CODE_RATE_LIMITED
    if any(marker in combined for marker in _RATE_LIMIT_MARKERS):
        return ERROR_CODE_RATE_LIMITED

    if any(marker in combined for marker in _TIMEOUT_MARKERS):
        return ERROR_CODE_TIMEOUT

    if any(marker in combined for marker in _SCHEMA_MARKERS):
        return ERROR_CODE_INVALID_RESPONSE

    if "retries_exhausted" in combined or (
        "retries" in combined and "exhaust" in combined
    ):
        return ERROR_CODE_RETRIES_EXHAUSTED

    return ERROR_CODE_UNAVAILABLE


def _structured_ai_error(error_code: str, detail: str) -> dict[str, str]:
    """Build the failure dict Flask can pass to io_manager.format_ai_error."""
    code = error_code if error_code in AI_ERROR_CODES else ERROR_CODE_UNAVAILABLE
    return {
        "error_code": code,
        "detail": str(detail),
        "source": AI_SOURCE,
    }


def _final_ai_error(
    last_kind: str,
    last_detail: str,
    *,
    attempts: int,
    last_was_api_exception: bool,
    failure_kinds: list[str] | None = None,
) -> dict[str, str]:
    """
    Choose the structured code after the model chain ends.

    - every model rate-limited → rate_limited
    - timeout / DeadlineExceeded stay timeout (even after retries)
    - schema / malformed JSON stay invalid_response
    - other API exceptions after more than one attempt → retries_exhausted
    - other one-shot API / network failures → unavailable
    """
    if failure_kinds and all(kind == ERROR_CODE_RATE_LIMITED for kind in failure_kinds):
        return _structured_ai_error(ERROR_CODE_RATE_LIMITED, last_detail)
    if last_kind == ERROR_CODE_TIMEOUT:
        code = ERROR_CODE_TIMEOUT
    elif last_kind == ERROR_CODE_INVALID_RESPONSE:
        code = ERROR_CODE_INVALID_RESPONSE
    elif last_was_api_exception and attempts > 1:
        code = ERROR_CODE_RETRIES_EXHAUSTED
    elif last_kind in AI_ERROR_CODES:
        code = last_kind
    else:
        code = ERROR_CODE_UNAVAILABLE
    return _structured_ai_error(code, last_detail)


def _redact_secret(text: str, secret: str) -> str:
    """Remove an API key from text before it is logged or returned."""
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text


def _backoff_seconds(attempt: int, base_delay_sec: float) -> float:
    """Wait after a failed attempt. attempt is 1-based: 0.5s, 1s, 2s, ..."""
    base = max(0.0, float(base_delay_sec))
    return base * (2 ** max(0, attempt - 1))


def _exception_status_code(exc: BaseException) -> int | None:
    for attr in ("code", "status_code"):
        value = getattr(exc, attr, None)
        if isinstance(value, int):
            return value
    return None


def _is_rate_limited(exc: BaseException) -> bool:
    """True for HTTP 429, quota, or resource-exhausted responses."""
    if _exception_status_code(exc) == 429:
        return True
    name = type(exc).__name__.lower()
    if "resourceexhausted" in name or "toomanyrequests" in name:
        return True
    text = str(exc).lower()
    return any(marker in text for marker in _RATE_LIMIT_MARKERS)


def _models_for_call(model_name: str) -> tuple[str, ...]:
    """Preferred model first, then the fixed older models, with duplicates removed."""
    primary = (model_name or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    ordered = [primary]
    for name in _FALLBACK_MODELS:
        if name not in ordered:
            ordered.append(name)
    return tuple(ordered)


def _tries_on_one_model(max_attempts: int) -> int:
    """First call, plus at most one repeat. Never more than max_attempts."""
    requested = max(1, int(max_attempts))
    return min(requested, 1 + _SAME_MODEL_RETRIES)


def _log_model_fallback(failed_model: str, next_model: str, reason: str) -> None:
    """Record a model switch. The reason is an error code, never an API key."""
    logger.warning(
        "Gemini model %s failed (%s); trying %s",
        failed_model,
        reason,
        next_model,
    )


def _mark_gemini_success(ai_fields: dict[str, Any]) -> dict[str, Any]:
    """Attach the success marker Data/Flask can trust. Never used on failure."""
    marked = dict(ai_fields)
    marked["source"] = AI_SOURCE
    return marked


def _format_question(question: Mapping[str, Any]) -> str:
    """One question line: key, wording, and answer labels. No scores."""
    key = str(question.get("key", "")).strip()
    wording = str(question.get("prompt", "")).strip()
    options = question.get("options")
    positive = bool(question.get("reverse"))
    tone = " Positively worded: a high answer means less stress." if positive else ""
    if options:
        labels = ", ".join(
            f"{number} = {label}" for number, label in enumerate(options, start=1)
        )
        return f"- {key}: {wording}{tone} Answer labels: {labels}."
    minimum = question.get("min", 0)
    maximum = question.get("max", 14)
    step = question.get("step", 0.5)
    low = question.get("low", "0 hours")
    high = question.get("high", "14 hours")
    return (
        f"- {key}: {wording}{tone} "
        f"Answer: {minimum} to {maximum} hours in steps of {step} "
        f"({low} to {high}), not a 1 to 5 rating."
    )


def build_prompt(
    student_dict: dict[str, Any],
    questions: Sequence[Mapping[str, Any]] | None = None,
    instructions: str | None = None,
) -> str:
    """
    Ask Gemini to calculate stress_score from the raw check-in.

    The JSON body is only the 11 answers and survey_version. Question wording
    and answer-option labels are instructions, not scored fields.

    `instructions` is the scoring formula and tier rules, written by
    logic_manager.scoring_instructions() and passed in by main.py. This module
    does not know those rules itself.

    `questions` defaults to DEFAULT_QUESTIONS so this module does not import
    survey. Each item needs `key` and `prompt`. Likert items include `options`
    (the label for 1, then 2, and so on). Sleep hours omit `options` and use
    min, max, step, low, and high. `reverse=True` marks a positively worded
    item. Pass survey.QUESTIONS from the caller to take wording from there.
    """
    catalog = DEFAULT_QUESTIONS if questions is None else questions
    payload = {key: student_dict.get(key) for key in STUDENT_PROMPT_FIELDS}
    record_json = json.dumps(payload, ensure_ascii=False, indent=2)
    wording = "\n".join(_format_question(item) for item in catalog)
    stressor_list = ", ".join(sorted(ALLOWED_PRIMARY_STRESSORS))
    tip_id_list = ", ".join(sorted(ALLOWED_TIP_IDS))
    soft_label_list = ", ".join(f'"{label}"' for label in SOFT_LABELS)
    scoring_rules = instructions or ""

    return (
        "You are a supportive student-wellbeing assistant for DoNotStress, "
        "a local check-in used by students.\n"
        "Calculate stress_score from the 11 answers with the formula below. "
        "You are not given a score, a tier, or a written reflection. "
        "Do not diagnose, and do not invent contacts.\n"
        f"{scoring_rules}"
        f"Question wording and answer labels:\n{wording}\n"
        "Speak to the student with warmth. Return ONLY a single JSON object "
        "(no markdown fences, no commentary) with exactly these keys:\n"
        '- "scored_items": object of the 11 converted values. Keys are '
        "pss_1, pss_2, pss_3, pss_4, sleep_hours_avg, sleep_quality, "
        "pas_workload, pas_catchup, fin_stress, mspss_friends, mspss_family. "
        "Each value is an integer from 1 to 5.\n"
        f'- "stress_score": the mean above, from {STRESS_SCORE_MIN:g} to '
        f"{STRESS_SCORE_MAX:g}, rounded to 2 decimal places\n"
        '- "risk_category": "Low", "Moderate", or "High", matching stress_score\n'
        '- "primary_stressors": list of snake_case strings chosen ONLY from: '
        f"{stressor_list}\n"
        '- "confidence": number from 0.0 to 1.0\n'
        '- "reasoning": 2 or 3 warm, plain sentences written to the student. '
        "No numbers, no jargon, no diagnosis, and no contacts\n"
        f'- "soft_label": exactly one of {soft_label_list}, matching risk_category. '
        "Use a straight apostrophe in You're doing ok\n"
        '- "tips": list of 1 to 3 tip IDs only, each one of: '
        f"{tip_id_list}. Do not invent tip text\n"
        '- "speak_prominence": "low", "medium", or "high", matching risk_category. '
        "This is how strongly the UI highlights Talk to someone. "
        "SIT Counselling stays available and is shown more prominently when stress is higher\n"
        "Do not add other keys. Never invent phone numbers, emails, or offices. "
        "SIT Counselling contacts are shown by the UI, not by you.\n"
        "\n"
        "Student check-in:\n"
        f"{record_json}\n"
    )


def _as_unit_interval(value: Any, field_name: str) -> tuple[bool, Any]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False, f"{field_name} must be a float between 0.0 and 1.0."
    if isinstance(value, bool) or not math.isfinite(number) or number < 0.0 or number > 1.0:
        return False, f"{field_name} must be between 0.0 and 1.0."
    return True, number


def _as_stress_score(value: Any) -> tuple[bool, Any]:
    """Finite float on the 1.0–5.0 stress scale. Booleans are rejected."""
    if isinstance(value, bool):
        return False, "stress_score must be a float between 1.0 and 5.0."
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False, "stress_score must be a float between 1.0 and 5.0."
    if (
        not math.isfinite(number)
        or number < STRESS_SCORE_MIN
        or number > STRESS_SCORE_MAX
    ):
        return False, "stress_score must be a float between 1.0 and 5.0."
    return True, number


def _normalise_soft_label(value: Any) -> tuple[bool, Any]:
    if not isinstance(value, str):
        return False, "soft_label must be a string."
    label = value.strip()
    normalised = _SOFT_LABEL_ALIASES.get(label)
    if normalised is None:
        return (
            False,
            'soft_label must be "You\'re doing ok", "Worth a check-in", '
            'or "Please reach out".',
        )
    return True, normalised


def _normalise_stressors(value: Any) -> tuple[bool, Any]:
    if not isinstance(value, list):
        return False, "primary_stressors must be a list of allow-listed strings."
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in value:
        if not isinstance(item, str):
            return False, "primary_stressors must be a list of strings."
        name = item.strip()
        if name not in ALLOWED_PRIMARY_STRESSORS:
            return False, f"primary_stressor is not on the allow-list: {name}."
        if name not in seen:
            seen.add(name)
            cleaned.append(name)
    return True, cleaned


def _normalise_tips(value: Any) -> tuple[bool, Any]:
    if not isinstance(value, list):
        return False, "tips must be a list of 1–3 allow-listed tip IDs."
    if len(value) < _TIPS_MIN or len(value) > _TIPS_MAX:
        return False, "tips must contain between 1 and 3 allow-listed tip IDs."
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            return False, "each tip must be an allow-listed tip ID."
        tip_id = item.strip()
        if tip_id not in ALLOWED_TIP_IDS:
            return False, f"tip ID is not on the allow-list: {tip_id}"
        if tip_id not in seen:
            seen.add(tip_id)
            cleaned.append(tip_id)
    if not cleaned:
        return False, "tips must contain between 1 and 3 allow-listed tip IDs."
    return True, cleaned


def _normalise_scored_items(value: Any) -> tuple[bool, Any]:
    """Require an object of the 11 converted integers, each from 1 to 5."""
    if not isinstance(value, dict):
        return False, "scored_items must be an object of the 11 converted answers."
    if set(value) != set(RAW_ANSWER_KEYS):
        return False, "scored_items must contain exactly the 11 answer keys."
    cleaned: dict[str, int] = {}
    for key in RAW_ANSWER_KEYS:
        item = value[key]
        if isinstance(item, bool) or not isinstance(item, int) or item < 1 or item > 5:
            return False, f"scored_items.{key} must be an integer from 1 to 5."
        cleaned[key] = item
    return True, cleaned


def validate_ai_response(payload: Any) -> tuple[bool, Any]:
    """
    Validate Gemini JSON against the response schema and allow-lists.

    Checks required keys, types, ranges and allowed values only. Whether the
    numbers and tier are right for the answers is a domain rule, checked by
    the verify_fn the caller passes to call_gemini (logic_manager's).

    Returns (True, normalised_dict) or (False, error_message).
    Never raises for malformed payloads.
    """
    if isinstance(payload, str):
        text = payload.strip()
        if not text:
            return False, "Empty AI response string."
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as exc:
            return False, f"AI response is not valid JSON: {exc}"

    if not isinstance(payload, dict):
        return False, "AI response must be a JSON object."

    missing = [key for key in _REQUIRED_FIELDS if key not in payload]
    if missing:
        return False, f"AI response missing required fields: {', '.join(missing)}."

    score_ok, stress_score = _as_stress_score(payload["stress_score"])
    if not score_ok:
        return False, stress_score

    items_ok, scored_items = _normalise_scored_items(payload["scored_items"])
    if not items_ok:
        return False, scored_items

    risk_category = payload["risk_category"]
    if not isinstance(risk_category, str):
        return False, 'risk_category must be "Low", "Moderate", or "High".'
    risk_category = risk_category.strip()
    if risk_category not in ALLOWED_RISK_CATEGORIES:
        return False, 'risk_category must be "Low", "Moderate", or "High".'

    stressors_ok, stressors = _normalise_stressors(payload["primary_stressors"])
    if not stressors_ok:
        return False, stressors

    conf_ok, confidence = _as_unit_interval(payload["confidence"], "confidence")
    if not conf_ok:
        return False, confidence

    reasoning = payload["reasoning"]
    if not isinstance(reasoning, str) or not reasoning.strip():
        return False, "reasoning must be a non-empty string."

    label_ok, soft_label = _normalise_soft_label(payload["soft_label"])
    if not label_ok:
        return False, soft_label

    tips_ok, tips = _normalise_tips(payload["tips"])
    if not tips_ok:
        return False, tips

    speak_prominence = payload["speak_prominence"]
    if (
        not isinstance(speak_prominence, str)
        or speak_prominence.strip() not in ALLOWED_SPEAK_PROMINENCE
    ):
        return False, 'speak_prominence must be "low", "medium", or "high".'
    speak_prominence = speak_prominence.strip()

    normalised = {
        "scored_items": scored_items,
        "stress_score": stress_score,
        "risk_category": risk_category,
        "primary_stressors": stressors,
        "confidence": confidence,
        "reasoning": reasoning.strip(),
        "soft_label": soft_label,
        "tips": tips,
        "speak_prominence": speak_prominence,
    }
    return True, normalised


def parse_response(raw: Any) -> dict[str, Any] | None:
    """Extract and parse the JSON object in a raw AI reply.

    Tolerates code fences or text around the object. Returns the dict, or
    None for empty, non-string or malformed input. Never raises.
    """
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    start, end = raw.find("{"), raw.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def validate_response(data: Any) -> tuple[bool, Any]:
    """Check required keys, types and ranges. Thin wrapper around validate_ai_response.

    Returns (True, normalised_dict) or (False, error_message). Never raises.
    """
    return validate_ai_response(data)


def _run_check(
    verify_fn: Callable[[dict[str, Any], Mapping[str, Any]], str | None],
    ai_fields: dict[str, Any],
    answers: Mapping[str, Any],
) -> str | None:
    """Run the caller's domain check on a schema-valid reply. Never raises.

    Returns the problem as text, or None when the reply passes.
    """
    try:
        problem = verify_fn(ai_fields, answers)
    except Exception as exc:  # noqa: BLE001 — a broken check must not crash the pipeline
        return f"Score check could not run: {exc}"
    return str(problem) if problem else None


_RESPONSE_FIELDS = (
    "scored_items",
    "stress_score",
    "risk_category",
    "soft_label",
    "speak_prominence",
    "primary_stressors",
    "tips",
    "reasoning",
    "confidence",
)

# Gemini structured-output schema (SDK Schema dict: uppercase types, enums).
# risk_score is not included; this module computes it after validation.
RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "OBJECT",
    "propertyOrdering": list(_RESPONSE_FIELDS),
    "required": list(_RESPONSE_FIELDS),
        "properties": {
        "scored_items": {
            "type": "OBJECT",
            "description": "The 11 answers converted onto the 1-5 stress scale.",
            "propertyOrdering": list(RAW_ANSWER_KEYS),
            "required": list(RAW_ANSWER_KEYS),
            "properties": {
                key: {"type": "INTEGER", "minimum": 1, "maximum": 5}
                for key in RAW_ANSWER_KEYS
            },
        },
        "stress_score": {
            "type": "NUMBER",
            "minimum": STRESS_SCORE_MIN,
            "maximum": STRESS_SCORE_MAX,
            "description": (
                "Mean of the 11 converted values, rounded to 2 decimal places."
            ),
        },
        "risk_category": {
            "type": "STRING",
            "enum": ["Low", "Moderate", "High"],
            "description": "The tier for stress_score, following the rules in the prompt.",
        },
        "soft_label": {
            "type": "STRING",
            "enum": list(SOFT_LABELS),
            "description": "Must match risk_category.",
        },
        "speak_prominence": {
            "type": "STRING",
            "enum": list(SPEAK_PROMINENCE),
            "description": "Must match risk_category: low, medium, or high.",
        },
        "primary_stressors": {
            "type": "ARRAY",
            "items": {
                "type": "STRING",
                "enum": sorted(ALLOWED_PRIMARY_STRESSORS),
            },
        },
        "tips": {
            "type": "ARRAY",
            "minItems": _TIPS_MIN,
            "maxItems": _TIPS_MAX,
            "items": {
                "type": "STRING",
                "enum": sorted(ALLOWED_TIP_IDS),
            },
        },
        "reasoning": {
            "type": "STRING",
            "description": (
                "Two or three warm, plain sentences to the student. "
                "No numbers, jargon, diagnosis, or contacts."
            ),
        },
        "confidence": {
            "type": "NUMBER",
            "minimum": 0.0,
            "maximum": 1.0,
        },
    },
}


def _default_generate(prompt: str, api_key: str, model_name: str) -> str:
    """
    Real Gemini call (structured JSON). Isolated so tests can inject a stub.
    Reads the key from the caller; never hardcode GEMINI_API_KEY.

    Uses the current google.genai client. The SDK's own HTTP retries are
    turned off so this module's 429/timeout backoff stays at 3 attempts.
    """
    from google import genai

    timeout_ms = int(_DEFAULT_TIMEOUT_SEC * 1000)
    client = genai.Client(
        api_key=api_key,
        http_options={
            "timeout": timeout_ms,
            "retry_options": {"attempts": 1},
        },
    )
    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config={
            "temperature": _DEFAULT_TEMPERATURE,
            "response_mime_type": "application/json",
            "response_schema": RESPONSE_SCHEMA,
            "automatic_function_calling": {"disable": True},
        },
    )
    text = getattr(response, "text", None)
    if text is None:
        try:
            text = response.candidates[0].content.parts[0].text
        except (AttributeError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Gemini returned no text payload: {exc}") from exc
    return text


def call_gemini(
    prompt: str,
    *,
    api_key: str | None = None,
    model_name: str = _DEFAULT_MODEL,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    retry_delay_sec: float = _DEFAULT_RETRY_DELAY_SEC,
    generate_fn: Callable[[str, str, str], str] | None = None,
    answers: Mapping[str, Any] | None = None,
    verify_fn: Callable[[dict[str, Any], Mapping[str, Any]], str | None] | None = None,
) -> tuple[bool, dict[str, Any] | None, dict[str, str] | None]:
    """
    Call Gemini with structured JSON output, validate schema, then fall back.

    The call order is gemini-3.6-flash, then gemini-3.5-flash, then
    gemini-3.5-flash-lite. Any API failure moves to the next model.
    A missing API key stops immediately. HTTP 429 does not retry the same
    model. A timeout or bad JSON may be tried once more on that same model.
    The generator is called at most MAX_TOTAL_CALLS times.

    When both `verify_fn` and `answers` are given, each schema-valid reply is
    also passed to verify_fn(reply, answers). A returned message means the
    reply is wrong for these answers; it is handled like bad JSON (retried,
    then invalid_response). main.py passes logic_manager.verify_ai_scores.

    Returns (ok, validated_ai_dict_or_None, error_or_None).
    On failure, error is {"error_code", "detail", "source": "gemini"}.
    Never crashes the program on API / timeout / malformed JSON.
    Never invents soft_label / tips / speak_prominence on failure.
    Never logs the API key.
    """
    key = (api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")).strip()
    generator = generate_fn if generate_fn is not None else _default_generate

    # Env-only key. Do not attempt the real API when it is missing/blank.
    # generate_fn injection is for tests and still runs without a key.
    if generate_fn is None and not key:
        detail = "GEMINI_API_KEY is not set; cannot call Gemini."
        logger.error(detail)
        return False, None, _structured_ai_error(ERROR_CODE_MISSING_API_KEY, detail)

    last_detail = "Unknown AI failure."
    last_kind = ERROR_CODE_UNAVAILABLE
    last_was_api_exception = False
    tries_allowed = _tries_on_one_model(max_attempts)
    models = _models_for_call(model_name)
    calls_made = 0
    finished_attempt = 1
    failure_kinds: list[str] = []

    for model_index, active_model in enumerate(models):
        tries_here = 0
        move_on = False
        while tries_here < tries_allowed and calls_made < MAX_TOTAL_CALLS:
            calls_made += 1
            tries_here += 1
            finished_attempt = tries_here
            try:
                raw_text = generator(prompt, key, active_model)
            except Exception as exc:  # noqa: BLE001 — must not crash pipeline
                last_was_api_exception = True
                last_kind = classify_ai_error(exc)
                failure_kinds.append(last_kind)
                safe_exc = _redact_secret(str(exc), key)
                last_detail = (
                    f"Gemini API failure (attempt {tries_here}/{tries_allowed}) "
                    f"model={active_model}: {safe_exc}"
                )
                logger.warning(last_detail)
                if last_kind == ERROR_CODE_MISSING_API_KEY:
                    return False, None, _structured_ai_error(
                        ERROR_CODE_MISSING_API_KEY, last_detail
                    )
                # 429 and every other API error leave this model. A timeout
                # may use the one same-model retry.
                repeat = (
                    last_kind == ERROR_CODE_TIMEOUT
                    and not _is_rate_limited(exc)
                    and tries_here < tries_allowed
                    and calls_made < MAX_TOTAL_CALLS
                )
                if repeat:
                    time.sleep(_backoff_seconds(tries_here, retry_delay_sec))
                    continue
                move_on = True
                break

            ok, result = validate_ai_response(raw_text)
            if ok and verify_fn is not None and answers is not None:
                problem = _run_check(verify_fn, result, answers)
                if problem:
                    ok, result = False, problem
            if ok:
                return True, _mark_gemini_success(result), None

            last_was_api_exception = False
            last_kind = ERROR_CODE_INVALID_RESPONSE
            failure_kinds.append(last_kind)
            last_detail = (
                f"Schema validation failed (attempt {tries_here}/{tries_allowed}) "
                f"model={active_model}: {result}"
            )
            logger.warning(last_detail)
            if tries_here < tries_allowed and calls_made < MAX_TOTAL_CALLS:
                time.sleep(_backoff_seconds(tries_here, retry_delay_sec))
                continue
            move_on = True
            break

        if not move_on or calls_made >= MAX_TOTAL_CALLS or model_index >= len(models) - 1:
            break
        _log_model_fallback(active_model, models[model_index + 1], last_kind)

    return False, None, _final_ai_error(
        last_kind,
        last_detail,
        attempts=finished_attempt,
        last_was_api_exception=last_was_api_exception,
        failure_kinds=failure_kinds,
    )


def call_api(
    prompt: str,
    *,
    generate_fn: Callable[[str, str, str], str] | None = None,
    answers: Mapping[str, Any] | None = None,
    verify_fn: Callable[[dict[str, Any], Mapping[str, Any]], str | None] | None = None,
) -> tuple[bool, dict[str, Any] | None, dict[str, str] | None]:
    """Send a prompt to the AI. Thin wrapper around call_gemini.

    Connection errors and timeouts are caught and logged inside call_gemini;
    this never raises. Returns (ok, validated_fields_or_None, error_or_None).
    """
    return call_gemini(prompt, generate_fn=generate_fn, answers=answers, verify_fn=verify_fn)


def analyse_student(
    student_dict: dict[str, Any],
    *,
    api_key: str | None = None,
    model_name: str = _DEFAULT_MODEL,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    retry_delay_sec: float = _DEFAULT_RETRY_DELAY_SEC,
    generate_fn: Callable[[str, str, str], str] | None = None,
    questions: Sequence[Mapping[str, Any]] | None = None,
    instructions: str | None = None,
    verify_fn: Callable[[dict[str, Any], Mapping[str, Any]], str | None] | None = None,
) -> tuple[bool, dict[str, Any] | None, dict[str, str] | None]:
    """
    Entry point for the AI Processing Layer.

    Builds prompt → calls Gemini → validates schema → merges AI fields into
    a shallow copy of the student record. Every successful record is marked
    source="gemini" so Data/Flask can trust Gemini processing.

    `questions` is forwarded to build_prompt. Leave it unset to use the
    built-in wording catalog. `instructions` (the scoring rules for the
    prompt) and `verify_fn` (the check on each reply) come from
    logic_manager via main.py; the raw answers are passed to verify_fn.

    Returns (ok, enriched_record_or_None, error_or_None). Never raises for
    API / schema failures. On failure the record is None (no invented
    soft_label / tips / speak_prominence).
    """
    if not isinstance(student_dict, dict):
        return False, None, _structured_ai_error(
            ERROR_CODE_INVALID_RESPONSE,
            "student_dict must be a dict from io_manager.",
        )

    prompt = build_prompt(student_dict, questions, instructions)
    ok, ai_fields, err = call_gemini(
        prompt,
        api_key=api_key,
        model_name=model_name,
        max_attempts=max_attempts,
        retry_delay_sec=retry_delay_sec,
        generate_fn=generate_fn,
        answers=student_dict,
        verify_fn=verify_fn,
    )
    if not ok or ai_fields is None:
        return False, None, err

    enriched = dict(student_dict)
    enriched.update(ai_fields)
    enriched["source"] = AI_SOURCE
    return True, enriched, None