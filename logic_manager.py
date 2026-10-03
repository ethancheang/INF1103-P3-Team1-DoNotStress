"""
DoNotStress - Logic Layer (logic_manager)

The "domain brain" of the pipeline. It acts on the AI's output:

    io_manager -> ai_manager -> logic_manager -> data_manager

What this module does (course brief for the Logic Manager)
----------------------------------------------------------
1. Applies business rules to the AI-enriched record.
2. Decides an outcome for the student: accept, flag, route or reject.
3. Uses multi-condition rules that combine AI output fields (risk_score,
   soft_label, risk_category, primary_stressors) with the student's own
   numbers (stress, sleep, financial stress, social support).
4. Holds the DoNotStress domain idea: the AI's reading of a student is a
   starting point. The team's rules check it against the student's own
   numbers and may raise the support level, never lower it.

Outcomes (stored on the record as "outcome")
--------------------------------------------
accept - "You're doing ok": nothing further to do.
flag   - "Worth a check-in".
route  - "Please reach out": point the student to an advisor.
reject - no usable AI result, so nothing is decided (ok is False).

Design rules
------------
* Procedural Python only: functions, no classes.
* No terminal output or input, no AI calls and no file access.
* The caller's record is never changed; a new record is returned.
* Rules only raise the support level. They never lower it.
* Missing student numbers mean a rule does not fire. Nothing is invented.

Record keys used
----------------
AI fields (required): risk_score, risk_category, primary_stressors,
    soft_label, tips, speak_prominence, reasoning, confidence
Student numbers (optional): sleep_hours, stress_level, financial_stress,
    social_support

Public functions: apply_logic(record) and its alias finalize_outcome(record).
"""

from __future__ import annotations

import copy
import math
from typing import Any

# A plain dictionary: the student's inputs plus the AI's fields (see above).
AIEnrichedRecord = dict[str, Any]


# ---------------------------------------------------------------------------
# Locked allow-lists. Keys and strings must match io_manager and ai_manager so
# the Flask formatters and the data layer stay aligned (the tests check this).
# ---------------------------------------------------------------------------

SOFT_LABEL_OK = "You're doing ok"
SOFT_LABEL_CHECK_IN = "Worth a check-in"
SOFT_LABEL_REACH_OUT = "Please reach out"
SOFT_LABEL_OK_CURLY = "You’re doing ok"  # same label with a curly apostrophe

# Every tuple below runs from the lowest to the highest support level.
SOFT_LABELS = (
    SOFT_LABEL_OK,
    SOFT_LABEL_CHECK_IN,
    SOFT_LABEL_REACH_OUT,
)
_SOFT_LABEL_ALIASES = {
    SOFT_LABEL_OK: SOFT_LABEL_OK,
    SOFT_LABEL_OK_CURLY: SOFT_LABEL_OK,
    SOFT_LABEL_CHECK_IN: SOFT_LABEL_CHECK_IN,
    SOFT_LABEL_REACH_OUT: SOFT_LABEL_REACH_OUT,
}

PROMINENCE_LOW = "low"
PROMINENCE_MEDIUM = "medium"
PROMINENCE_HIGH = "high"
SPEAK_PROMINENCE = (PROMINENCE_LOW, PROMINENCE_MEDIUM, PROMINENCE_HIGH)
ALLOWED_SPEAK_PROMINENCE = frozenset(SPEAK_PROMINENCE)

CATEGORY_LOW = "Low"
CATEGORY_MODERATE = "Moderate"
CATEGORY_HIGH = "High"
RISK_CATEGORIES = (CATEGORY_LOW, CATEGORY_MODERATE, CATEGORY_HIGH)

# Tip IDs only - same keys as io_manager.TIPS_ALLOWLIST. Copy lives in I/O.
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

# Gemini fields that must already be on the record. Same as ai_manager's
# required fields, except recommended_support (passed through, unused here).
REQUIRED_AI_FIELDS = (
    "risk_score",
    "risk_category",
    "primary_stressors",
    "soft_label",
    "tips",
    "speak_prominence",
    "reasoning",
    "confidence",
)


# ---------------------------------------------------------------------------
# What this module puts on the result record
# ---------------------------------------------------------------------------

LOGIC_SOURCE = "ai_logic"
ERROR_AI_FIELDS_REQUIRED = "ai_fields_required"

OUTCOME_ACCEPT = "accept"
OUTCOME_FLAG = "flag"
OUTCOME_ROUTE = "route"
OUTCOME_REJECT = "reject"

RULE_REACH_OUT = "reach_out_high_ai_stress_low_support"
RULE_FINANCIAL_CHECK_IN = "check_in_high_category_financial"
RULE_SLEEP_CHECK_IN = "check_in_sleep_deprivation"
RULE_NONE = "ai_clamped"  # no domain rule matched; AI values were only cleaned


# ---------------------------------------------------------------------------
# Domain settings - the team's numbers. Change them here and nowhere else.
# The student scales (stress, financial stress, social support) run 1 to 10.
# ---------------------------------------------------------------------------

# Rule 1 - reach out
REACH_OUT_RISK_ABOVE = 0.75  # the AI's risk_score must be above this
REACH_OUT_STRESS_MIN = 8  # stress_level at least this
REACH_OUT_SUPPORT_MAX = 3  # social_support at most this

# Rule 2 - financial check-in
FINANCIAL_STRESS_MIN = 8  # financial_stress at least this

# Rule 3 - sleep check-in
SLEEP_HOURS_MAX = 5.0  # sleep_hours at most this
SLEEP_STRESS_MIN = 7  # stress_level at least this

# Used only when the AI's own risk_category cannot be used: score -> category.
CATEGORY_HIGH_ABOVE = 0.75
CATEGORY_MODERATE_FROM = 0.40

_MAX_TIPS = 4

_CATEGORY_TO_LABEL = {
    CATEGORY_HIGH: SOFT_LABEL_REACH_OUT,
    CATEGORY_MODERATE: SOFT_LABEL_CHECK_IN,
    CATEGORY_LOW: SOFT_LABEL_OK,
}
_CATEGORY_TO_PROMINENCE = {
    CATEGORY_HIGH: PROMINENCE_HIGH,
    CATEGORY_MODERATE: PROMINENCE_MEDIUM,
    CATEGORY_LOW: PROMINENCE_LOW,
}

_TIP_SLEEP = "sleep_routine"
_TIP_MONEY = "money_worries"
_TIP_TALK = "talk_to_someone"
_TIP_FEELINGS = "feelings_check_in"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_logic(record: AIEnrichedRecord) -> AIEnrichedRecord:
    """Apply the DoNotStress business rules to one AI-enriched student record.

    Steps: reject a record without a usable AI result, clean the AI fields,
    run the domain rules, decide the outcome, then return a new record. The
    caller's record is never changed. Student numbers only matter inside rules
    that also use AI fields.

    Args:
        record: the student's inputs plus every field in REQUIRED_AI_FIELDS.

    Returns:
        On success: a copy of the record with ok=True, source="ai_logic", the
        cleaned (and possibly raised) AI fields, outcome set to accept, flag
        or route, plus logic_rule, logic_rules and logic_clamp_notes.
        On failure: a copy with ok=False, error="ai_fields_required",
        outcome="reject" and the lists "missing" and "invalid". No soft_label,
        tips or speak_prominence is invented.
    """
    if not isinstance(record, dict):
        return _error_result(
            {},
            missing=list(REQUIRED_AI_FIELDS),
            invalid=["record"],
        )

    missing, invalid = _ai_field_problems(record)
    if missing or invalid:
        return _error_result(record, missing=missing, invalid=invalid)

    ai_fields, clamp_notes = _clamp_ai_fields(record)
    student = _read_student_numbers(record)
    decided, matched_rules = _run_domain_rules(ai_fields, student)
    reasoning = _note_rules(
        ai_fields["reasoning"], matched_rules, changed=decided != ai_fields
    )

    result = copy.deepcopy(record)
    result.update(decided)
    result.update({
        "ok": True,
        "error": None,
        "reasoning": reasoning,
        "source": LOGIC_SOURCE,
        "ai_ok": True,
        "outcome": _decide_outcome(decided["soft_label"]),
        "logic_rule": matched_rules[0] if matched_rules else RULE_NONE,
        "logic_rules": matched_rules,
        "logic_clamp_notes": clamp_notes,
    })
    return result


def finalize_outcome(record: AIEnrichedRecord) -> AIEnrichedRecord:
    """Alias of apply_logic - finalize a Gemini-enriched record."""
    return apply_logic(record)


# ---------------------------------------------------------------------------
# Domain rules - the DoNotStress idea lives here
# ---------------------------------------------------------------------------

def _run_domain_rules(
    ai_fields: dict[str, Any], student: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """Run the three domain rules in order and raise the support level.

    Rule 2 reads the label and category as they are after Rule 1, so it only
    matters for a student whom Rule 1 did not already raise.

    Args:
        ai_fields: the cleaned AI fields from _clamp_ai_fields.
        student: the student's numbers from _read_student_numbers.

    Returns:
        (fields, matched): the AI fields with any raise applied, and the ids of
        the rules whose conditions matched, in the order they ran.
    """
    band = {
        "soft_label": ai_fields["soft_label"],
        "speak_prominence": ai_fields["speak_prominence"],
        "risk_category": ai_fields["risk_category"],
        "tips": list(ai_fields["tips"]),
    }
    matched: list[str] = []

    if _reach_out_rule_matches(
        ai_fields["risk_score"],
        student["stress_level"],
        student["social_support"],
    ):
        band = _raise_band(
            band,
            SOFT_LABEL_REACH_OUT, PROMINENCE_HIGH, CATEGORY_HIGH,
            (_TIP_TALK, _TIP_FEELINGS),
        )
        matched.append(RULE_REACH_OUT)

    if _financial_rule_matches(
        band["soft_label"],
        band["risk_category"],
        student["financial_stress"],
    ):
        band = _raise_band(
            band,
            SOFT_LABEL_CHECK_IN, PROMINENCE_MEDIUM, CATEGORY_HIGH,
            (_TIP_MONEY,),
        )
        matched.append(RULE_FINANCIAL_CHECK_IN)

    if _sleep_rule_matches(
        ai_fields["primary_stressors"],
        student["sleep_hours"],
        student["stress_level"],
    ):
        band = _raise_band(
            band,
            SOFT_LABEL_CHECK_IN, PROMINENCE_MEDIUM, CATEGORY_MODERATE,
            (_TIP_SLEEP,),
        )
        matched.append(RULE_SLEEP_CHECK_IN)

    return {**ai_fields, **band}, matched


def _reach_out_rule_matches(
    risk_score: float, stress: int | None, support: int | None
) -> bool:
    """Rule 1 - reach out: very high AI risk, high stress, little support.

    True when the AI's risk_score is above REACH_OUT_RISK_ABOVE AND the
    student's stress_level is at least REACH_OUT_STRESS_MIN AND their
    social_support is at most REACH_OUT_SUPPORT_MAX. A missing student number
    means the rule does not fire.

    Uses AI field: risk_score.
    Uses student fields: stress_level, social_support.
    Effect: at least "Please reach out" / high / High, plus the talk and
    feelings tips.
    """
    return (
        risk_score > REACH_OUT_RISK_ABOVE
        and stress is not None
        and stress >= REACH_OUT_STRESS_MIN
        and support is not None
        and support <= REACH_OUT_SUPPORT_MAX
    )


def _financial_rule_matches(
    soft_label: str, risk_category: str, financial: int | None
) -> bool:
    """Rule 2 - financial check-in: a calm label the AI's own category denies.

    True when the soft_label is "You're doing ok" AND the risk_category is
    "High" AND the student's financial_stress is at least
    FINANCIAL_STRESS_MIN. The AI contradicts itself and money worries are
    present, so the cautious reading wins.

    Uses AI fields: soft_label, risk_category.
    Uses student field: financial_stress.
    Effect: at least "Worth a check-in" / medium, plus the money tip.
    """
    return (
        soft_label == SOFT_LABEL_OK
        and risk_category == CATEGORY_HIGH
        and financial is not None
        and financial >= FINANCIAL_STRESS_MIN
    )


def _sleep_rule_matches(
    stressors: list[str], sleep: float | None, stress: int | None
) -> bool:
    """Rule 3 - sleep check-in: the AI names sleep loss and the numbers agree.

    True when "sleep_deprivation" is one of the AI's primary_stressors AND the
    student sleeps at most SLEEP_HOURS_MAX hours AND their stress_level is at
    least SLEEP_STRESS_MIN.

    Uses AI field: primary_stressors.
    Uses student fields: sleep_hours, stress_level.
    Effect: at least "Worth a check-in" / medium / Moderate, plus the sleep tip.
    """
    return (
        "sleep_deprivation" in stressors
        and sleep is not None
        and sleep <= SLEEP_HOURS_MAX
        and stress is not None
        and stress >= SLEEP_STRESS_MIN
    )


def _raise_band(
    band: dict[str, Any],
    label: str,
    prominence: str,
    category: str,
    extra_tips: tuple[str, ...],
) -> dict[str, Any]:
    """Return a new band raised to at least the target values.

    A band is the soft_label, speak_prominence, risk_category and tips of a
    record. Escalate only: an already-higher AI value is kept. The extra tips
    go first.
    """
    return {
        "soft_label": _higher(band["soft_label"], label, SOFT_LABELS),
        "speak_prominence": _higher(
            band["speak_prominence"], prominence, SPEAK_PROMINENCE
        ),
        "risk_category": _higher(band["risk_category"], category, RISK_CATEGORIES),
        "tips": _ensure_tips(band["tips"], extra_tips),
    }


def _higher(current: str, target: str, ordered: tuple[str, ...]) -> str:
    """Return whichever value sits later in ordered (lowest to highest)."""
    if ordered.index(target) > ordered.index(current):
        return target
    return current


def _ensure_tips(tips: list[str], extra: tuple[str, ...]) -> list[str]:
    """Put the extra tip IDs first; keep allowed IDs once each; cap the list."""
    ordered: list[str] = []
    for tip_id in list(extra) + list(tips):
        if tip_id in ALLOWED_TIP_IDS and tip_id not in ordered:
            ordered.append(tip_id)
    return ordered[:_MAX_TIPS]


# ---------------------------------------------------------------------------
# Outcome - what happens to the student
# ---------------------------------------------------------------------------

def _decide_outcome(soft_label: str) -> str:
    """Decide the outcome from the final support label.

    "Please reach out" -> route (point the student to an advisor)
    "Worth a check-in" -> flag
    anything else      -> accept (nothing further to do)
    """
    if soft_label == SOFT_LABEL_REACH_OUT:
        return OUTCOME_ROUTE
    if soft_label == SOFT_LABEL_CHECK_IN:
        return OUTCOME_FLAG
    return OUTCOME_ACCEPT


def _note_rules(reasoning: str, matched: list[str], changed: bool) -> str:
    """Add a short audit note to the AI's reasoning when a rule matched.

    The note says "adjusted" if a rule really changed the record and
    "confirmed" if the AI had already reached that level.
    """
    if not matched:
        return reasoning
    verb = "adjusted" if changed else "confirmed"
    return f"{reasoning} Logic {verb}: {', '.join(matched)}."


def _error_result(
    record: AIEnrichedRecord,
    *,
    missing: list[str],
    invalid: list[str],
) -> AIEnrichedRecord:
    """Build the reject result: the original fields plus ok=False and why.

    Nothing is invented: no soft_label, tips or speak_prominence is added.
    Callers must treat ok=False as a hard stop, not as a fallback engine.
    """
    result = copy.deepcopy(record) if isinstance(record, dict) else {}
    result["ok"] = False
    result["error"] = ERROR_AI_FIELDS_REQUIRED
    result["outcome"] = OUTCOME_REJECT
    result["missing"] = list(missing)
    result["invalid"] = list(invalid)
    result["message"] = (
        "Logic requires a successful Gemini (AI-enriched) record; "
        "it does not invent soft outcomes from student inputs alone."
    )
    return result


# ---------------------------------------------------------------------------
# Check the AI fields
# ---------------------------------------------------------------------------

def _ai_field_problems(record: AIEnrichedRecord) -> tuple[list[str], list[str]]:
    """Check the required AI fields.

    Returns (missing, invalid), both in REQUIRED_AI_FIELDS order. "missing"
    lists fields that are absent; "invalid" lists fields that are present but
    have the wrong type. Values that are only out of range or not on an
    allow-list are repaired later by _clamp_ai_fields.
    """
    missing = [name for name in REQUIRED_AI_FIELDS if name not in record]
    invalid = [
        name
        for name in REQUIRED_AI_FIELDS
        if name in record and not _field_is_usable(name, record[name])
    ]
    return missing, invalid


def _field_is_usable(name: str, value: Any) -> bool:
    """True if value has the right type for the named AI field."""
    if name in ("risk_score", "confidence"):
        return _as_unit_interval(value) is not None
    if name == "reasoning":
        return isinstance(value, str) and bool(value.strip())
    if name in ("primary_stressors", "tips"):
        return isinstance(value, list)
    return isinstance(value, str)  # risk_category, soft_label, speak_prominence


# ---------------------------------------------------------------------------
# Clean the AI fields onto the allow-lists (map what is wrong, never invent)
# ---------------------------------------------------------------------------

def _clamp_ai_fields(record: AIEnrichedRecord) -> tuple[dict[str, Any], list[str]]:
    """Put every AI field onto its allow-list and report what had to change.

    Call this only after _ai_field_problems found nothing wrong. Scores are
    limited to 0-1. The risk category and speak prominence are matched
    ignoring case; the soft label must be one of the allowed labels (a curly
    apostrophe is accepted). Anything unknown is rebuilt from the risk score
    or category, and unknown tips and stressors are dropped.

    Returns:
        (cleaned fields, names of the fields that had to be changed).
    """
    risk_score = _as_unit_interval(record["risk_score"])
    confidence = _as_unit_interval(record["confidence"])
    if risk_score is None or confidence is None:
        # Cannot happen after validation. Fail loudly instead of guessing a
        # score: a made-up 0.0 would quietly mean "no risk".
        raise ValueError("_clamp_ai_fields needs a validated record")

    notes: list[str] = []

    category, category_clamped = _clamp_risk_category(
        record["risk_category"], risk_score
    )
    if category_clamped:
        notes.append("risk_category")

    label, label_clamped = _clamp_soft_label(record["soft_label"], category)
    if label_clamped:
        notes.append("soft_label")

    prominence, prominence_clamped = _clamp_speak_prominence(
        record["speak_prominence"], category
    )
    if prominence_clamped:
        notes.append("speak_prominence")

    tips, tips_clamped = _clamp_allowed_ids(record["tips"], ALLOWED_TIP_IDS)
    if tips_clamped:
        notes.append("tips")

    stressors, stressors_clamped = _clamp_allowed_ids(
        record["primary_stressors"], ALLOWED_PRIMARY_STRESSORS
    )
    if stressors_clamped:
        notes.append("primary_stressors")

    return {
        "risk_score": risk_score,
        "confidence": confidence,
        "risk_category": category,
        "soft_label": label,
        "speak_prominence": prominence,
        "tips": tips,
        "primary_stressors": stressors,
        "reasoning": str(record["reasoning"]).strip(),
    }, notes


def _clamp_risk_category(value: Any, risk_score: float) -> tuple[str, bool]:
    """Match the category ignoring case; if unknown, rebuild it from the score."""
    if isinstance(value, str):
        text = value.strip()
        for category in RISK_CATEGORIES:
            if text.lower() == category.lower():
                return category, text != category
    return _score_to_category(risk_score), True


def _score_to_category(risk_score: float) -> str:
    """Map a 0-1 risk score onto Low, Moderate or High."""
    if risk_score > CATEGORY_HIGH_ABOVE:
        return CATEGORY_HIGH
    if risk_score >= CATEGORY_MODERATE_FROM:
        return CATEGORY_MODERATE
    return CATEGORY_LOW


def _clamp_soft_label(value: Any, risk_category: str) -> tuple[str, bool]:
    """Map the label onto the three allowed ones; if unknown, use the category."""
    if isinstance(value, str):
        mapped = _SOFT_LABEL_ALIASES.get(value.strip())
        if mapped is not None:
            return mapped, mapped != value
    fallback = _CATEGORY_TO_LABEL.get(risk_category, SOFT_LABEL_CHECK_IN)
    return fallback, True


def _clamp_speak_prominence(value: Any, risk_category: str) -> tuple[str, bool]:
    """Match low/medium/high ignoring case; if unknown, use the category."""
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ALLOWED_SPEAK_PROMINENCE:
            return text, text != value
    fallback = _CATEGORY_TO_PROMINENCE.get(risk_category, PROMINENCE_MEDIUM)
    return fallback, True


def _clamp_allowed_ids(value: Any, allowed: frozenset[str]) -> tuple[list[str], bool]:
    """Keep only the text items found in allowed, once each, in their order.

    Returns (kept items, True if anything was dropped or value was not a list).
    """
    if not isinstance(value, list):
        return [], True
    kept: list[str] = []
    dropped = False
    for item in value:
        if not isinstance(item, str):
            dropped = True
            continue
        name = item.strip()
        if name not in allowed:
            dropped = True
        elif name not in kept:
            kept.append(name)
    return kept, dropped


# ---------------------------------------------------------------------------
# Numeric readers - a missing or unusable number means a rule does not fire.
# No defaults: a default would invent an outcome from incomplete input.
# ---------------------------------------------------------------------------

def _read_student_numbers(record: AIEnrichedRecord) -> dict[str, Any]:
    """Read the student's own numbers; anything missing or unusable is None."""
    return {
        "sleep_hours": _safe_float(record.get("sleep_hours")),
        "stress_level": _optional_int(record.get("stress_level")),
        "financial_stress": _optional_int(record.get("financial_stress")),
        "social_support": _optional_int(record.get("social_support")),
    }


def _safe_float(value: Any) -> float | None:
    """Return value as a finite float, or None if it is missing or unusable.

    None, True/False, text that is not a number, NaN and infinity all give None.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _as_unit_interval(value: Any) -> float | None:
    """Return value limited to 0.0-1.0, or None if it is missing or unusable."""
    number = _safe_float(value)
    if number is None:
        return None
    return max(0.0, min(1.0, number))


def _optional_int(value: Any) -> int | None:
    """Return value rounded to a whole number, or None if it is unusable."""
    number = _safe_float(value)
    if number is None:
        return None
    return round(number)
