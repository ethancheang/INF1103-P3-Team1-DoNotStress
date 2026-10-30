"""
DoNotStress — Logic Layer (logic_manager)

Post-AI validator. Gemini is mandatory for every record.

Gemini's analysis (from ai_manager.analyse_student, already schema-checked)
is the result. Logic recomputes the deterministic stress score from the 11
raw answers as an audit and never substitutes its own score. It does not
re-validate Gemini's schema; ai_manager owns that.

Logic is the only module that knows the scoring rules. main.py hands two of
its functions to ai_manager, so ai_manager itself holds no domain logic:
  scoring_instructions()  the formula and tier text for the Gemini prompt
  verify_ai_scores()      checks Gemini's arithmetic and tier before the
                          reply is accepted (a failure is retried like any
                          other invalid AI response)

Rules (logic_rule "v3")
-----------------------
1. Score — mean of the 11 answers on the 1–5 stress scale, equal weight.
   pss_2, pss_3, mspss_friends and mspss_family are positively worded and
   scored as 6 - answer. sleep_hours_avg is converted: 8+ h -> 1,
   7 to <8 -> 2, 6 to <7 -> 3, 5 to <6 -> 4, under 5 -> 5.
2. Cross-check — if Gemini's stress_score is within 0.01 of the logic
   score (the same tolerance verify_ai_scores uses), Gemini's score, tier, tips,
   stressors and reasoning are kept unchanged. Otherwise Logic returns a
   "score_mismatch" error dict and the caller treats the check-in as an AI
   failure (saved as pending, no result).
3. Context flags — sleep, workload, finances, support. Each flag makes sure
   its matching tip is included if there is room (max 4 tips). Flags never
   replace Gemini's tips and never change the tier.
4. Support priority — a multi-condition rule on two AI fields: when Gemini
   rates the check-in High AND lists low_social_support in
   primary_stressors, talk_to_someone is shown first and
   keep_social_contact is added if there is room (support_priority True).
5. Safety — if the reflection safety check fired (safety_flag True), the
   tier is forced to High / "Please reach out" / prominence high and
   talk_to_someone is shown first. The stress score is not changed.

Tiers: Low below 2.5, Moderate 2.5 to 3.5 inclusive, High above 3.5.
These bands are team heuristics, not clinical cut-offs or a diagnosis.

Pure procedural Python: functions only — no classes.
No terminal I/O (print / input), no Gemini / network, no file I/O.

Pipeline position:
  User → io_manager → ai_manager (must succeed) → logic_manager → data_manager
"""

from __future__ import annotations

import math
from typing import Any


# ---------------------------------------------------------------------------
# Locked allow-lists — strings must match io_manager and ai_manager.
# ---------------------------------------------------------------------------

SOFT_LABEL_OK = "You're doing ok"
SOFT_LABEL_CHECK_IN = "Worth a check-in"
SOFT_LABEL_REACH_OUT = "Please reach out"

RISK_CATEGORIES = ("Low", "Moderate", "High")

_CATEGORY_TO_LABEL = {
    "Low": SOFT_LABEL_OK,
    "Moderate": SOFT_LABEL_CHECK_IN,
    "High": SOFT_LABEL_REACH_OUT,
}
_CATEGORY_TO_PROMINENCE = {
    "Low": "low",
    "Moderate": "medium",
    "High": "high",
}

LOGIC_SOURCE = "ai_logic"
LOGIC_RULE = "v3"
ERROR_AI_FIELDS_REQUIRED = "ai_fields_required"
ERROR_SCORE_MISMATCH = "score_mismatch"


# ---------------------------------------------------------------------------
# Domain settings - the team's numbers. Change them here and nowhere else.
# ---------------------------------------------------------------------------

SCALE_MIN = 1
SCALE_MAX = 5

# The 11 scored answers, in survey order.
ANSWER_KEYS = (
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

# Positively worded items: a high answer means LESS stress (6 - answer).
REVERSED_KEYS = ("pss_2", "pss_3", "mspss_friends", "mspss_family")
SUPPORT_KEYS = ("mspss_friends", "mspss_family")

SLEEP_HOURS_MIN = 0
SLEEP_HOURS_MAX = 14

# Sleep hours -> 1–5 stress value: (at least this many hours, value).
SLEEP_HOUR_BANDS = ((8, 1), (7, 2), (6, 3), (5, 4))
SLEEP_HOURS_BELOW_ALL = 5

# Tier bands on the 1–5 average.
CHECK_IN_FROM = 2.5    # 2.5 to 3.5 inclusive -> Moderate
REACH_OUT_ABOVE = 3.5  # above 3.5 -> High

# Gemini's stress_score must sit this close to Logic's (same as ai_manager).
SCORE_TOLERANCE = 0.01

# Context flags (raw answers, same rules as the check-in guide).
SLEEP_FLAG_BELOW_HOURS = 6
SLEEP_QUALITY_FLAG_MIN = 4   # fairly bad or very bad
WORKLOAD_FLAG_MIN = 4        # agree or strongly agree
FINANCE_FLAG_MIN = 4         # high or overwhelming money stress
SUPPORT_FLAG_BELOW = 2.5     # mean raw agreement, mostly disagreeing

FLAG_SLEEP = "sleep"
FLAG_WORKLOAD = "workload"
FLAG_FINANCES = "finances"
FLAG_SUPPORT = "support"

# Each flag makes sure this tip is shown (if there is room).
_FLAG_TIPS = (
    (FLAG_SLEEP, "sleep_routine"),
    (FLAG_WORKLOAD, "workload_chunks"),
    (FLAG_FINANCES, "money_worries"),
    (FLAG_SUPPORT, "talk_to_someone"),
)

_TIP_TALK = "talk_to_someone"
_TIP_KEEP_CONTACT = "keep_social_contact"
MAX_TIPS = 4

# Multi-condition rule on Gemini's fields (see needs_support_priority).
SUPPORT_PRIORITY_CATEGORY = "High"
SUPPORT_PRIORITY_STRESSOR = "low_social_support"

# Short internal note stored with each record (data_manager requires it).
# The student never sees this text; the UI shows tips instead.
RECOMMENDED_SUPPORT = {
    "Low": "Internal: low stress. The UI shows tips, not this field.",
    "Moderate": "Internal: moderate stress. The UI shows tips, not this field.",
    "High": "Internal: high stress. The UI shows tips, not this field.",
}

# Gemini fields that must already be on the record (from ai_manager).
# risk_score and recommended_support are worked out here, not by Gemini.
REQUIRED_AI_FIELDS = (
    "stress_score",
    "risk_category",
    "soft_label",
    "speak_prominence",
    "primary_stressors",
    "tips",
    "reasoning",
    "confidence",
)

# Answer labels for the factor cards (1-based).
SLEEP_QUALITY_OPTIONS = ("Very good", "Fairly good", "Okay", "Fairly bad", "Very bad")
AGREE_OPTIONS = ("Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree")
FIN_OPTIONS = (
    "No stress at all",
    "A little stress",
    "Moderate stress",
    "High stress",
    "Overwhelming stress",
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_logic(record: dict[str, Any]) -> dict[str, Any]:
    """
    Validate Gemini's analysis against the student's answers.

    Input MUST be a dict holding the 11 raw answers and Gemini's fields
    (see REQUIRED_AI_FIELDS). Gemini's result is kept unchanged when its
    stress_score matches the deterministic score within 0.01.

    On success, returns a shallow copy with ok=True, source="ai_logic",
    ai_ok=True, logic_rule="v3", the final outcome fields, plus:
      logic_stress_score  the deterministic 1–5 average (audit only)
      logic_clamp_notes   why Logic changed anything (empty if nothing)
      context_flags       {"sleep", "workload", "finances", "support"}
      support_mean        mean raw agreement of the two support answers
      factor_insights     the four factor cards for the result page
      risk_score          (stress_score - 1) / 4, kept for compatibility
      recommended_support short internal note for the final tier
    feelings_text is removed.

    On missing or unusable fields, returns an error dict:
      {"ok": False, "error": "ai_fields_required", "missing": [...],
       "invalid": [...], ...}
    If Gemini's stress_score is more than 0.01 from Logic's, returns:
      {"ok": False, "error": "score_mismatch", "stress_score": ...,
       "logic_stress_score": ..., ...}

    Does not mutate the original dict.
    """
    if not isinstance(record, dict):
        return _error_result(
            {},
            missing=list(REQUIRED_AI_FIELDS + ANSWER_KEYS),
            invalid=["record"],
        )

    missing, invalid = _field_problems(record)
    if missing or invalid:
        return _error_result(record, missing=missing, invalid=invalid)

    scores = score_answers(record)
    logic_score = scores["stress_score"]
    gemini_score = _safe_float(record["stress_score"])

    # Cross-check only: Logic never substitutes its own score.
    if not _within_tolerance(gemini_score, logic_score):
        return _score_mismatch_result(record, gemini_score, logic_score)

    category = record["risk_category"]
    soft_label = record["soft_label"]
    prominence = record["speak_prominence"]
    notes: list[str] = []
    lead_tips: list[str] = []

    # Safety override from the reflection check (text itself is never used).
    if record.get("safety_flag") is True:
        category = "High"
        soft_label = SOFT_LABEL_REACH_OUT
        prominence = "high"
        lead_tips = [_TIP_TALK]
        notes.append("safety_override: reflection safety check fired")

    # Business rule on two AI fields: a High tier AND low social support.
    support_priority = needs_support_priority(record)
    if support_priority:
        lead_tips = [_TIP_TALK]
        notes.append("support_priority: High tier with low social support")

    flags = scores["context_flags"]
    flag_tips = [tip for flag, tip in _FLAG_TIPS if flags[flag]]
    if support_priority:
        flag_tips.insert(0, _TIP_KEEP_CONTACT)
    tips = _merge_tips(lead_tips, list(record["tips"]), flag_tips)

    enriched = dict(record)
    enriched.pop("feelings_text", None)
    enriched.update({
        "ok": True,
        "error": None,
        "source": LOGIC_SOURCE,
        "ai_ok": True,
        "logic_rule": LOGIC_RULE,
        "stress_score": record["stress_score"],
        "logic_stress_score": logic_score,
        "risk_score": risk_score_for(gemini_score),
        "recommended_support": RECOMMENDED_SUPPORT[category],
        "risk_category": category,
        "soft_label": soft_label,
        "speak_prominence": prominence,
        "tips": tips,
        "primary_stressors": list(record["primary_stressors"]),
        "reasoning": record["reasoning"],
        "logic_clamp_notes": notes,
        "support_priority": support_priority,
        "context_flags": flags,
        "support_mean": scores["support_mean"],
        "factor_insights": factor_insights(record, scores),
    })
    return enriched


def score_answers(record: dict[str, Any]) -> dict[str, Any]:
    """
    Deterministic score of the 11 answers. Caller must pass usable numbers.

    Returns stress_score (1.0–5.0, 2 dp), the tier it falls in, the
    support mean and the four context flags.
    """
    items = [scored_value(key, _safe_float(record[key])) for key in ANSWER_KEYS]
    average = round(sum(items) / len(items), 2)
    support = [_safe_float(record[key]) for key in SUPPORT_KEYS]
    support_mean = round(sum(support) / len(support), 2)
    category = category_for_score(average)
    return {
        "stress_score": average,
        "scored_item_count": len(items),
        "support_mean": support_mean,
        "support_item_count": len(support),
        "risk_category": category,
        "soft_label": _CATEGORY_TO_LABEL[category],
        "speak_prominence": _CATEGORY_TO_PROMINENCE[category],
        "context_flags": context_flags(record, support_mean),
    }


def evaluate(record: dict[str, Any]) -> dict[str, Any]:
    """Run every business rule on the AI-enriched record. Wraps apply_logic.

    Returns the decision dict (ok=True with final fields, or an error dict).
    """
    return apply_logic(record)


def score(record: dict[str, Any]) -> float | None:
    """Return the verified AI stress_score, or None if Logic rejects it.

    Logic never substitutes its own number: logic_stress_score in the
    evaluate() result is an audit value only.
    """
    result = apply_logic(record)
    if not result.get("ok"):
        return None
    return float(result["stress_score"])


def route(record: dict[str, Any]) -> str:
    """Return the outcome path: "Low", "Moderate", "High", or "unavailable".

    Routes on the final risk_category only when the soft_label agrees with it,
    otherwise "unavailable". Pass the dict evaluate() returned.
    """
    if not isinstance(record, dict) or not record.get("ok"):
        return "unavailable"
    category = record.get("risk_category")
    if category in _CATEGORY_TO_LABEL and record.get("soft_label") == _CATEGORY_TO_LABEL[category]:
        return category
    return "unavailable"


def scored_value(key: str, answer: float) -> float:
    """Stress-direction value: sleep hours converted, positive items 6 - answer."""
    if key == "sleep_hours_avg":
        return sleep_hours_stress(answer)
    if key in REVERSED_KEYS:
        return (SCALE_MIN + SCALE_MAX) - answer
    return answer


def sleep_hours_stress(hours: float) -> int:
    """Map typical nightly hours onto the 1–5 stress scale. Scoring only."""
    for at_least, value in SLEEP_HOUR_BANDS:
        if hours >= at_least:
            return value
    return SLEEP_HOURS_BELOW_ALL


def category_for_score(stress_score: float) -> str:
    """Low below 2.5, Moderate 2.5 to 3.5 inclusive, High above 3.5."""
    if stress_score > REACH_OUT_ABOVE:
        return "High"
    if stress_score >= CHECK_IN_FROM:
        return "Moderate"
    return "Low"


def needs_support_priority(record: dict[str, Any]) -> bool:
    """Multi-condition business rule on two fields from Gemini's reply.

    True when Gemini rated the check-in High (risk_category) AND named
    low social support as a stressor (primary_stressors). apply_logic then
    puts "talk to someone" first and adds "keep in touch" while there is room.
    """
    stressors = record.get("primary_stressors")
    return (
        record.get("risk_category") == SUPPORT_PRIORITY_CATEGORY
        and isinstance(stressors, list)
        and SUPPORT_PRIORITY_STRESSOR in stressors
    )


def risk_score_for(stress_score: float) -> float:
    """Map the 1–5 stress score onto 0–1. Kept for compatibility; not a probability."""
    return (stress_score - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)


def scored_items(answers: dict[str, Any]) -> dict[str, int]:
    """The 11 answers converted onto the 1–5 stress scale.

    This is exactly what Gemini must return as scored_items. Caller must
    pass usable answers (see verify_ai_scores).
    """
    return {key: int(scored_value(key, _safe_float(answers[key]))) for key in ANSWER_KEYS}


def verify_ai_scores(ai_fields: dict[str, Any], answers: dict[str, Any]) -> str | None:
    """Check Gemini's arithmetic and tier against the student's answers.

    main.py passes this to ai_manager, which treats any message as an
    invalid AI response and retries. Checks, in order:
      1. risk_category, soft_label and speak_prominence match the tier of
         Gemini's stress_score
      2. scored_items equal the converted answers exactly
      3. stress_score is within 0.01 of the mean of those items

    Returns an error message, or None when everything matches. Never raises.
    """
    if not isinstance(ai_fields, dict) or not isinstance(answers, dict):
        return "verify_ai_scores needs the AI fields and the answers as dicts."
    unusable = [
        key for key in ANSWER_KEYS
        if key not in answers
        or not _answer_in_range(key, answers[key])
        or (key != "sleep_hours_avg" and not float(answers[key]).is_integer())
    ]
    if unusable:
        return f"Cannot convert {', '.join(unusable)} onto the 1-5 stress scale."
    gemini_score = _safe_float(ai_fields.get("stress_score"))
    if gemini_score is None:
        return "stress_score must be a number."

    expected_category = category_for_score(gemini_score)
    if ai_fields.get("risk_category") != expected_category:
        return f"risk_category must be {expected_category} for stress_score {gemini_score}."
    if ai_fields.get("soft_label") != _CATEGORY_TO_LABEL[expected_category]:
        return "soft_label must match risk_category."
    if ai_fields.get("speak_prominence") != _CATEGORY_TO_PROMINENCE[expected_category]:
        return "speak_prominence must match risk_category."

    if ai_fields.get("scored_items") != scored_items(answers):
        return "scored_items does not match the converted answers."
    expected_score = score_answers(answers)["stress_score"]
    if not _within_tolerance(gemini_score, expected_score):
        return (
            "stress_score must match the mean of the 11 converted answers "
            f"(expected {expected_score})."
        )
    return None


def scoring_instructions() -> str:
    """The scoring formula and tier rules, written as instructions for Gemini.

    Built from this module's constants, so the prompt always matches the
    rules verify_ai_scores checks.
    """
    reversed_keys = ", ".join(REVERSED_KEYS)
    sleep_bands = ", ".join(
        f"{hours:g} or more{' hours' if index == 0 else ''} -> {value}"
        for index, (hours, value) in enumerate(SLEEP_HOUR_BANDS)
    )
    return (
        f"Convert each answer onto the {SCALE_MIN} to {SCALE_MAX} stress scale:\n"
        f"- {reversed_keys} are positively worded. "
        f"Convert each as {SCALE_MIN + SCALE_MAX} - answer.\n"
        f"- sleep_hours_avg is hours from {SLEEP_HOURS_MIN} to {SLEEP_HOURS_MAX} in half-hour steps. "
        f"Convert it as: {sleep_bands}, otherwise {SLEEP_HOURS_BELOW_ALL}.\n"
        f"- Every other answer is already on the {SCALE_MIN} to {SCALE_MAX} scale. "
        "Use the number as answered.\n"
        f"stress_score is the mean of those {len(ANSWER_KEYS)} converted values, "
        "rounded to 2 decimal places. Higher stress is worse.\n"
        "Then set the tier from that stress_score:\n"
        f"- below {CHECK_IN_FROM:g}: risk_category Low, soft_label \"{SOFT_LABEL_OK}\", "
        "speak_prominence low\n"
        f"- {CHECK_IN_FROM:g} to {REACH_OUT_ABOVE:g} inclusive: risk_category Moderate, "
        f"soft_label \"{SOFT_LABEL_CHECK_IN}\", speak_prominence medium\n"
        f"- above {REACH_OUT_ABOVE:g}: risk_category High, "
        f"soft_label \"{SOFT_LABEL_REACH_OUT}\", speak_prominence high\n"
        "These bands are a simple guide for this check-in, not clinical cut-offs.\n"
    )


def context_flags(record: dict[str, Any], support_mean: float) -> dict[str, bool]:
    """The four context flags from the raw answers."""
    return {
        FLAG_SLEEP: (
            _safe_float(record["sleep_hours_avg"]) < SLEEP_FLAG_BELOW_HOURS
            or _safe_float(record["sleep_quality"]) >= SLEEP_QUALITY_FLAG_MIN
        ),
        FLAG_WORKLOAD: _safe_float(record["pas_workload"]) >= WORKLOAD_FLAG_MIN,
        FLAG_FINANCES: _safe_float(record["fin_stress"]) >= FINANCE_FLAG_MIN,
        FLAG_SUPPORT: support_mean < SUPPORT_FLAG_BELOW,
    }


def factor_insights(record: dict[str, Any], scores: dict[str, Any]) -> list[dict[str, Any]]:
    """The four factor cards shown on the result page."""
    flags = scores["context_flags"]
    sleep_quality = int(record["sleep_quality"])
    workload = int(record["pas_workload"])
    finances = int(record["fin_stress"])
    return [
        dict(
            title="Rest & recovery",
            flagged=flags[FLAG_SLEEP],
            value=(
                f"{_safe_float(record['sleep_hours_avg']):g} hours · "
                f"{SLEEP_QUALITY_OPTIONS[sleep_quality - 1]} quality"
            ),
            text=(
                "Sleep and stress affect each other. When sleep is short or "
                "restless, everyday tasks can feel harder, and stress can make "
                "it harder to sleep well."
            ),
        ),
        dict(
            title="Study demands",
            flagged=flags[FLAG_WORKLOAD],
            value=f"{workload}/5 · {AGREE_OPTIONS[workload - 1]}",
            text=(
                "A heavy workload can leave less time to rest and recharge. "
                "Feeling behind or overloaded is one of the most common sources "
                "of student stress."
            ),
        ),
        dict(
            title="Money pressures",
            flagged=flags[FLAG_FINANCES],
            value=f"{finances}/5 · {FIN_OPTIONS[finances - 1]}",
            text=(
                "Financial worries can add to the pressure of studying. "
                "Concerns about money often weigh on focus and sleep."
            ),
        ),
        dict(
            title="Support & connection",
            flagged=flags[FLAG_SUPPORT],
            value=(
                f"{scores['support_mean']:g}/5 agreement across "
                f"{scores['support_item_count']} answers"
            ),
            text=(
                "Having people to turn to can make stressful times easier to "
                "handle. Strong support from friends or family helps protect "
                "against stress."
            ),
        ),
    ]


# ---------------------------------------------------------------------------
# Error result — no invented outcomes
# ---------------------------------------------------------------------------

def _error_result(
    record: dict[str, Any],
    *,
    missing: list[str],
    invalid: list[str],
) -> dict[str, Any]:
    """
    Pass through the original fields without adding soft outcomes.
    Callers must treat ok=False as a hard stop, not a fallback engine.
    """
    result = dict(record) if isinstance(record, dict) else {}
    result.pop("feelings_text", None)
    result["ok"] = False
    result["error"] = ERROR_AI_FIELDS_REQUIRED
    result["missing"] = list(missing)
    result["invalid"] = list(invalid)
    result["message"] = (
        "Logic requires a successful Gemini (AI-enriched) record and all 11 "
        "answers; it does not guess outcomes without them."
    )
    return result


def _score_mismatch_result(
    record: dict[str, Any],
    gemini_score: float,
    logic_score: float,
) -> dict[str, Any]:
    """
    Gemini's score disagrees with the answers. No outcome is produced; the
    caller treats this like any other AI failure.
    """
    result = dict(record)
    result.pop("feelings_text", None)
    result.update({
        "ok": False,
        "error": ERROR_SCORE_MISMATCH,
        "stress_score": record["stress_score"],
        "logic_stress_score": logic_score,
        "message": (
            f"Gemini stress_score {gemini_score:g} does not match the answers "
            f"({logic_score:g}); no result is given."
        ),
    })
    return result


def _field_problems(record: dict[str, Any]) -> tuple[list[str], list[str]]:
    """
    Return (missing keys, unusable keys).

    Only checks that fields exist and that numbers Logic computes with are
    numbers. Gemini's schema is ai_manager's job.
    """
    missing = [key for key in REQUIRED_AI_FIELDS + ANSWER_KEYS if key not in record]
    invalid = [
        key for key in ("stress_score",) + ANSWER_KEYS
        if key in record and not _answer_in_range(key, record[key])
    ]
    for key in ("tips", "primary_stressors"):
        if key in record and not isinstance(record[key], list):
            invalid.append(key)
    return missing, invalid


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _merge_tips(lead: list[str], gemini: list[str], flagged: list[str]) -> list[str]:
    """
    lead first, then all of Gemini's tips, then flag tips while there is room.

    Gemini gives at most 3 tips and lead holds at most one, so Gemini's tips
    are never pushed out.
    """
    ordered: list[str] = []
    for tip_id in lead + gemini:
        if tip_id not in ordered:
            ordered.append(tip_id)
    for tip_id in flagged:
        if len(ordered) >= MAX_TIPS:
            break
        if tip_id not in ordered:
            ordered.append(tip_id)
    return ordered[:MAX_TIPS]


def _within_tolerance(gemini_score: float, logic_score: float) -> bool:
    """True when Gemini's score is at most SCORE_TOLERANCE (0.01) from Logic's.

    The tiny allowance absorbs floating-point error, so a score exactly 0.01
    off (for example 4.63 against 4.64) is accepted, as the brief says.
    """
    return abs(gemini_score - logic_score) <= SCORE_TOLERANCE + 1e-9


def _answer_in_range(key: str, value: Any) -> bool:
    """True if value is a number Logic can score (sleep hours 0–14, else 1–5)."""
    number = _safe_float(value)
    if number is None:
        return False
    if key == "sleep_hours_avg":
        return SLEEP_HOURS_MIN <= number <= SLEEP_HOURS_MAX
    return SCALE_MIN <= number <= SCALE_MAX


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
