"""
DoNotStress — Logic Layer (logic_manager)

Post-AI validator. Gemini is mandatory for every record.

LogicManager takes Gemini's analysis (from ai_manager.analyse_student,
already schema-checked) as the result. It recomputes the deterministic
stress score from the 11 raw answers as an audit and never substitutes its
own score. It does not re-validate Gemini's schema; ai_manager owns that.

LogicManager is the only class that knows the scoring rules. main.py hands
two of its methods to ai_manager, so ai_manager itself holds no domain
logic:
  instructions()  the formula and tier text for the Gemini prompt
  verify()        checks Gemini's arithmetic and tier before the reply is
                  accepted (a failure is retried like any other invalid
                  AI response)

Rules (logic_rule "v3")
-----------------------
1. Score — mean of the 11 answers on the 1–5 stress scale, equal weight.
   pss_2, pss_3, mspss_friends and mspss_family are positively worded and
   scored as 6 - answer. sleep_hours_avg is converted: 8+ h -> 1,
   7 to <8 -> 2, 6 to <7 -> 3, 5 to <6 -> 4, under 5 -> 5.
2. Cross-check — if Gemini's stress_score is within 0.01 of the logic
   score (the same tolerance verify() uses), Gemini's score, tier, tips,
   stressors and reasoning are kept. Otherwise evaluate() returns a
   "score_mismatch" error dict and the caller treats the check-in as an AI
   failure (saved as pending, no result).
3. Business rules — evaluate() runs each BusinessRule on one Decision, in
   order: SafetyOverrideRule, SupportPriorityRule, ContextFlagRule. Then
   Decision.finalise_tips() puts the lead tip first, keeps all of Gemini's
   tips and adds suggested tips while there is room (max 4). A new rule is
   a new BusinessRule subclass; evaluate() does not change.

Tiers: Low below 2.5, Moderate 2.5 to 3.5 inclusive, High above 3.5.
These bands are team heuristics, not clinical cut-offs or a diagnosis.

The numbers and wording tables below are module-level data so they can be
changed in one place. No terminal I/O (print / input), no Gemini / network,
no file I/O.

Pipeline position:
  User → io_manager → ai_manager (must succeed) → LogicManager → data_manager
"""

from __future__ import annotations

import math
from typing import Any

from base_manager import BaseManager
from logic.business_rule import BusinessRule
from logic.context_flag_rule import ContextFlagRule
from logic.decision import Decision
from logic.safety_override_rule import SafetyOverrideRule
from logic.support_priority_rule import SupportPriorityRule


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

# The tip list is capped by Decision.finalise_tips(); this is the same cap.
MAX_TIPS = Decision.MAX_TIPS

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

# Trend over a student's past check-ins. A guide, not a diagnosis.
TREND_SIMILAR_WITHIN = 0.25    # scores this close count as about the same
TREND_WINDOW = 5               # direction uses the last five scores
TREND_SLOPE_THRESHOLD = 0.1    # change per check-in that counts as moving
TREND_MIN_FOR_DIRECTION = 3

TREND_NONE = "none"
TREND_FIRST = "first"
TREND_LOWER = "lower"
TREND_SIMILAR = "similar"
TREND_HIGHER = "higher"
TREND_NOT_ENOUGH = "not_enough"
TREND_EASING = "easing"
TREND_STEADY = "steady"
TREND_BUILDING = "building"

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


class LogicManager(BaseManager):
    """Audits Gemini's score, runs the business rules, and reads trends.

    The three policy rules are created here and belong to this manager
    (composition). Pass a different tuple of rules to change the policy
    without editing evaluate().
    """

    def __init__(self, rules: tuple[BusinessRule, ...] | None = None) -> None:
        super().__init__("logic_manager")
        if rules is None:
            rules = (SafetyOverrideRule(), SupportPriorityRule(),
                     ContextFlagRule())
        self.__rules: tuple[BusinessRule, ...] = tuple(rules)
        self.__support_rule: SupportPriorityRule = SupportPriorityRule()

    @property
    def rules(self) -> tuple[BusinessRule, ...]:
        return self.__rules

    def describe(self) -> dict[str, Any]:
        """Rule version, scale, tolerance and rule names. No secrets."""
        return {
            "rule_version": LOGIC_RULE,
            "scale": f"{SCALE_MIN}-{SCALE_MAX}",
            "answer_count": len(ANSWER_KEYS),
            "tolerance": SCORE_TOLERANCE,
            "rules": [rule.name for rule in self.__rules],
        }

    # --- Full pipeline ------------------------------------------------------

    def evaluate(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Validate Gemini's analysis against the student's answers and run
        every business rule.

        Input MUST be a dict holding the 11 raw answers and Gemini's fields
        (see REQUIRED_AI_FIELDS). Gemini's result is kept when its
        stress_score matches the deterministic score within 0.01.

        On success, returns a shallow copy with ok=True, source="ai_logic",
        ai_ok=True, logic_rule="v3", the final outcome fields, plus:
          logic_stress_score  the deterministic 1–5 average (audit only)
          logic_clamp_notes   why a rule changed anything (empty if nothing)
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
        problem = self.__audit(record)
        if problem is not None:
            return problem

        scores = self.score_answers(record)
        gemini_score = self.__number(record["stress_score"])
        flags = scores["context_flags"]
        decision = Decision(record, flags)
        for rule in self.__rules:
            rule.run(decision)
        decision.finalise_tips()

        enriched = dict(record)
        enriched.pop("feelings_text", None)
        enriched.update({
            "ok": True,
            "error": None,
            "source": LOGIC_SOURCE,
            "ai_ok": True,
            "logic_rule": LOGIC_RULE,
            "stress_score": record["stress_score"],
            "logic_stress_score": scores["stress_score"],
            "risk_score": self.risk_score_for(gemini_score),
            "recommended_support": RECOMMENDED_SUPPORT[decision.risk_category],
            "risk_category": decision.risk_category,
            "soft_label": decision.soft_label,
            "speak_prominence": decision.speak_prominence,
            "tips": decision.tips,
            "primary_stressors": list(record["primary_stressors"]),
            "reasoning": record["reasoning"],
            "logic_clamp_notes": decision.notes,
            "support_priority": decision.support_priority,
            "context_flags": flags,
            "support_mean": scores["support_mean"],
            "factor_insights": self.factor_insights(record, scores),
        })
        return enriched

    def score(self, record: dict[str, Any]) -> float | None:
        """Gemini's stress_score once the formula confirms it, else None.

        Only the formula check runs here (fields present, score within
        0.01); the business rules are evaluate()'s job. Logic never
        substitutes its own number.
        """
        if self.__audit(record) is not None:
            return None
        return float(record["stress_score"])

    def route(self, record: dict[str, Any]) -> str:
        """Return the outcome path: "Low", "Moderate", "High", or "unavailable".

        Routes on the final risk_category only when the soft_label agrees
        with it, otherwise "unavailable". Pass the dict evaluate() returned.
        """
        if not isinstance(record, dict) or not record.get("ok"):
            return "unavailable"
        category = record.get("risk_category")
        if (category in _CATEGORY_TO_LABEL
                and record.get("soft_label") == _CATEGORY_TO_LABEL[category]):
            return category
        return "unavailable"

    # --- Handed to ai_manager -----------------------------------------------

    def instructions(self) -> str:
        """The scoring formula and tier rules, written as instructions for Gemini.

        Built from this module's constants, so the prompt always matches
        the rules verify() checks.
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

    def verify(self, ai_fields: dict[str, Any], answers: dict[str, Any]) -> str | None:
        """Check Gemini's arithmetic and tier against the student's answers.

        main.py passes this to ai_manager, which treats any message as an
        invalid AI response and retries. Checks, in order:
          1. risk_category, soft_label and speak_prominence match the tier
             of Gemini's stress_score
          2. scored_items equal the converted answers exactly
          3. stress_score is within 0.01 of the mean of those items

        Returns an error message, or None when everything matches. Never raises.
        """
        if not isinstance(ai_fields, dict) or not isinstance(answers, dict):
            return "verify needs the AI fields and the answers as dicts."
        unusable = [
            key for key in ANSWER_KEYS
            if key not in answers
            or not self.__answer_in_range(key, answers[key])
            or (key != "sleep_hours_avg" and not float(answers[key]).is_integer())
        ]
        if unusable:
            return f"Cannot convert {', '.join(unusable)} onto the 1-5 stress scale."
        gemini_score = self.__number(ai_fields.get("stress_score"))
        if gemini_score is None:
            return "stress_score must be a number."

        expected_category = self.category_for_score(gemini_score)
        if ai_fields.get("risk_category") != expected_category:
            return f"risk_category must be {expected_category} for stress_score {gemini_score}."
        if ai_fields.get("soft_label") != _CATEGORY_TO_LABEL[expected_category]:
            return "soft_label must match risk_category."
        if ai_fields.get("speak_prominence") != _CATEGORY_TO_PROMINENCE[expected_category]:
            return "speak_prominence must match risk_category."

        if ai_fields.get("scored_items") != self.scored_items(answers):
            return "scored_items does not match the converted answers."
        expected_score = self.score_answers(answers)["stress_score"]
        if not self.within_tolerance(gemini_score, expected_score):
            return (
                "stress_score must match the mean of the 11 converted answers "
                f"(expected {expected_score})."
            )
        return None

    # --- The formula --------------------------------------------------------

    def score_answers(self, record: dict[str, Any]) -> dict[str, Any]:
        """
        Deterministic score of the 11 answers. Caller must pass usable numbers.

        Returns stress_score (1.0–5.0, 2 dp), the tier it falls in, the
        support mean and the four context flags.
        """
        items = [self.scored_value(key, self.__number(record[key])) for key in ANSWER_KEYS]
        average = round(sum(items) / len(items), 2)
        support = [self.__number(record[key]) for key in SUPPORT_KEYS]
        support_mean = round(sum(support) / len(support), 2)
        category = self.category_for_score(average)
        return {
            "stress_score": average,
            "scored_item_count": len(items),
            "support_mean": support_mean,
            "support_item_count": len(support),
            "risk_category": category,
            "soft_label": _CATEGORY_TO_LABEL[category],
            "speak_prominence": _CATEGORY_TO_PROMINENCE[category],
            "context_flags": self.context_flags(record, support_mean),
        }

    def scored_items(self, answers: dict[str, Any]) -> dict[str, int]:
        """The 11 answers converted onto the 1–5 stress scale.

        This is exactly what Gemini must return as scored_items. Caller must
        pass usable answers (see verify).
        """
        return {key: int(self.scored_value(key, self.__number(answers[key])))
                for key in ANSWER_KEYS}

    def scored_value(self, key: str, answer: float) -> float:
        """Stress-direction value: sleep hours converted, positive items 6 - answer."""
        if key == "sleep_hours_avg":
            return self.sleep_hours_stress(answer)
        if key in REVERSED_KEYS:
            return (SCALE_MIN + SCALE_MAX) - answer
        return answer

    def sleep_hours_stress(self, hours: float) -> int:
        """Map typical nightly hours onto the 1–5 stress scale. Scoring only."""
        for at_least, value in SLEEP_HOUR_BANDS:
            if hours >= at_least:
                return value
        return SLEEP_HOURS_BELOW_ALL

    def category_for_score(self, stress_score: float) -> str:
        """Low below 2.5, Moderate 2.5 to 3.5 inclusive, High above 3.5."""
        if stress_score > REACH_OUT_ABOVE:
            return "High"
        if stress_score >= CHECK_IN_FROM:
            return "Moderate"
        return "Low"

    def risk_score_for(self, stress_score: float) -> float:
        """Map the 1–5 stress score onto 0–1. Kept for compatibility; not a probability."""
        return (stress_score - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)

    def within_tolerance(self, gemini_score: float, logic_score: float) -> bool:
        """True when Gemini's score is at most SCORE_TOLERANCE (0.01) from Logic's.

        The tiny allowance absorbs floating-point error, so a score exactly
        0.01 off (for example 4.63 against 4.64) is accepted, as the brief says.
        """
        return abs(gemini_score - logic_score) <= SCORE_TOLERANCE + 1e-9

    def context_flags(self, record: dict[str, Any], support_mean: float) -> dict[str, bool]:
        """The four context flags from the raw answers."""
        return {
            FLAG_SLEEP: (
                self.__number(record["sleep_hours_avg"]) < SLEEP_FLAG_BELOW_HOURS
                or self.__number(record["sleep_quality"]) >= SLEEP_QUALITY_FLAG_MIN
            ),
            FLAG_WORKLOAD: self.__number(record["pas_workload"]) >= WORKLOAD_FLAG_MIN,
            FLAG_FINANCES: self.__number(record["fin_stress"]) >= FINANCE_FLAG_MIN,
            FLAG_SUPPORT: support_mean < SUPPORT_FLAG_BELOW,
        }

    def needs_support_priority(self, record: dict[str, Any]) -> bool:
        """True when Gemini rated the check-in High AND named low social support.

        Asks SupportPriorityRule, so the condition is written only once.
        """
        if not isinstance(record, dict):
            return False
        return self.__support_rule.applies(Decision(record, {}))

    # --- Trend --------------------------------------------------------------

    def trend(self, records: list[dict[str, Any]]) -> dict[str, Any]:
        """How a student's stress scores are moving, from their saved check-ins.

        records is a list of plain check-in dicts. They are put in saved_at
        order (oldest first); pending check-ins and rows without a numeric
        stress_score are skipped. Returns a plain dict:
          comparison  "none", "first", or "lower" / "similar" / "higher" than
                      the previous score (within 0.25 counts as similar)
          direction   "not_enough" (under three scores), or "easing" /
                      "steady" / "building" from the least-squares slope of
                      the last five scores
          latest, previous, change, average  (None when there are too few)
        Lower stress is better. Never raises on odd input.
        """
        rows = [row for row in records if isinstance(row, dict)] if isinstance(records, list) else []
        rows.sort(key=lambda row: str(row.get("saved_at") or ""))
        scores = [
            float(row["stress_score"]) for row in rows
            if row.get("status") != "pending"
            and isinstance(row.get("stress_score"), (int, float))
            and not isinstance(row.get("stress_score"), bool)
        ]
        result: dict[str, Any] = {
            "comparison": TREND_NONE, "direction": TREND_NOT_ENOUGH,
            "latest": None, "previous": None, "change": None, "average": None,
        }
        if not scores:
            return result
        result["average"] = round(sum(scores) / len(scores), 2)
        result["latest"] = scores[-1]
        if len(scores) == 1:
            result["comparison"] = TREND_FIRST
            return result
        latest, previous = scores[-1], scores[-2]
        change = latest - previous
        if abs(change) <= TREND_SIMILAR_WITHIN:
            result["comparison"] = TREND_SIMILAR
        else:
            result["comparison"] = TREND_LOWER if change < 0 else TREND_HIGHER
        result["previous"] = previous
        result["change"] = round(change, 2)
        result["direction"] = self.__trend_direction(scores)
        return result

    # --- Result page --------------------------------------------------------

    def factor_insights(self, record: dict[str, Any], scores: dict[str, Any]) -> list[dict[str, Any]]:
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
                    f"{self.__number(record['sleep_hours_avg']):g} hours · "
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

    # --- Private helpers ----------------------------------------------------

    def __audit(self, record: Any) -> dict[str, Any] | None:
        """An error dict if the record is unusable or Gemini's score is off, else None."""
        if not isinstance(record, dict):
            return self.__error_result(
                {},
                missing=list(REQUIRED_AI_FIELDS + ANSWER_KEYS),
                invalid=["record"],
            )
        missing, invalid = self.__field_problems(record)
        if missing or invalid:
            return self.__error_result(record, missing=missing, invalid=invalid)
        logic_score = self.score_answers(record)["stress_score"]
        gemini_score = self.__number(record["stress_score"])
        # Cross-check only: Logic never substitutes its own score.
        if not self.within_tolerance(gemini_score, logic_score):
            return self.__score_mismatch_result(record, gemini_score, logic_score)
        return None

    def __error_result(
        self,
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

    def __score_mismatch_result(
        self,
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

    def __field_problems(self, record: dict[str, Any]) -> tuple[list[str], list[str]]:
        """
        Return (missing keys, unusable keys).

        Only checks that fields exist and that numbers Logic computes with are
        numbers. Gemini's schema is ai_manager's job.
        """
        missing = [key for key in REQUIRED_AI_FIELDS + ANSWER_KEYS if key not in record]
        invalid = [
            key for key in ("stress_score",) + ANSWER_KEYS
            if key in record and not self.__answer_in_range(key, record[key])
        ]
        for key in ("tips", "primary_stressors"):
            if key in record and not isinstance(record[key], list):
                invalid.append(key)
        return missing, invalid

    def __trend_direction(self, scores: list[float]) -> str:
        """Easing, steady or building, from the slope of the recent scores."""
        if len(scores) < TREND_MIN_FOR_DIRECTION:
            return TREND_NOT_ENOUGH
        recent = scores[-TREND_WINDOW:]
        count = len(recent)
        mean_x = (count - 1) / 2
        mean_y = sum(recent) / count
        spread = sum((index - mean_x) ** 2 for index in range(count))
        slope = sum((index - mean_x) * (value - mean_y)
                    for index, value in enumerate(recent)) / spread
        if slope < -TREND_SLOPE_THRESHOLD:
            return TREND_EASING
        if slope > TREND_SLOPE_THRESHOLD:
            return TREND_BUILDING
        return TREND_STEADY

    def __answer_in_range(self, key: str, value: Any) -> bool:
        """True if value is a number Logic can score (sleep hours 0–14, else 1–5)."""
        number = self.__number(value)
        if number is None:
            return False
        if key == "sleep_hours_avg":
            return SLEEP_HOURS_MIN <= number <= SLEEP_HOURS_MAX
        return SCALE_MIN <= number <= SCALE_MAX

    def __number(self, value: Any) -> float | None:
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
