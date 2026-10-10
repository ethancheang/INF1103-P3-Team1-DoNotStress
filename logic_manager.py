"""
DoNotStress — Logic Layer (logic_manager)

Post-AI finalizer. Standardised on 1.0-5.0 scoring.
Reference score = average of PSS-4 items (1.0-5.0).
Tiers:
  - below 2.5: "You're doing ok"
  - 2.5 to 3.5: "Worth a check-in"
  - above 3.5: "Please reach out"

Cross-checks AI score against reference score with SCORE_TOLERANCE = 0.5.
If within tolerance, uses AI score; otherwise uses reference score and logs mismatch.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
import math
import os
from pathlib import Path
import re
from typing import Any

try:
    import data_manager
except ImportError:
    data_manager = None  # type: ignore[assignment]

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Scoring Constants & Tier Bands (1.0 - 5.0)
# ---------------------------------------------------------------------------

TIER_CHECK_IN_FROM: float = 2.5
TIER_REACH_OUT_ABOVE: float = 3.5
SCORE_TOLERANCE: float = 0.5

TIER_OK: str = "You're doing ok"
TIER_CHECK_IN: str = "Worth a check-in"
TIER_REACH_OUT: str = "Please reach out"
TIER_OK_CURLY: str = "You’re doing ok"

SOFT_LABEL_OK: str = TIER_OK
SOFT_LABEL_CHECK_IN: str = TIER_CHECK_IN
SOFT_LABEL_REACH_OUT: str = TIER_REACH_OUT

SOFT_LABELS = (
    SOFT_LABEL_OK,
    SOFT_LABEL_CHECK_IN,
    SOFT_LABEL_REACH_OUT,
)
ALLOWED_SOFT_LABELS = frozenset(SOFT_LABELS)

_TIER_TO_PROMINENCE = {
    SOFT_LABEL_OK: "low",
    SOFT_LABEL_CHECK_IN: "medium",
    SOFT_LABEL_REACH_OUT: "high",
}
_TIER_TO_CATEGORY = {
    SOFT_LABEL_OK: "Low",
    SOFT_LABEL_CHECK_IN: "Moderate",
    SOFT_LABEL_REACH_OUT: "High",
}

SPEAK_PROMINENCE = ("low", "medium", "high")
ALLOWED_SPEAK_PROMINENCE = frozenset(SPEAK_PROMINENCE)

RISK_CATEGORIES = ("Low", "Moderate", "High")
ALLOWED_RISK_CATEGORIES = frozenset(RISK_CATEGORIES)

# Tip IDs only — same keys as io_manager.TIPS_ALLOWLIST.
TIPS_ALLOWLIST = {
    "sleep_routine": "Try to keep a regular sleep schedule, including on weekends.",
    "rest_a_little_more": "If you can, give yourself a bit more rest — even 30 extra minutes can help.",
    "short_breaks": "Take short, planned breaks between study blocks instead of pushing through without a pause.",
    "workload_chunks": "Break larger assignments into smaller tasks and spread them across the week.",
    "money_worries": "If money is on your mind, campus support can help you find the right next step.",
    "talk_to_someone": "Reach out to a friend, classmate, or family member — you do not have to handle this alone.",
    "keep_social_contact": "Stay in touch with people who help you feel supported, even with a short check-in.",
    "feelings_check_in": "Name how you have been feeling and give yourself permission to ask for help if school feels heavy.",
}
ALLOWED_TIP_IDS = frozenset(TIPS_ALLOWLIST)

ALLOWED_PRIMARY_STRESSORS = frozenset(
    {
        "sleep_deprivation",
        "high_stress",
        "academic_overload",
        "financial_pressure",
        "low_social_support",
        "emotional_distress",
    }
)

REQUIRED_STUDENT_FIELDS = ("pss_1", "pss_2", "pss_3", "pss_4")
REQUIRED_AI_FIELDS = (
    "perceived_stress_score",
    "explanation",
    "tips",
)

LOGIC_SOURCE = "ai_logic"
ERROR_AI_FIELDS_REQUIRED = "ai_fields_required"
_MAX_TIPS = 4

# Crisis / self-harm phrases
_CRISIS_PATTERNS = tuple(re.compile(p) for p in (
    r"\bsuicid",
    r"\bkill(?:ing)? my ?self\b(?!-)",
    r"\bend(?:ing)? (?:my life|it all)\b",
    r"\btake my (?:own )?life\b",
    r"\bself[- ]?harm",
    r"\b(?:hurt(?:ing)?|harm(?:ing)?|cut(?:ting)?) my ?self\b(?!-| some slack)",
    r"\b(?:(?:want|going) to|wanna) die\b",
    r"\bbetter off dead\b",
    r"\b(?:don't|do not|dont) want to (?:live|be alive|be here|exist)\b",
    r"\bno (?:reason|point) (?:to|in) (?:live|living|go on|going on)\b",
    r"\b(?:life is )?not worth living\b",
))

SLEEP_LABELS = ["Very good", "Fairly good", "Fairly bad", "Very bad"]
PAS_LABELS = ["Strongly disagree", "Disagree", "Neither agree nor disagree", "Agree", "Strongly agree"]


# ---------------------------------------------------------------------------
# Scoring and Tier Assignment Functions
# ---------------------------------------------------------------------------

def compute_reference_score(answers: dict[str, Any]) -> float:
    """
    Compute reference score = average of the 4 PSS items (1.0-5.0).
    Answers are expected to be on the 1-5 scale with items 2 and 3 already reverse-scored.
    """
    pss_keys = ("pss_1", "pss_2", "pss_3", "pss_4")
    vals = [float(answers[k]) for k in pss_keys]
    return sum(vals) / len(vals)


def assign_tier(score: float) -> str:
    """
    Assign tier based on stress score (1.0-5.0):
      - below 2.5: "You're doing ok"
      - 2.5 to 3.5: "Worth a check-in"
      - above 3.5: "Please reach out"
    """
    s = float(score)
    if s > TIER_REACH_OUT_ABOVE:
        return TIER_REACH_OUT
    if s >= TIER_CHECK_IN_FROM:
        return TIER_CHECK_IN
    return TIER_OK


def cross_check_score(ai_score: float, reference: float) -> tuple[float, bool]:
    """
    Cross-check AI score against reference score with SCORE_TOLERANCE = 0.5.
    If |ai - reference| <= 0.5:
        use AI score, score_mismatch is False
    Otherwise:
        use reference score, log the mismatch, score_mismatch is True
    Returns (chosen_score, score_mismatch).
    """
    ai = float(ai_score)
    ref = float(reference)
    diff = abs(ai - ref)
    if diff <= SCORE_TOLERANCE:
        return (ai, False)
    logger.warning(
        "Score mismatch: AI score %.2f differs from reference score %.2f by %.2f (> %.2f)",
        ai, ref, diff, SCORE_TOLERANCE,
    )
    return (ref, True)


def compute_context_flags(record: dict[str, Any]) -> tuple[dict[str, bool], float | None, int]:
    """
    Compute context flags for sleep, workload, finances, and support.
    Context flags DO NOT raise the tier, but guide suggested tips and factors.
    """
    support_vals = [
        float(record[k])
        for k in ("mspss_friends", "mspss_family", "mspss_so")
        if record.get(k) is not None
    ]
    support_mean = (sum(support_vals) / len(support_vals)) if support_vals else None

    sleep_h = _safe_float(record.get("sleep_hours_avg") if record.get("sleep_hours_avg") is not None else record.get("sleep_hours"))
    sleep_q = _safe_float(record.get("sleep_quality"))
    sleep_flag = False
    if sleep_h is not None and sleep_h < 6.0:
        sleep_flag = True
    if sleep_q is not None and sleep_q >= 2.0:
        sleep_flag = True

    pas_w = _safe_float(record.get("pas_workload") if record.get("pas_workload") is not None else record.get("academic_workload"))
    workload_flag = pas_w is not None and pas_w >= 4.0

    fin_s = _safe_float(record.get("fin_stress") if record.get("fin_stress") is not None else record.get("financial_stress"))
    fin_flag = fin_s is not None and fin_s <= 4.0

    support_flag = support_mean is not None and support_mean < 3.0

    flags = {
        "sleep": sleep_flag,
        "workload": workload_flag,
        "finances": fin_flag,
        "support": support_flag,
    }
    return flags, support_mean, len(support_vals)


def build_factor_insights(
    record: dict[str, Any],
    flags: dict[str, bool],
    support_mean: float | None,
    support_count: int,
) -> list[dict[str, Any]]:
    sleep_h = record.get("sleep_hours_avg", record.get("sleep_hours", 0)) or 0
    sleep_q = int(record.get("sleep_quality", 0) or 0)
    sleep_label = SLEEP_LABELS[sleep_q] if 0 <= sleep_q < len(SLEEP_LABELS) else ""

    pas_w = int(record.get("pas_workload", record.get("academic_workload", 1)) or 1)
    pas_label = PAS_LABELS[pas_w - 1] if 1 <= pas_w <= len(PAS_LABELS) else ""

    sup_str = (
        f"{support_mean:g}/7 across {support_count} answers"
        if support_mean is not None
        else "Not answered"
    )

    return [
        dict(
            title="Rest & recovery",
            flagged=flags.get("sleep", False),
            value=f"{sleep_h:g} hours · {sleep_label}" if sleep_label else f"{sleep_h:g} hours",
            text="Short or unsatisfying sleep can make daily demands harder to manage. Stress may also disrupt sleep. The project flags under 6 hours or fairly/very bad quality.",
        ),
        dict(
            title="Study demands",
            flagged=flags.get("workload", False),
            value=f"{pas_w}/5 · {pas_label}" if pas_label else f"{pas_w}/5",
            text="Feeling overloaded may leave less room for rest. Agreeing that assignments are too much raises a workload flag. The optional catch-up answer adds context, not another flag.",
        ),
        dict(
            title="Money pressures",
            flagged=flags.get("finances", False),
            value=f"{record.get('fin_stress', record.get('financial_stress', 0))}/10 · 1 means more distress, 10 means less",
            text="Money worries may add to study pressures. Responses of 1–4 raise a financial flag and guide money-support suggestions; no amounts or income are inferred.",
        ),
        dict(
            title="Support & connection",
            flagged=flags.get("support", False),
            value=sup_str,
            text="Available support may help you cope with pressures. A mean below 3 raises a support flag. This selected-item average is an indicator, not a validated MSPSS short-form score.",
        ),
    ]


def _has_crisis_language(text: Any) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    normalized = text.lower().replace("’", "'").replace("‘", "'")
    normalized = " ".join(normalized.split())
    return any(pattern.search(normalized) for pattern in _CRISIS_PATTERNS)


def _safe_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


# ---------------------------------------------------------------------------
# Public API & LLM Unavailable Handling
# ---------------------------------------------------------------------------

def extract_error_reason(error: Any) -> str:
    """
    Extract a concise, non-technical, human-readable reason from an AI error
    or status code so students understand why they are encountering the error
    without being shown raw technical exception dumps.
    """
    if error is None:
        return "unable to communicate to ai server"

    code_str = ""
    if isinstance(error, int):
        code_str = str(error)
    elif isinstance(error, str) and error.strip().isdigit():
        code_str = error.strip()
    elif isinstance(error, dict):
        for key in ("code", "status_code", "error_code", "status"):
            val = error.get(key)
            if isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
                code_str = str(val)
                break
        if not code_str and isinstance(error.get("error"), dict):
            for key in ("code", "status_code", "status"):
                val = error["error"].get(key)
                if isinstance(val, int) or (isinstance(val, str) and val.isdigit()):
                    code_str = str(val)
                    break

    if code_str == "401":
        return "login error"
    if code_str == "503":
        return "unable to communicate to ai server"
    if code_str == "429":
        return "ai service busy"
    if code_str in ("408", "504"):
        return "request timeout"
    if code_str == "403":
        return "access denied"
    if code_str == "404":
        return "ai service not found"
    if code_str in ("500", "502"):
        return "unable to communicate to ai server"

    raw_text = ""
    if isinstance(error, str):
        raw_text = error
    elif isinstance(error, dict):
        raw_text = " ".join(
            str(v)
            for v in (
                error.get("error_code"),
                error.get("detail"),
                error.get("reason"),
                error.get("message"),
                error.get("status"),
                error.get("error"),
            )
            if v
        )
    elif isinstance(error, BaseException):
        raw_text = f"{type(error).__name__} {error}"
    else:
        raw_text = str(error)

    lowered = raw_text.lower()

    if any(m in lowered for m in (
        "401", "unauthenticated", "unauthorized", "login error",
        "invalid authentication", "access_token_type_unsupported",
        "invalid credential", "authentication credential", "oauth 2"
    )):
        return "login error"

    if any(m in lowered for m in (
        "missing_api_key", "api_key is not set", "api key is not set",
        "gemini_api_key is not set", "missing gemini api key", "missing api key"
    )):
        return "missing API key"

    if any(m in lowered for m in (
        "429", "quota", "resource_exhausted", "rate limit",
        "too many requests", "high demand", "spikes in demand", "busy"
    )):
        return "ai service busy"

    if any(m in lowered for m in (
        "408", "timeout", "timed out", "timed_out", "deadline", "deadlineexceeded"
    )):
        return "request timeout"

    if any(m in lowered for m in ("403", "forbidden", "permission_denied", "permission denied")):
        return "access denied"

    if any(m in lowered for m in ("404", "not found", "not_found")):
        return "ai service not found"

    if any(m in lowered for m in ("schema validation", "invalid_response", "invalid ai response", "malformed", "jsondecode")):
        return "invalid AI response"

    if any(m in lowered for m in ("503", "unavailable", "retries_exhausted", "connection", "service unavailable", "failed to connect")):
        return "unable to communicate to ai server"

    return "unable to communicate to ai server"


def format_error_prompt(reason: Any = "unable to communicate to ai server") -> str:
    """Format user-facing prompt when LLM is unavailable."""
    clean_reason = extract_error_reason(reason)
    return f"unexpected error due to {clean_reason}"


def display_error_prompt(reason: Any = "unable to communicate to ai server") -> str:
    """Display error prompt to console/terminal and return string."""
    prompt = format_error_prompt(reason)
    print(prompt)
    return prompt


def _resolve_data_path(data_path: str | Path | None = None) -> Path:
    if data_path is not None and str(data_path).strip():
        return Path(data_path)
    env_path = os.environ.get("DONOTSTRESS_DATA_PATH")
    if env_path and env_path.strip():
        return Path(env_path)
    if data_manager is not None and hasattr(data_manager, "get_default_data_path"):
        try:
            return Path(data_manager.get_default_data_path())
        except Exception:
            pass
    return Path(__file__).resolve().parent / "data" / "student_records.json"


def _read_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        data = json.loads(raw)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict) and isinstance(data.get("records"), list):
            return [item for item in data["records"] if isinstance(item, dict)]
    except Exception:
        return []
    return []


def _write_records(path: Path, records: list[dict[str, Any]]) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(records, indent=2, ensure_ascii=False) + "\n"
        path.write_text(text, encoding="utf-8")
        return True
    except Exception:
        return False


def save_record_locally(
    record: dict[str, Any],
    reason: Any = "unable to communicate to ai server",
    data_path: str | Path | None = None,
) -> dict[str, Any]:
    clean_reason = extract_error_reason(reason)
    path = _resolve_data_path(data_path)

    stored = dict(record) if isinstance(record, dict) else {}
    stored.pop("feelings_text", None)

    stored["ai_ok"] = False
    stored["ok"] = False
    stored["saved_locally"] = True
    stored["save_opt_in"] = True
    stored["source"] = "logic_fallback"
    stored["error"] = clean_reason
    stored["error_code"] = clean_reason

    if not stored.get("saved_at"):
        stored["saved_at"] = datetime.now(timezone.utc).isoformat()

    records = _read_records(path)
    records.append(stored)
    success = _write_records(path, records)

    return {
        "ok": success,
        "saved": success,
        "path": str(path),
        "record": stored,
        "error": clean_reason,
    }


def save_checkin_locally(
    record: dict[str, Any],
    reason: Any = "unable to communicate to ai server",
    data_path: str | Path | None = None,
) -> dict[str, Any]:
    return save_record_locally(record, reason=reason, data_path=data_path)


auto_save_record = save_record_locally
auto_save = save_record_locally
handle_llm_unavailable = save_record_locally
save_when_llm_unavailable = save_record_locally


# ---------------------------------------------------------------------------
# Core Finalizer: apply_logic
# ---------------------------------------------------------------------------

def apply_logic(
    record: dict[str, Any],
    *,
    reason: Any = None,
    ai_error: Any = None,
    data_path: str | Path | None = None,
    auto_save_on_unavailable: bool = False,
) -> dict[str, Any]:
    """
    Finalize an AI-enriched student record with 1.0-5.0 standardised scoring.

    Input MUST be a dict that already contains Gemini's fields:
      perceived_stress_score (float 1.0-5.0), explanation (str), tips (list)
    and student answers pss_1..pss_4.
    """
    if not isinstance(record, dict):
        return _error_result(
            {},
            missing=list(REQUIRED_AI_FIELDS + REQUIRED_STUDENT_FIELDS),
            invalid=["record"],
            reason=reason or ai_error,
            data_path=data_path,
            auto_save_on_unavailable=auto_save_on_unavailable,
        )

    explicit_ai_error = ai_error or reason
    has_error_indicator = bool(
        explicit_ai_error
        or (isinstance(record, dict) and (
            record.get("ai_ok") is False
            or record.get("llm_unavailable") is True
            or bool(record.get("error"))
            or bool(record.get("error_code"))
            or bool(record.get("ai_error"))
        ))
    )
    if has_error_indicator:
        err = (
            explicit_ai_error
            or (record.get("error") if isinstance(record, dict) else None)
            or (record.get("error_code") if isinstance(record, dict) else None)
            or (record.get("ai_error") if isinstance(record, dict) else None)
            or "unable to communicate to ai server"
        )
        clean_reason = extract_error_reason(err)
        prompt = display_error_prompt(clean_reason)
        auto_res = (
            save_record_locally(record, reason=clean_reason, data_path=data_path)
            if auto_save_on_unavailable and isinstance(record, dict) and record
            else {}
        )
        res = dict(record) if isinstance(record, dict) else {}
        res.update({
            "ok": False,
            "ai_ok": False,
            "error": clean_reason,
            "error_code": clean_reason,
            "prompt": prompt,
            "message": prompt,
            "can_save_locally": True,
            "auto_saved": auto_res.get("ok", False),
            "saved": auto_res.get("ok", False),
            "saved_record": auto_res.get("record"),
            "path": auto_res.get("path"),
        })
        return res

    missing, invalid = _ai_field_problems(record)
    for key in REQUIRED_STUDENT_FIELDS:
        if key not in record or record.get(key) is None:
            missing.append(key)
        else:
            val = _safe_float(record.get(key))
            if val is None or not (1.0 <= val <= 5.0):
                invalid.append(key)

    if missing or invalid:
        ai_fields_missing = any(field in missing for field in REQUIRED_AI_FIELDS)
        if ai_fields_missing or reason or ai_error:
            err_reason = reason or ai_error or "ai unavailable"
            clean_reason = extract_error_reason(err_reason)
            prompt = display_error_prompt(clean_reason)
            return _error_result(
                record,
                missing=missing,
                invalid=invalid,
                reason=clean_reason,
                prompt=prompt,
                data_path=data_path,
                auto_save_on_unavailable=auto_save_on_unavailable,
            )
        return _error_result(
            record,
            missing=missing,
            invalid=invalid,
            auto_save_on_unavailable=False,
        )

    # 1. Compute reference score = average of PSS items (1.0-5.0)
    reference_score = compute_reference_score(record)

    # 2. Cross-check AI score against reference score
    ai_score = float(record["perceived_stress_score"])
    final_score, score_mismatch = cross_check_score(ai_score, reference_score)
    score_source = "ai" if not score_mismatch else "reference"

    # 3. Assign tier strictly from score
    tier = assign_tier(final_score)

    # 4. Crisis language / safety check override
    crisis = _has_crisis_language(record.get("feelings_text"))
    safety = bool(record.get("safety_flag") or crisis)
    if safety:
        tier = TIER_REACH_OUT

    prominence = _TIER_TO_PROMINENCE[tier]
    category = _TIER_TO_CATEGORY[tier]

    # Context flags (do NOT raise tier)
    flags, support_mean, support_count = compute_context_flags(record)
    factors = build_factor_insights(record, flags, support_mean, support_count)

    # Stressors
    stressors: list[str] = []
    if flags.get("sleep"):
        stressors.append("sleep_deprivation")
    if flags.get("workload"):
        stressors.append("academic_overload")
    if flags.get("finances"):
        stressors.append("financial_pressure")
    if flags.get("support"):
        stressors.append("low_social_support")
    if final_score > TIER_REACH_OUT_ABOVE:
        stressors.append("high_stress")

    # Tips
    raw_tips = record.get("tips", [])
    if not isinstance(raw_tips, list):
        raw_tips = []
    tips = [t for t in raw_tips if t in ALLOWED_TIP_IDS]
    if tier == TIER_REACH_OUT and "talk_to_someone" not in tips:
        tips.insert(0, "talk_to_someone")
    tips = list(dict.fromkeys(tips))[:_MAX_TIPS]
    if not tips:
        tips = ["short_breaks", "workload_chunks"]

    explanation = str(record.get("explanation", "")).strip()

    enriched = dict(record)
    enriched.update({
        "ok": True,
        "error": None,
        "tier": tier,
        "soft_label": tier,
        "perceived_stress_score": round(final_score, 2),
        "reference_score": round(reference_score, 2),
        "score_source": score_source,
        "score_mismatch": score_mismatch,
        "ai_score": round(ai_score, 2),
        "tips": tips,
        "explanation": explanation,
        "reasoning": explanation,
        "speak_prominence": prominence,
        "risk_category": category,
        "risk_score": round((final_score - 1.0) / 4.0, 2),
        "primary_stressors": stressors,
        "source": LOGIC_SOURCE,
        "ai_ok": True,
        "ai_model": record.get("ai_model", ""),
        "context_flags": flags,
        "support_mean": round(support_mean, 2) if support_mean is not None else None,
        "factor_insights": factors,
        "safety_flag": safety,
        "logic_rule": f"tier_{tier.lower().replace(' ', '_').replace('\'', '')}",
        "logic_rules": [f"tier_{tier.lower().replace(' ', '_').replace('\'', '')}"],
    })
    return enriched


def finalize_outcome(record: dict[str, Any]) -> dict[str, Any]:
    """Alias of apply_logic."""
    return apply_logic(record)


def _ai_field_problems(record: dict[str, Any]) -> tuple[list[str], list[str]]:
    missing: list[str] = []
    invalid: list[str] = []

    for key in REQUIRED_AI_FIELDS:
        if key not in record:
            missing.append(key)

    if "perceived_stress_score" in record:
        val = _safe_float(record.get("perceived_stress_score"))
        if val is None or not (1.0 <= val <= 5.0):
            invalid.append("perceived_stress_score")

    if "explanation" in record:
        exp = record.get("explanation")
        if not isinstance(exp, str) or not exp.strip():
            invalid.append("explanation")

    if "tips" in record:
        tips = record.get("tips")
        if not isinstance(tips, list):
            invalid.append("tips")

    return missing, invalid


def _error_result(
    record: dict[str, Any],
    *,
    missing: list[str],
    invalid: list[str],
    reason: Any = None,
    prompt: str | None = None,
    data_path: str | Path | None = None,
    auto_save_on_unavailable: bool = False,
) -> dict[str, Any]:
    result = dict(record) if isinstance(record, dict) else {}
    result["ok"] = False
    result["missing"] = list(missing)
    result["invalid"] = list(invalid)

    ai_fields_missing = any(field in missing for field in REQUIRED_AI_FIELDS)
    has_explicit_error = bool(
        reason
        or (isinstance(record, dict) and (
            record.get("ai_error")
            or record.get("error")
            or record.get("error_code")
            or record.get("ai_ok") is False
        ))
    )
    is_llm_unavailable = ai_fields_missing or has_explicit_error

    clean_reason = extract_error_reason(reason or "unable to communicate to ai server")

    if is_llm_unavailable:
        if prompt is None:
            prompt = display_error_prompt(clean_reason)
        result["prompt"] = prompt
        result["message"] = prompt
        result["error"] = clean_reason
        result["error_code"] = clean_reason
        result["error_reason"] = clean_reason
        result["can_save_locally"] = True
        result["auto_saved"] = False
        result["saved"] = False

        if auto_save_on_unavailable and isinstance(record, dict) and record:
            save_res = save_record_locally(record, reason=clean_reason, data_path=data_path)
            result["auto_saved"] = save_res.get("ok", False)
            result["saved"] = save_res.get("ok", False)
            result["saved_record"] = save_res.get("record")
            result["path"] = save_res.get("path")
    else:
        result["error"] = ERROR_AI_FIELDS_REQUIRED
        result["message"] = (
            "Logic requires a successful Gemini record with perceived_stress_score, "
            "explanation, and tips."
        )

    return result


# ---------------------------------------------------------------------------
# Runtime auto-integration with web UI & AI layer
# ---------------------------------------------------------------------------

_LAST_AI_ERROR: dict[str, Any] = {}
_PENDING_FAILED_CHECKIN: dict[str, Any] = {}

_LOCAL_SAVE_UI_SCRIPT = """<script id="ds-logic-local-save-script">
(() => {
  function checkAndRenderSaveOption() {
    const main = document.getElementById('ds-main');
    if (!main) return;
    const failureSupport = main.querySelector('#ds-failure-support');
    const errorEl = main.querySelector('#ds-error');
    if (!failureSupport) return;

    const hasError = (errorEl && errorEl.textContent.trim().length > 0) || failureSupport.children.length > 0;
    let card = main.querySelector('#ds-local-save-card');

    if (hasError && !card) {
      card = document.createElement('div');
      card.id = 'ds-local-save-card';
      card.className = 'ds-support';
      card.style.marginTop = '1.25rem';
      card.style.border = '1px solid #cbd5e1';
      card.style.borderRadius = '12px';
      card.style.padding = '1.25rem';
      card.style.background = '#f8fafc';
      card.innerHTML = [
        '<h3 style="margin-top:0;font-size:1.15rem;color:#1e293b;">Option to save your check-in locally</h3>',
        '<p style="margin:0.5rem 0;color:#475569;font-size:0.95rem;">AI suggestions are currently unavailable. Would you like to save your questionnaire answers locally on this computer for your records and admin review?</p>',
        '<div style="margin:0.75rem 0;">',
        '  <label style="display:inline-flex;align-items:center;gap:0.5rem;cursor:pointer;font-size:0.95rem;color:#334155;">',
        '    <input type="checkbox" id="ds-local-save-consent" style="width:1.1rem;height:1.1rem;cursor:pointer;">',
        '    <span>I want to save my check-in locally on this computer.</span>',
        '  </label>',
        '</div>',
        '<button type="button" id="ds-btn-save-locally" class="ds-secondary" style="cursor:pointer;padding:0.5rem 1rem;font-weight:600;">Save check-in locally</button>',
        '<div id="ds-local-save-result" style="margin-top:0.6rem;font-size:0.95rem;font-weight:500;" role="status"></div>'
      ].join('');
      failureSupport.appendChild(card);

      const saveBtn = card.querySelector('#ds-btn-save-locally');
      const consentCb = card.querySelector('#ds-local-save-consent');
      const statusDiv = card.querySelector('#ds-local-save-result');

      saveBtn.addEventListener('click', async function() {
        if (!consentCb.checked) {
          statusDiv.style.color = '#dc2626';
          statusDiv.textContent = 'Please tick the consent box before saving locally.';
          return;
        }
        saveBtn.disabled = true;
        statusDiv.style.color = '#64748b';
        statusDiv.textContent = 'Saving check-in locally…';
        try {
          const cfgEl = document.getElementById('campus-config');
          const csrf = cfgEl ? JSON.parse(cfgEl.textContent).csrfToken : '';
          const res = await fetch('/api/save-checkin-locally', {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf},
            body: JSON.stringify({consent: true, opt_in: true})
          });
          const data = await res.json();
          if (res.ok && data.ok) {
            statusDiv.style.color = '#16a34a';
            statusDiv.textContent = '✓ ' + (data.message || 'Your check-in has been saved locally on this computer (data/student_records.json).');
            consentCb.disabled = true;
            saveBtn.textContent = 'Saved locally';
          } else {
            saveBtn.disabled = false;
            statusDiv.style.color = '#dc2626';
            statusDiv.textContent = data.message || 'Could not save locally. Please try again.';
          }
        } catch (err) {
          saveBtn.disabled = false;
          statusDiv.style.color = '#dc2626';
          statusDiv.textContent = 'Could not connect to save locally. Please try again.';
        }
      });
    } else if (!hasError && card) {
      card.remove();
    }
  }

  const observer = new MutationObserver(checkAndRenderSaveOption);
  const target = document.getElementById('ds-main') || document.body;
  observer.observe(target, {childList: true, subtree: true, characterData: true});
})();
</script>"""


def _install_runtime_hooks() -> None:
    try:
        import ai_manager  # type: ignore[import]
        orig_analyse = getattr(ai_manager, "analyse_student", None)
        if orig_analyse and not getattr(orig_analyse, "_logic_hooked", False):
            def _hooked_analyse_student(student_dict: dict[str, Any], *args: Any, **kwargs: Any) -> Any:
                ok, enriched, error = orig_analyse(student_dict, *args, **kwargs)
                if not ok:
                    clean_reason = extract_error_reason(error)
                    _LAST_AI_ERROR["reason"] = clean_reason
                    _LAST_AI_ERROR["error"] = error
                    _LAST_AI_ERROR["record"] = dict(student_dict) if isinstance(student_dict, dict) else {}
                    _PENDING_FAILED_CHECKIN["record"] = dict(student_dict) if isinstance(student_dict, dict) else {}
                    _PENDING_FAILED_CHECKIN["reason"] = clean_reason
                    _PENDING_FAILED_CHECKIN["saved"] = False
                    display_error_prompt(clean_reason)
                return ok, enriched, error
            _hooked_analyse_student._logic_hooked = True  # type: ignore[attr-defined]
            ai_manager.analyse_student = _hooked_analyse_student
    except Exception:
        pass

    try:
        from flask import Flask, jsonify, request  # type: ignore[import]
        orig_init = getattr(Flask, "__init__", None)
        if orig_init and not getattr(orig_init, "_logic_hooked", False):
            def _hooked_flask_init(app_self: Any, *args: Any, **kwargs: Any) -> Any:
                orig_init(app_self, *args, **kwargs)

                @app_self.post("/api/save-checkin-locally")
                def _save_checkin_locally_route() -> Any:
                    values = request.get_json(silent=True) if request.is_json else request.form
                    values = values if isinstance(values, dict) or hasattr(values, "get") else {}
                    consent = values.get("consent") in (True, "true", "yes", "on", 1) or values.get("opt_in") in (True, "true", "yes", "on", 1)
                    if not consent:
                        return jsonify({"ok": False, "message": "Please tick the consent box to save locally."}), 400
                    record = _PENDING_FAILED_CHECKIN.get("record")
                    if not record:
                        return jsonify({"ok": False, "message": "No check-in found to save. Please review your answers and try again."}), 409
                    reason = _PENDING_FAILED_CHECKIN.get("reason", "unable to communicate to ai server")
                    save_res = save_record_locally(record, reason=reason, data_path=app_self.config.get("DATA_PATH"))
                    if save_res.get("ok"):
                        _PENDING_FAILED_CHECKIN["saved"] = True
                        return jsonify({
                            "ok": True,
                            "saved": True,
                            "message": "Your check-in has been saved locally on this computer (data/student_records.json).",
                            "path": save_res.get("path"),
                        })
                    return jsonify({"ok": False, "message": "Could not save check-in locally. Please try again."}), 500

                app_self.add_url_rule(
                    "/api/save-local",
                    endpoint="save_local_alias",
                    view_func=_save_checkin_locally_route,
                    methods=["POST"],
                )

                @app_self.after_request
                def _inject_error_prompt_and_ui(response: Any) -> Any:
                    if response.status_code == 503 and response.is_json:
                        try:
                            data = response.get_json(silent=True)
                            if isinstance(data, dict):
                                code_val = data.get("error_code")
                                clean_reason = _PENDING_FAILED_CHECKIN.get("reason") or _LAST_AI_ERROR.get("reason") or extract_error_reason(code_val)
                                prompt_str = format_error_prompt(clean_reason)

                                data["message"] = f"We encountered an {prompt_str}. AI suggestions are unavailable right now. You can choose to save your check-in locally on this computer below."
                                data["prompt"] = prompt_str
                                data["error_reason"] = clean_reason
                                data["can_save_locally"] = True
                                data["auto_saved"] = False
                                data["saved"] = False
                                if isinstance(data.get("advisor"), dict):
                                    data["advisor"]["heading"] = prompt_str.capitalize()
                                    data["advisor"]["body"] = f"We encountered an {prompt_str}. AI suggestions could not be generated. You can choose to save your check-in locally on this computer for review, or reach out to campus support:"
                                    data["advisor"]["cta"] = "Save check-in locally below, or contact support:"
                                response.set_data(json.dumps(data))
                        except Exception:
                            pass

                    if response.status_code == 200 and response.content_type and "text/html" in response.content_type:
                        try:
                            content = response.get_data(as_text=True)
                            if "dns-campus" in content and "ds-logic-local-save-script" not in content:
                                if "</body>" in content:
                                    content = content.replace("</body>", f"{_LOCAL_SAVE_UI_SCRIPT}\n</body>")
                                else:
                                    content += f"\n{_LOCAL_SAVE_UI_SCRIPT}"
                                response.set_data(content)
                        except Exception:
                            pass

                    return response

            _hooked_flask_init._logic_hooked = True  # type: ignore[attr-defined]
            Flask.__init__ = _hooked_flask_init
    except Exception:
        pass


_install_runtime_hooks()
