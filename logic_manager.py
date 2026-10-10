"""
DoNotStress — Logic Layer (logic_manager)

Post-AI finalizer. Gemini is mandatory for every record.

Logic decides the soft label from the student's answers, following the
team's evidence brief (donotstress_question_evidence.docx, 9 Oct 2026).
For evidence-v3 records, survey.py computes the 1–5 average stress score
(sleep hours are converted to that scale only when scoring) and applies
the documented project bands. Gemini contributes suggestions but cannot
replace those bands. If the AI step failed, Logic does not run.

The legacy path below preserves the team's logic for older 1–10 records,
including AI escalation and bounded tip lists.

Design
------
1. Require AI fields produced by Gemini (see REQUIRED_AI_FIELDS) and a
   usable stress_level.
2. Clamp present-but-invalid AI values onto I/O allow-lists
   (io_manager SOFT_LABELS / TIPS_ALLOWLIST keys / SPEAK_PROMINENCE).
3. Decide the label from the evidence brief's heuristic:
   a. Stress band — stress_level mapped onto the PSS-4 0–16 range:
      >= 12 "Please reach out", 8–11 "Worth a check-in", <= 7 "You're
      doing ok".
   b. Context flags — poor sleep, heavy workload, money worries, low
      support. Two or more raise the label one level, at most to
      "Worth a check-in". Flags alone never trigger "Please reach out".
   c. Safety override — crisis / self-harm language in feelings_text
      always gives "Please reach out". feelings_text is used for
      nothing else.
   d. Gemini's own soft_label may raise the result, never lower it.
4. Flags pick the tips shown first; Gemini's tips fill the rest.
5. Mark the result `source: "ai_logic"` (never `logic_fallback`).

The legacy path used single 1–10 questions. Its rescaled scores below are
approximations and must not be confused with actual PSS-4 totals. The current
website uses the revised items in survey.py and bypasses legacy thresholds.
All guidance bands are team heuristics, not clinical cut-offs or a diagnosis.

Pure procedural Python: functions only — no classes.
No terminal I/O (print / input), no Gemini / network, no file I/O.

Pipeline position:
  User → io_manager → ai_manager (must succeed) → logic_manager → data_manager
"""

from __future__ import annotations

import math
import survey
import re
from typing import Any


# ---------------------------------------------------------------------------
# Locked allow-lists — keys/strings must match io_manager (PR #6) and
# ai_manager (PR #8) so Flask formatters and Data Layer saves stay aligned.
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

RISK_CATEGORIES = ("Low", "Moderate", "High")
ALLOWED_RISK_CATEGORIES = frozenset(RISK_CATEGORIES)

# Tip IDs only — same keys as io_manager.TIPS_ALLOWLIST. Copy lives in I/O.
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

# Student answer the stress band is computed from. Without it Logic
# cannot decide a label, so the record is rejected rather than guessed.
REQUIRED_STUDENT_FIELDS = ("stress_level",)

# Gemini fields that must already be on the record. Matching ai_manager
# `_REQUIRED_FIELDS` except recommended_support (pass-through, unused here).
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

LOGIC_SOURCE = "ai_logic"
ERROR_AI_FIELDS_REQUIRED = "ai_fields_required"


# ---------------------------------------------------------------------------
# Domain settings - the team's numbers. Change them here and nowhere else.
# Cut-offs come from the evidence brief (Section 2, "Suggested labelling
# logic"). They are design heuristics, not clinical cut-offs: pilot them.
# The student scales (stress, workload, financial stress, support) run 1–10.
# ---------------------------------------------------------------------------

ANSWER_MIN = 1
ANSWER_MAX = 10

# Stress band. PSS-4 total runs 0–16 (Cohen et al., 1983). stress_level is
# mapped linearly onto that range: 1 -> 0, 10 -> 16. So stress_level >= 8
# reaches out, 6–7 checks in, <= 5 is ok.
PSS4_MAX = 16
PSS4_REACH_OUT_MIN = 12  # average answer "Fairly Often" or more
PSS4_CHECK_IN_MIN = 8  # average answer "Sometimes" or more

# Sleep flag. PSQI duration component >= 2 means under 6 hours
# (Buysse et al., 1989).
SLEEP_FLAG_BELOW_HOURS = 6.0

# Workload flag. PAS item on 1–5 agreement; >= 4 is "Agree" or stronger
# (Bedewy & Gabriel, 2015). academic_workload 1–10 is mapped onto 1–5,
# so academic_workload >= 8 raises the flag.
PAS_SCALE_MAX = 5
PAS_FLAG_MIN = 4

# Financial flag. IFDFW item 8 runs 1 = overwhelming stress to 10 = no
# stress (Prawitz et al., 2006); <= 4 is "High" to "Overwhelming".
# financial_stress runs the other way, so it is reversed (11 - x):
# financial_stress >= 7 raises the flag.
IFDFW_FLAG_MAX = 4

# Support flag. MSPSS mean on 1–7; below 3 is "low support"
# (Zimet et al., 1988). social_support 1–10 is mapped onto 1–7,
# so social_support <= 3 raises the flag.
MSPSS_SCALE_MAX = 7
MSPSS_FLAG_BELOW = 3

# Two or more flags raise the label one level, never past check-in.
FLAGS_TO_RAISE = 2

FLAG_SLEEP = "sleep"
FLAG_WORKLOAD = "workload"
FLAG_FINANCE = "finance"
FLAG_SUPPORT = "support"

# Crisis / self-harm phrases in feelings_text. Deliberately broad: a false
# alarm only shows support contacts, a miss could leave a student without
# them. Matched on lower-case text with straight apostrophes.
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

# Used only when the AI's own risk_category cannot be used: score -> category.
CATEGORY_HIGH_ABOVE = 0.75
CATEGORY_MODERATE_FROM = 0.40

_MAX_TIPS = 4

_LABEL_RANK = {
    SOFT_LABEL_OK: 0,
    SOFT_LABEL_CHECK_IN: 1,
    SOFT_LABEL_REACH_OUT: 2,
}
_PROMINENCE_RANK = {"low": 0, "medium": 1, "high": 2}
_CATEGORY_RANK = {"Low": 0, "Moderate": 1, "High": 2}

_CATEGORY_TO_LABEL = {
    "High": SOFT_LABEL_REACH_OUT,
    "Moderate": SOFT_LABEL_CHECK_IN,
    "Low": SOFT_LABEL_OK,
}
_CATEGORY_TO_PROMINENCE = {
    "High": "high",
    "Moderate": "medium",
    "Low": "low",
}

_LABEL_BY_RANK = {rank: label for label, rank in _LABEL_RANK.items()}
_LABEL_TO_PROMINENCE = {
    SOFT_LABEL_OK: "low",
    SOFT_LABEL_CHECK_IN: "medium",
    SOFT_LABEL_REACH_OUT: "high",
}
_LABEL_TO_CATEGORY = {
    SOFT_LABEL_OK: "Low",
    SOFT_LABEL_CHECK_IN: "Moderate",
    SOFT_LABEL_REACH_OUT: "High",
}

_TIP_TALK = "talk_to_someone"
_TIP_FEELINGS = "feelings_check_in"

# Flags drive which tips come first (brief: sleep tips, money resources,
# peer support, time management).
_FLAG_TIPS = {
    FLAG_SLEEP: "sleep_routine",
    FLAG_WORKLOAD: "workload_chunks",
    FLAG_FINANCE: "money_worries",
    FLAG_SUPPORT: "keep_social_contact",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def apply_logic(record: dict[str, Any]) -> dict[str, Any]:
    """
    Finalize an AI-enriched student record.

    Input MUST be a dict that already contains Gemini's fields
    (see REQUIRED_AI_FIELDS) and a usable stress_level.

    The label comes from the student's answers (stress band, context
    flags, crisis-language check); Gemini's soft_label can only raise it.

    On success, returns a shallow copy with the final outcome fields,
    `ok=True`, `source="ai_logic"`, `ai_ok=True`, plus audit fields:
      stress_score_pss4  stress_level on the PSS-4 0–16 range
      logic_flags        context flags raised, e.g. ["sleep", "finance"]
      crisis_language    True if feelings_text matched a crisis phrase
      logic_rule         step that set the final label
      logic_rules        every step that applied

    On missing or unusable AI fields or stress_level, returns an error:
      {"ok": False, "error": "ai_fields_required", "missing": [...], ...}

    Does not mutate the original dict.
    """
    if not isinstance(record, dict):
        return _error_result(
            {},
            missing=list(REQUIRED_AI_FIELDS + REQUIRED_STUDENT_FIELDS),
            invalid=["record"],
        )

    missing, invalid = _ai_field_problems(record)
    revised = record.get('survey_version') == survey.VERSION
    student_fields = (tuple(q['key'] for q in survey.QUESTIONS if not q.get('optional'))
                      if revised else REQUIRED_STUDENT_FIELDS)
    for key in student_fields:
        if key not in record:
            missing.append(key)
        elif _safe_float(record.get(key)) is None:
            invalid.append(key)
    if missing or invalid:
        return _error_result(record, missing=missing, invalid=invalid)

    if revised:
        # New questionnaire uses the documented deterministic rules; old /10
        # thresholds must never be applied to its different response scales.
        return survey.finalise(record)

    clamped, clamp_notes = _clamp_ai_fields(record)

    # a. Stress band from the student's own answer.
    stress_score = _stress_to_pss4(_safe_float(record.get("stress_level")))
    label = _stress_band_label(stress_score)
    deciding_rule = "stress_band"
    applied_rules = ["stress_band"]

    # b. Two or more context flags raise one level, never past check-in.
    flags = _context_flags(record)
    if (
        len(flags) >= FLAGS_TO_RAISE
        and _LABEL_RANK[label] < _LABEL_RANK[SOFT_LABEL_CHECK_IN]
    ):
        label = _LABEL_BY_RANK[_LABEL_RANK[label] + 1]
        deciding_rule = "context_flags"
        applied_rules.append("context_flags")

    # c. Safety override from crisis language in the free text.
    crisis = _has_crisis_language(record.get("feelings_text"))
    if crisis:
        label = SOFT_LABEL_REACH_OUT
        deciding_rule = "crisis_language"
        applied_rules.append("crisis_language")

    # d. Gemini may raise the label, never lower it.
    if _LABEL_RANK[clamped["soft_label"]] > _LABEL_RANK[label]:
        label = clamped["soft_label"]
        deciding_rule = "ai_raised"
        applied_rules.append("ai_raised")

    prominence = _higher(
        _PROMINENCE_RANK, _LABEL_TO_PROMINENCE[label], clamped["speak_prominence"]
    )
    category = _higher(
        _CATEGORY_RANK, _LABEL_TO_CATEGORY[label], clamped["risk_category"]
    )

    lead_tips: list[str] = []
    if label == SOFT_LABEL_REACH_OUT:
        lead_tips += [_TIP_TALK, _TIP_FEELINGS]
    lead_tips += [_FLAG_TIPS[flag] for flag in flags]
    tips = _ensure_tips(clamped["tips"], tuple(lead_tips))

    reasoning = (
        f"{clamped['reasoning']} Logic: stress {stress_score:.1f}/{PSS4_MAX} "
        f"(PSS-4 range); flags: {', '.join(flags) or 'none'}; "
        f"label set by {deciding_rule}."
    )

    enriched = dict(record)
    enriched.update({
        "ok": True,
        "error": None,
        "soft_label": label,
        "tips": tips,
        "speak_prominence": prominence,
        "risk_score": clamped["risk_score"],
        "risk_category": category,
        "primary_stressors": clamped["primary_stressors"],
        "reasoning": reasoning,
        "confidence": clamped["confidence"],
        "source": LOGIC_SOURCE,
        "ai_ok": True,
        "stress_score_pss4": round(stress_score, 2),
        "logic_flags": flags,
        "crisis_language": crisis,
        "logic_rule": deciding_rule,
        "logic_rules": applied_rules,
        "logic_clamp_notes": clamp_notes,
    })
    return enriched


def finalize_outcome(record: dict[str, Any]) -> dict[str, Any]:
    """Alias of apply_logic — finalize a Gemini-enriched record."""
    return apply_logic(record)


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
    result["ok"] = False
    result["error"] = ERROR_AI_FIELDS_REQUIRED
    result["missing"] = list(missing)
    result["invalid"] = list(invalid)
    result["message"] = (
        "Logic requires a successful Gemini (AI-enriched) record with a "
        "usable stress_level; it does not guess outcomes without them."
    )
    return result


def _ai_field_problems(record: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Return (missing keys, unusable-type keys). Values are clamped later."""
    missing: list[str] = []
    invalid: list[str] = []

    for key in REQUIRED_AI_FIELDS:
        if key not in record:
            missing.append(key)

    if "risk_score" in record and _as_unit_interval(record.get("risk_score")) is None:
        invalid.append("risk_score")
    if "confidence" in record and _as_unit_interval(record.get("confidence")) is None:
        invalid.append("confidence")
    if "risk_category" in record and not isinstance(record.get("risk_category"), str):
        invalid.append("risk_category")
    if "soft_label" in record and not isinstance(record.get("soft_label"), str):
        invalid.append("soft_label")
    if "speak_prominence" in record and not isinstance(record.get("speak_prominence"), str):
        invalid.append("speak_prominence")
    if "primary_stressors" in record and not isinstance(record.get("primary_stressors"), list):
        invalid.append("primary_stressors")
    if "tips" in record and not isinstance(record.get("tips"), list):
        invalid.append("tips")
    if "reasoning" in record:
        reasoning = record.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning.strip():
            invalid.append("reasoning")

    return missing, invalid


# ---------------------------------------------------------------------------
# Clamp AI values onto allow-lists (present but invalid → map, don't invent)
# ---------------------------------------------------------------------------

def _clamp_ai_fields(record: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    notes: list[str] = []
    risk_score = _as_unit_interval(record.get("risk_score"))
    confidence = _as_unit_interval(record.get("confidence"))
    assert risk_score is not None and confidence is not None

    category, category_clamped = _clamp_risk_category(
        record.get("risk_category"), risk_score
    )
    if category_clamped:
        notes.append("risk_category")

    label, label_clamped = _clamp_soft_label(record.get("soft_label"), category)
    if label_clamped:
        notes.append("soft_label")

    prominence, prominence_clamped = _clamp_speak_prominence(
        record.get("speak_prominence"), category
    )
    if prominence_clamped:
        notes.append("speak_prominence")

    tips, tips_clamped = _clamp_tips(record.get("tips"))
    if tips_clamped:
        notes.append("tips")

    stressors, stressors_clamped = _clamp_stressors(record.get("primary_stressors"))
    if stressors_clamped:
        notes.append("primary_stressors")

    reasoning = str(record.get("reasoning")).strip()

    return {
        "risk_score": risk_score,
        "confidence": confidence,
        "risk_category": category,
        "soft_label": label,
        "speak_prominence": prominence,
        "tips": tips,
        "primary_stressors": stressors,
        "reasoning": reasoning,
    }, notes


def _clamp_risk_category(value: Any, risk_score: float) -> tuple[str, bool]:
    if isinstance(value, str):
        text = value.strip()
        for cat in RISK_CATEGORIES:
            if text.lower() == cat.lower():
                return cat, text != cat
    return _score_to_category(risk_score), True


def _score_to_category(risk_score: float) -> str:
    if risk_score > CATEGORY_HIGH_ABOVE:
        return "High"
    if risk_score >= CATEGORY_MODERATE_FROM:
        return "Moderate"
    return "Low"


def _clamp_soft_label(value: Any, risk_category: str) -> tuple[str, bool]:
    if isinstance(value, str):
        mapped = _SOFT_LABEL_ALIASES.get(value.strip())
        if mapped is not None:
            return mapped, mapped != value
    fallback = _CATEGORY_TO_LABEL.get(risk_category, SOFT_LABEL_CHECK_IN)
    return fallback, True


def _clamp_speak_prominence(value: Any, risk_category: str) -> tuple[str, bool]:
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ALLOWED_SPEAK_PROMINENCE:
            return text, text != value
    fallback = _CATEGORY_TO_PROMINENCE.get(risk_category, "medium")
    return fallback, True


def _clamp_tips(value: Any) -> tuple[list[str], bool]:
    cleaned: list[str] = []
    dropped = False
    if not isinstance(value, list):
        return [], True
    for item in value:
        if not isinstance(item, str):
            dropped = True
            continue
        tip_id = item.strip()
        if tip_id in ALLOWED_TIP_IDS:
            if tip_id not in cleaned:
                cleaned.append(tip_id)
        else:
            dropped = True
    if len(cleaned) > _MAX_TIPS:
        cleaned = cleaned[:_MAX_TIPS]
        dropped = True
    return cleaned, dropped


def _clamp_stressors(value: Any) -> tuple[list[str], bool]:
    cleaned: list[str] = []
    dropped = False
    if not isinstance(value, list):
        return [], True
    for item in value:
        if not isinstance(item, str):
            dropped = True
            continue
        name = item.strip()
        if name in ALLOWED_PRIMARY_STRESSORS:
            if name not in cleaned:
                cleaned.append(name)
        else:
            dropped = True
    return cleaned, dropped


def _ensure_tips(tips: list[str], extra: tuple[str, ...]) -> list[str]:
    """Prepend rule-required allow-listed IDs; keep unique; cap at _MAX_TIPS."""
    ordered: list[str] = []
    for tip_id in list(extra) + list(tips):
        if tip_id in ALLOWED_TIP_IDS and tip_id not in ordered:
            ordered.append(tip_id)
    return ordered[:_MAX_TIPS]


def _higher(rank: dict[str, int], first: str, second: str) -> str:
    """Return whichever of two band values ranks higher (first on a tie)."""
    return second if rank.get(second, 0) > rank.get(first, 0) else first


# ---------------------------------------------------------------------------
# Scoring — the evidence brief's heuristic on the current 1–10 answers
# ---------------------------------------------------------------------------

def _answer(value: Any) -> float | None:
    """Return a 1–10 answer clamped into range, or None if unusable."""
    number = _safe_float(value)
    if number is None:
        return None
    return max(float(ANSWER_MIN), min(float(ANSWER_MAX), number))


def _rescale(answer: float, low: float, high: float) -> float:
    """Map a 1–10 answer linearly onto low..high (1 -> low, 10 -> high)."""
    fraction = (answer - ANSWER_MIN) / (ANSWER_MAX - ANSWER_MIN)
    return low + fraction * (high - low)


def _stress_to_pss4(stress_level: float) -> float:
    """stress_level 1–10 on the PSS-4 0–16 range (higher = more stress)."""
    return _rescale(_answer(stress_level), 0, PSS4_MAX)


def _stress_band_label(pss4_score: float) -> str:
    if pss4_score >= PSS4_REACH_OUT_MIN:
        return SOFT_LABEL_REACH_OUT
    if pss4_score >= PSS4_CHECK_IN_MIN:
        return SOFT_LABEL_CHECK_IN
    return SOFT_LABEL_OK


def _context_flags(record: dict[str, Any]) -> list[str]:
    """Return raised flags in a fixed order. Missing answers raise nothing."""
    flags: list[str] = []

    sleep = _safe_float(record.get("sleep_hours"))
    if sleep is not None and sleep < SLEEP_FLAG_BELOW_HOURS:
        flags.append(FLAG_SLEEP)

    workload = _answer(record.get("academic_workload"))
    if workload is not None and _rescale(workload, 1, PAS_SCALE_MAX) >= PAS_FLAG_MIN:
        flags.append(FLAG_WORKLOAD)

    financial = _answer(record.get("financial_stress"))
    if financial is not None and (ANSWER_MAX + ANSWER_MIN - financial) <= IFDFW_FLAG_MAX:
        flags.append(FLAG_FINANCE)

    support = _answer(record.get("social_support"))
    if support is not None and _rescale(support, 1, MSPSS_SCALE_MAX) < MSPSS_FLAG_BELOW:
        flags.append(FLAG_SUPPORT)

    return flags


def _has_crisis_language(text: Any) -> bool:
    if not isinstance(text, str) or not text.strip():
        return False
    normalized = text.lower().replace("’", "'").replace("‘", "'")
    normalized = " ".join(normalized.split())
    return any(pattern.search(normalized) for pattern in _CRISIS_PATTERNS)


# ---------------------------------------------------------------------------
# Numeric readers — missing/unparseable means the rule does not fire.
# No defaults: defaults would invent outcomes from incomplete inputs.
# ---------------------------------------------------------------------------

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
