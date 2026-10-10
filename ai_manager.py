"""
DoNotStress — AI Processing Layer (ai_manager)

Sole owner of Gemini prompt construction, structured JSON API calls,
schema validation, and graceful retries.

Audience: students (local Flask web UI), not advisors.
Gemini is MANDATORY: every record must pass through analyse_student /
call_gemini. This layer never invents soft_label / tips / speak_prominence
as a substitute product, and never falls back to logic_manager.

Pure procedural Python: functions only.
No terminal I/O (print / input), no Intervention Tier rules, no file persistence.

Pipeline position:
  User → io_manager → ai_manager (required) → data_manager
  On failure: structured error for io_manager.format_ai_error (no Logic substitute)
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import time
from typing import Any, Callable

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Plain item labels for 1-5 answers sent to Gemini (student check-in only)
# ---------------------------------------------------------------------------

PLAIN_ITEM_LABELS = {
    "pss_1": "Feeling unable to control important things in life",
    "pss_2": "Difficulty handling personal problems",
    "pss_3": "Feeling that things are not going your way",
    "pss_4": "Difficulties piling up so high they cannot be overcome",
    "sleep_hours_avg": "Typical nightly sleep hours",
    "sleep_quality": "Sleep quality rating",
    "pas_workload": "Academic workload pressure",
    "pas_catchup": "Difficulty catching up with studies",
    "fin_stress": "Personal finances stress",
    "mspss_friends": "Perceived support from friends",
    "mspss_family": "Perceived support from family",
    "mspss_so": "Perceived support from a special person",
}

# ---------------------------------------------------------------------------
# Shared allow-lists — MUST match io_manager exactly.
# Tip *copy* lives in io_manager.format_tips — this layer returns IDs only.
# ---------------------------------------------------------------------------

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
        "feelings_check_in",
    }
)

_REQUIRED_FIELDS = (
    "perceived_stress_score",
    "explanation",
    "tips",
)

MODEL_FALLBACK_CHAIN = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
)

_DEFAULT_MODEL = MODEL_FALLBACK_CHAIN[0]
_DEFAULT_TIMEOUT_SEC = 30.0
_DEFAULT_MAX_ATTEMPTS = 1
_DEFAULT_RETRY_DELAY_SEC = 0.0
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
ERROR_CODE_UNAVAILABLE = "unavailable"
ERROR_CODE_QUOTA_EXHAUSTED = "quota_exhausted"

AI_ERROR_CODES = (
    ERROR_CODE_MISSING_API_KEY,
    ERROR_CODE_TIMEOUT,
    ERROR_CODE_INVALID_RESPONSE,
    ERROR_CODE_RETRIES_EXHAUSTED,
    ERROR_CODE_UNAVAILABLE,
    ERROR_CODE_QUOTA_EXHAUSTED,
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
) -> dict[str, str]:
    """
    Choose the structured code after the retry loop ends.

    - timeout / DeadlineExceeded stay timeout (even after retries)
    - schema / malformed JSON stay invalid_response
    - other API exceptions after more than one attempt → retries_exhausted
    - other one-shot API / network failures → unavailable
    """
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
    """True for HTTP 429 / resource-exhausted responses."""
    if _exception_status_code(exc) == 429:
        return True
    name = type(exc).__name__.lower()
    if "resourceexhausted" in name or "toomanyrequests" in name:
        return True
    text = str(exc).lower()
    return (
        "429" in text
        or "resource exhausted" in text
        or "too many requests" in text
        or "rate limit" in text
    )


def _is_retryable_api_error(exc: BaseException) -> bool:
    """Retry timeouts and 429s only. Other API errors fail on the first try."""
    if classify_ai_error(exc) == ERROR_CODE_TIMEOUT:
        return True
    return _is_rate_limited(exc)


def _is_model_overloaded(exc: BaseException) -> bool:
    """True when Gemini accepted the key but the model returned HTTP 503."""
    if _exception_status_code(exc) == 503:
        return True
    text = str(exc).lower()
    return "503" in text and ("unavailable" in text or "high demand" in text)


def _models_for_call(model_name: str) -> tuple[str, ...]:
    """Preferred model first, then overload fallbacks, with duplicates removed."""
    primary = (model_name or _DEFAULT_MODEL).strip() or _DEFAULT_MODEL
    ordered = [primary]
    for name in _FALLBACK_MODELS:
        if name not in ordered:
            ordered.append(name)
    return tuple(ordered)


def require_gemini_api_key() -> str:
    """
    Stop startup when GEMINI_API_KEY is missing or blank.

    The key is read from the environment only. SystemExit carries a clear
    message and never includes the key.
    """
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "GEMINI_API_KEY is not set. Set it in the environment and start the app again."
        )
    return key


def _mark_gemini_success(ai_fields: dict[str, Any]) -> dict[str, Any]:
    """Attach the success marker Data/Flask can trust. Never used on failure."""
    marked = dict(ai_fields)
    marked["source"] = AI_SOURCE
    return marked


def build_prompt(student_dict: dict[str, Any]) -> str:
    """
    Build a structured prompt from validated 1-5 student check-in answers.

    Uses plain item labels for the 1-5 answers (already reverse-scored).
    Never includes student_id, reflection text, or the reference score.
    Instructs Gemini to return ONLY the required JSON with perceived_stress_score,
    explanation, and tips.
    """
    items_lines = []
    for key, label in PLAIN_ITEM_LABELS.items():
        if key in student_dict and student_dict[key] is not None:
            items_lines.append(f"- {label}: {student_dict[key]}")
    items_text = "\n".join(items_lines)
    tip_id_list = ", ".join(sorted(ALLOWED_TIP_IDS))

    return (
        "You are a supportive student-wellbeing assistant for DoNotStress, "
        "a check-in tool used by university students.\n"
        "Here are the student's ratings (standardised 1.0–5.0 scale, where higher "
        "indicates more stress or challenges; positively worded items have already "
        "been reverse-scored):\n"
        f"{items_text}\n\n"
        "Please analyse these ratings holistically and return ONLY a single JSON "
        "object (no markdown fences, no extra commentary) with exactly these keys:\n"
        '- "perceived_stress_score": float between 1.0 and 5.0 reflecting overall '
        "perceived stress level (1.0 = lowest stress, 5.0 = highest stress).\n"
        '- "explanation": 2 to 3 warm, supportive sentences addressed directly to "you". '
        "Strict rules for the explanation:\n"
        "  * Must be addressed to 'you'.\n"
        "  * Must NOT contain any numbers or digits.\n"
        '  * Must NOT contain the words "AI", "Gemini", "PSS", "score", or "scores".\n'
        "  * Must NOT contain any medical or clinical diagnoses or diagnostic terms.\n"
        "  * Must be under 400 characters.\n"
        '- "tips": list of 1 to 3 tip IDs chosen ONLY from this allow-list: '
        f"[{tip_id_list}]. Do not invent new IDs.\n"
    )


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


def validate_ai_response(payload: Any) -> tuple[bool, Any]:
    """
    Validate Gemini JSON against the new schema:
      - perceived_stress_score (float 1.0-5.0)
      - explanation (str <= 400 chars, no numbers, no AI/Gemini/PSS/score/diagnoses)
      - tips (list of 1-3 allow-listed tip IDs)

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

    # Validate perceived_stress_score
    try:
        raw_score = payload["perceived_stress_score"]
        if isinstance(raw_score, bool):
            return False, "perceived_stress_score must be a float between 1.0 and 5.0."
        score = float(raw_score)
        if not math.isfinite(score) or score < 1.0 or score > 5.0:
            return False, "perceived_stress_score must be between 1.0 and 5.0."
    except (TypeError, ValueError):
        return False, "perceived_stress_score must be a numeric float."

    # Validate explanation
    explanation = payload.get("explanation")
    if not isinstance(explanation, str) or not explanation.strip():
        return False, "explanation must be a non-empty string."
    explanation = explanation.strip()
    if len(explanation) > 400:
        return False, "explanation exceeds maximum length of 400 characters."
    if any(c.isdigit() for c in explanation):
        return False, "explanation must not contain numbers."

    lower_exp = explanation.lower()
    if "gemini" in lower_exp:
        return False, "explanation must not contain 'Gemini'."
    if re.search(r"\bai\b", lower_exp):
        return False, "explanation must not contain 'AI'."
    if re.search(r"\bpss\b", lower_exp):
        return False, "explanation must not contain 'PSS'."
    if re.search(r"\bscores?\b", lower_exp):
        return False, "explanation must not contain 'score'."
    if re.search(r"\bdiagnos", lower_exp):
        return False, "explanation must not contain clinical diagnoses."

    # Validate tips
    tips_ok, tips = _normalise_tips(payload["tips"])
    if not tips_ok:
        return False, tips

    normalised = {
        "perceived_stress_score": round(score, 2),
        "explanation": explanation,
        "tips": tips,
    }
    return True, normalised


def _default_generate(prompt: str, api_key: str, model_name: str) -> str:
    """
    Real Gemini call (structured JSON). Isolated so tests can inject a stub.
    Uses the current google.genai client without temperature setting.
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
            "response_mime_type": "application/json",
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
    generate_fn: Callable[[str, str, str], str] | None = None,
    **kwargs: Any,
) -> tuple[bool, dict[str, Any] | None, dict[str, str] | None]:
    """
    Call Gemini models in fallback order (one attempt per model).

    MODEL_FALLBACK_CHAIN: gemini-3.6-flash -> gemini-3.5-flash -> gemini-3.5-flash-lite.
    - If 401/403 or missing key: fails immediately with missing_api_key.
    - If 429/quota, 503, timeout, or invalid response: moves to next model in chain.
    - Exactly one attempt per model (no retries loop on same model).
    - Stores ai_model on success.
    """
    key = (api_key if api_key is not None else os.environ.get("GEMINI_API_KEY", "")).strip()
    generator = generate_fn if generate_fn is not None else _default_generate

    if generate_fn is None and not key:
        detail = "GEMINI_API_KEY is not set; cannot call Gemini."
        logger.error(detail)
        return False, None, _structured_ai_error(ERROR_CODE_MISSING_API_KEY, detail)

    last_detail = "All fallback models unavailable."
    last_kind = ERROR_CODE_UNAVAILABLE
    saw_quota = False

    for model_name in MODEL_FALLBACK_CHAIN:
        logger.info("Attempting AI call with model: %s", model_name)
        try:
            raw_text = generator(prompt, key, model_name)
        except Exception as exc:  # noqa: BLE001
            kind = classify_ai_error(exc)
            safe_exc = _redact_secret(str(exc), key)
            last_detail = f"Gemini API failure model={model_name}: {safe_exc}"
            logger.warning(last_detail)

            # 401 / 403 fails immediately across all models
            if kind == ERROR_CODE_MISSING_API_KEY or "401" in str(exc) or "403" in str(exc) or "unauthenticated" in str(exc).lower():
                return False, None, _structured_ai_error(ERROR_CODE_MISSING_API_KEY, last_detail)

            if "429" in str(exc) or "resource_exhausted" in str(exc).lower() or "quota" in str(exc).lower():
                saw_quota = True

            last_kind = kind
            continue

        ok, result = validate_ai_response(raw_text)
        if ok:
            result["ai_model"] = model_name
            logger.info("Model %s answered successfully", model_name)
            return True, _mark_gemini_success(result), None

        last_kind = ERROR_CODE_INVALID_RESPONSE
        last_detail = f"Schema validation failed model={model_name}: {result}"
        logger.warning(last_detail)
        continue

    final_code = ERROR_CODE_QUOTA_EXHAUSTED if saw_quota else last_kind
    return False, None, _structured_ai_error(final_code, last_detail)


def analyse_student(
    student_dict: dict[str, Any],
    *,
    api_key: str | None = None,
    model_name: str = _DEFAULT_MODEL,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    retry_delay_sec: float = _DEFAULT_RETRY_DELAY_SEC,
    generate_fn: Callable[[str, str, str], str] | None = None,
) -> tuple[bool, dict[str, Any] | None, dict[str, str] | None]:
    """
    Entry point for the AI Processing Layer.

    Builds prompt → calls Gemini → validates schema → merges AI fields into
    a shallow copy of the student record. Every successful record is marked
    source="gemini" so Data/Flask can trust Gemini processing.

    Returns (ok, enriched_record_or_None, error_or_None). Never raises for
    API / schema failures. On failure the record is None (no invented
    soft_label / tips / speak_prominence).
    """
    if not isinstance(student_dict, dict):
        return False, None, _structured_ai_error(
            ERROR_CODE_INVALID_RESPONSE,
            "student_dict must be a dict from io_manager.",
        )

    prompt = build_prompt(student_dict)
    ok, ai_fields, err = call_gemini(
        prompt,
        api_key=api_key,
        model_name=model_name,
        max_attempts=max_attempts,
        retry_delay_sec=retry_delay_sec,
        generate_fn=generate_fn,
    )
    if not ok or ai_fields is None:
        return False, None, err

    enriched = dict(student_dict)
    enriched.update(ai_fields)
    enriched["source"] = AI_SOURCE
    return True, enriched, None