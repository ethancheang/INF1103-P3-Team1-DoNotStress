"""DoNotStress — Logic Layer (logic_manager).

LogicManager checks Gemini's analysis against the answers and applies the
team's business rules. Gemini's result is the result: Logic recomputes the
score as an audit and never substitutes its own number.

The scoring formula, the verification used in the AI retry loop, and the
prompt instructions all live here. Tip capping is a finishing step on
Decision after the three policy rules run.

No terminal I/O, no Gemini calls, no file I/O, no student-facing copy.
"""

from __future__ import annotations

import math

from base_manager import BaseManager
from json_types import JSONObject, JSONValue
from logic.business_rule import BusinessRule
from logic.context_flag_rule import ContextFlagRule
from logic.decision import Decision
from logic.safety_override_rule import SafetyOverrideRule
from logic.support_priority_rule import SupportPriorityRule

# Scoring constants: the only place that knows how answers are scored.
SCALE_MIN: int = 1
SCALE_MAX: int = 5
ANSWER_KEYS: tuple[str, ...] = (
    "pss_1", "pss_2", "pss_3", "pss_4", "sleep_hours_avg",
    "sleep_quality", "pas_workload", "pas_catchup", "fin_stress",
    "mspss_friends", "mspss_family",
)
REVERSED_KEYS: tuple[str, ...] = (
    "pss_2", "pss_3", "mspss_friends", "mspss_family",
)
SUPPORT_KEYS: tuple[str, ...] = ("mspss_friends", "mspss_family")
SLEEP_KEY: str = "sleep_hours_avg"
SLEEP_HOURS_MIN: int = 0
SLEEP_HOURS_MAX: int = 14
SLEEP_HOUR_BANDS: tuple[tuple[int, int], ...] = (
    (8, 1), (7, 2), (6, 3), (5, 4),
)
SLEEP_HOURS_BELOW_ALL: int = 5
CHECK_IN_FROM: float = 2.5
REACH_OUT_ABOVE: float = 3.5
TOLERANCE: float = 0.01

CATEGORY_LABELS: dict[str, str] = {
    "Low": "You're doing ok",
    "Moderate": "Worth a check-in",
    "High": "Please reach out",
}
CATEGORY_PROMINENCE: dict[str, str] = {
    "Low": "low", "Moderate": "medium", "High": "high",
}
RECOMMENDED_SUPPORT: dict[str, str] = {
    "Low": "Continue healthy habits and routine self-care check-ins.",
    "Moderate": ("Consider short breaks, workload pacing, or talking with "
                 "someone you trust."),
    "High": ("Please reach out to SIT Counselling or someone you trust "
             "for support."),
}

FLAG_SLEEP: str = "sleep"
FLAG_WORKLOAD: str = "workload"
FLAG_FINANCES: str = "finances"
FLAG_SUPPORT: str = "support"
SLEEP_FLAG_BELOW_HOURS: float = 6
SLEEP_QUALITY_FLAG_MIN: float = 4
WORKLOAD_FLAG_MIN: float = 4
FINANCE_FLAG_MIN: float = 4
SUPPORT_FLAG_BELOW: float = 2.5

# Trend: comparison of the latest two scores, and a direction over a window.
TREND_SIMILAR_WITHIN: float = 0.25
TREND_WINDOW: int = 5
TREND_SLOPE_THRESHOLD: float = 0.1
TREND_MIN_FOR_DIRECTION: int = 3
TREND_NONE = "none"
TREND_FIRST = "first"
TREND_LOWER = "lower"
TREND_SIMILAR = "similar"
TREND_HIGHER = "higher"
TREND_NOT_ENOUGH = "not_enough"
TREND_EASING = "easing"
TREND_STEADY = "steady"
TREND_BUILDING = "building"


class LogicManager(BaseManager):
    """Audits Gemini's score, runs the business rules, and reads trends.

    The three policy rules are created here and belong to this manager
    (composition). A new policy is a new BusinessRule subclass; evaluate()
    itself does not change. After the rule loop, Decision.finalise_tips()
    caps the tip list at four.
    """

    SOURCE: str = "ai_logic"
    RULE_VERSION: str = "v3"
    ERROR_AI_FIELDS_REQUIRED: str = "ai_fields_required"
    ERROR_SCORE_MISMATCH: str = "score_mismatch"
    REQUIRED_AI_FIELDS: tuple[str, ...] = (
        "stress_score", "risk_category", "soft_label", "speak_prominence",
        "primary_stressors", "tips", "reasoning", "confidence",
    )

    def __init__(self, rules: tuple[BusinessRule, ...] | None = None) -> None:
        super().__init__("logic_manager")
        if rules is None:
            rules = (
                SafetyOverrideRule(),
                SupportPriorityRule(),
                ContextFlagRule(),
            )
        self.__rules: tuple[BusinessRule, ...] = tuple(rules)

    @property
    def rules(self) -> tuple[BusinessRule, ...]:
        return self.__rules

    @property
    def rule_names(self) -> list[str]:
        return [rule.name for rule in self.__rules]

    def describe(self) -> JSONObject:
        return {
            "rule_version": self.RULE_VERSION,
            "scale": f"{SCALE_MIN}-{SCALE_MAX}",
            "answer_count": len(ANSWER_KEYS),
            "tolerance": TOLERANCE,
            "rules": list(self.rule_names),
        }

    def instructions(self) -> str:
        """The formula and tiers, written as instructions for Gemini.

        App injects this into AIManager so the same rules appear in the
        prompt and in verify().
        """
        reversed_keys = ", ".join(REVERSED_KEYS)
        sleep_bands = ", ".join(
            f"{hours:g} or more{' hours' if index == 0 else ''} -> {value}"
            for index, (hours, value) in enumerate(SLEEP_HOUR_BANDS))
        low, middle, high = CATEGORY_LABELS.values()
        scale = f"{SCALE_MIN} to {SCALE_MAX}"
        return (
            f"Convert each answer onto the {scale} stress scale:\n"
            f"- {reversed_keys} are positively worded. Convert each as "
            f"{SCALE_MIN + SCALE_MAX} - answer.\n"
            f"- sleep_hours_avg is hours from {SLEEP_HOURS_MIN} to "
            f"{SLEEP_HOURS_MAX} in half-hour steps. Convert it as: "
            f"{sleep_bands}, otherwise {SLEEP_HOURS_BELOW_ALL}.\n"
            f"- Every other answer is already on the {scale} scale. Use "
            "the number as answered.\n"
            f"stress_score is the mean of those {len(ANSWER_KEYS)} "
            "converted values, rounded to 2 decimal places. Higher stress "
            "is worse.\n"
            "Then set the tier from that stress_score:\n"
            f"- below {CHECK_IN_FROM:g}: risk_category Low, soft_label "
            f'"{low}", speak_prominence low\n'
            f"- {CHECK_IN_FROM:g} to {REACH_OUT_ABOVE:g} "
            f'inclusive: risk_category Moderate, soft_label "{middle}", '
            "speak_prominence medium\n"
            f"- above {REACH_OUT_ABOVE:g}: risk_category High, "
            f'soft_label "{high}", speak_prominence high\n'
            "These bands are a simple guide for this check-in, not clinical "
            "cut-offs.\n"
        )

    def verify(self, ai_fields: JSONObject,
               answers: JSONObject) -> str | None:
        """Check Gemini's tier, converted items and mean. Never raises.

        In order: the tier fields match the tier of Gemini's own score;
        scored_items equal the converted answers exactly; stress_score is
        within 0.01 of their mean. Returns a problem or None. Used inside
        AIManager's retry loop.
        """
        if not isinstance(ai_fields, dict) or not isinstance(answers, dict):
            return "verify needs the AI fields and the answers as dicts."
        unusable = [key for key in ANSWER_KEYS
                    if not self.__scorable(key, answers.get(key))]
        if unusable:
            return (f"Cannot convert {', '.join(unusable)} onto the 1-5 "
                    "stress scale.")
        gemini_score = self.__number(ai_fields.get("stress_score"))
        if gemini_score is None:
            return "stress_score must be a number."
        expected = self.__category_for(gemini_score)
        if ai_fields.get("risk_category") != expected:
            return (f"risk_category must be {expected} for stress_score "
                    f"{gemini_score}.")
        if ai_fields.get("soft_label") != CATEGORY_LABELS[expected]:
            return "soft_label must match risk_category."
        if ai_fields.get("speak_prominence") != CATEGORY_PROMINENCE[expected]:
            return "speak_prominence must match risk_category."
        if ai_fields.get("scored_items") != self.__scored_items(answers):
            return "scored_items does not match the converted answers."
        logic_score = self.__mean_stress_score(answers)
        if not self.__within_tolerance(gemini_score, logic_score):
            return ("stress_score must match the mean of the 11 converted "
                    f"answers (expected {logic_score}).")
        return None

    def evaluate(self, record: JSONObject) -> JSONObject:
        """Validate Gemini's analysis and apply every business rule.

        The record must hold the 11 raw answers and Gemini's fields. On
        success the copy gains ok=True, source="ai_logic", the final tier
        and tips, logic_stress_score (audit only), logic_clamp_notes,
        support_priority, context_flags, support_mean, risk_score and
        recommended_support. On a problem it is an error dict with
        ok=False. feelings_text is always removed; the input is not
        changed.
        """
        if not isinstance(record, dict):
            return self.__error_result(
                {}, list(self.REQUIRED_AI_FIELDS + ANSWER_KEYS), ["record"])
        missing, invalid = self.__field_problems(record)
        if missing or invalid:
            return self.__error_result(record, missing, invalid)

        card = self.__score_answers(record)
        gemini_score = self.__number(record["stress_score"])
        if gemini_score is None:
            return self.__error_result(record, [], ["stress_score"])
        logic_score = float(card["stress_score"])  # type: ignore[arg-type]
        if not self.__within_tolerance(gemini_score, logic_score):
            return self.__mismatch_result(record, gemini_score, logic_score)

        flags = card["context_flags"]
        decision = Decision(record, flags)  # type: ignore[arg-type]
        for rule in self.__rules:
            rule.run(decision)
        decision.finalise_tips()

        result = self.__without_reflection(record)
        result.update({
            "ok": True,
            "error": None,
            "source": self.SOURCE,
            "ai_ok": True,
            "logic_rule": self.RULE_VERSION,
            "logic_stress_score": logic_score,
            "risk_score": self.__risk_score_for(gemini_score),
            "recommended_support": RECOMMENDED_SUPPORT[decision.risk_category],
            "risk_category": decision.risk_category,
            "soft_label": decision.soft_label,
            "speak_prominence": decision.speak_prominence,
            "tips": list(decision.tips),
            "logic_clamp_notes": list(decision.notes),
            "support_priority": decision.support_priority,
            "context_flags": dict(flags),  # type: ignore[arg-type]
            "support_mean": card["support_mean"],
        })
        return result

    def trend(self, history: JSONObject | list[JSONObject]) -> JSONObject:
        """How a student's scores are moving, from a history dict or record list.

        history is the dict DataManager.history_for() returns (scores,
        student_id, records, pending_count) or a list of record dicts.
        This never imports a history type from Data.
        """
        scores: list[float] = []
        raw_rows: list[ object ] | None = None
        if isinstance(history, dict):
            raw_scores = history.get("scores")
            if isinstance(raw_scores, list):
                for item in raw_scores:
                    number = self.__number(item)
                    if number is not None:
                        scores.append(round(number, 2))
            if not scores and isinstance(history.get("records"), list):
                raw_rows = history.get("records")  # type: ignore[assignment]
        elif isinstance(history, list):
            raw_rows = history
        if not scores and isinstance(raw_rows, list):
            for row in raw_rows:
                if not isinstance(row, dict):
                    continue
                if (row.get("pending") is True
                        or str(row.get("status") or "").lower() == "pending"):
                    continue
                number = self.__number(row.get("stress_score"))
                if number is not None:
                    scores.append(round(number, 2))
        if not scores:
            return {
                "comparison": TREND_NONE, "direction": TREND_NOT_ENOUGH,
                "latest": None, "previous": None, "change": None,
                "average": None, "count": 0,
            }
        average = round(sum(scores) / len(scores), 2)
        if len(scores) == 1:
            return {
                "comparison": TREND_FIRST, "direction": TREND_NOT_ENOUGH,
                "latest": scores[0], "previous": None, "change": None,
                "average": average, "count": 1,
            }
        latest, previous = scores[-1], scores[-2]
        return {
            "comparison": self.__compare(latest, previous),
            "direction": self.__direction(scores),
            "latest": latest, "previous": previous,
            "change": round(latest - previous, 2),
            "average": average, "count": len(scores),
        }

    def __scored_value(self, key: str, answer: float) -> float:
        """Sleep hours converted; positively worded items as 6 - answer."""
        if key == SLEEP_KEY:
            return self.__sleep_hours_stress(answer)
        if key in REVERSED_KEYS:
            return (SCALE_MIN + SCALE_MAX) - answer
        return answer

    def __sleep_hours_stress(self, hours: float) -> int:
        for at_least, value in SLEEP_HOUR_BANDS:
            if hours >= at_least:
                return value
        return SLEEP_HOURS_BELOW_ALL

    def __scored_items(self, answers: JSONObject) -> dict[str, int]:
        """The answers on the 1-5 stress scale: what Gemini must return."""
        return {key: int(self.__scored_value(key, self.__require_number(answers, key)))
                for key in ANSWER_KEYS}

    def __mean_stress_score(self, answers: JSONObject) -> float:
        items = self.__scored_items(answers)
        return round(sum(items.values()) / len(items), 2)

    def __category_for(self, stress_score: float) -> str:
        if stress_score > REACH_OUT_ABOVE:
            return "High"
        if stress_score >= CHECK_IN_FROM:
            return "Moderate"
        return "Low"

    def __risk_score_for(self, stress_score: float) -> float:
        """The 1-5 score mapped onto 0-1."""
        return (stress_score - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)

    def __within_tolerance(self, gemini_score: float,
                           logic_score: float) -> bool:
        """True when Gemini is at most 0.01 away from Logic."""
        return abs(gemini_score - logic_score) <= TOLERANCE + 1e-9

    def __context_flags(self, answers: JSONObject,
                        support_mean: float | None = None) -> dict[str, bool]:
        if support_mean is None:
            support = [self.__require_number(answers, key)
                       for key in SUPPORT_KEYS]
            support_mean = round(sum(support) / len(support), 2)
        sleep_short = (self.__require_number(answers, SLEEP_KEY)
                       < SLEEP_FLAG_BELOW_HOURS)
        sleep_poor = (self.__require_number(answers, "sleep_quality")
                      >= SLEEP_QUALITY_FLAG_MIN)
        return {
            FLAG_SLEEP: sleep_short or sleep_poor,
            FLAG_WORKLOAD: (self.__require_number(answers, "pas_workload")
                            >= WORKLOAD_FLAG_MIN),
            FLAG_FINANCES: (self.__require_number(answers, "fin_stress")
                            >= FINANCE_FLAG_MIN),
            FLAG_SUPPORT: support_mean < SUPPORT_FLAG_BELOW,
        }

    def __support_mean(self, answers: JSONObject) -> float:
        support = [self.__require_number(answers, key) for key in SUPPORT_KEYS]
        return round(sum(support) / len(support), 2)

    def __score_answers(self, answers: JSONObject) -> JSONObject:
        """The audit card: mean, items, flags, support mean and tier."""
        items = self.__scored_items(answers)
        stress = round(sum(items.values()) / len(items), 2)
        support = self.__support_mean(answers)
        return {
            "stress_score": stress,
            "scored_items": items,
            "support_mean": support,
            "risk_category": self.__category_for(stress),
            "context_flags": self.__context_flags(answers, support),
        }

    def __answer_in_range(self, key: str, value: JSONValue) -> bool:
        number = self.__number(value)
        if number is None:
            return False
        if key == SLEEP_KEY:
            return SLEEP_HOURS_MIN <= number <= SLEEP_HOURS_MAX
        return SCALE_MIN <= number <= SCALE_MAX

    def __field_problems(self, record: JSONObject
                         ) -> tuple[list[str], list[str]]:
        needed = self.REQUIRED_AI_FIELDS + ANSWER_KEYS
        missing = [key for key in needed if key not in record]
        numbers = ("stress_score",) + ANSWER_KEYS
        invalid = [key for key in numbers if key in record and
                   not self.__answer_in_range(key, record[key])]
        invalid += [key for key in ("tips", "primary_stressors")
                    if key in record and not isinstance(record[key], list)]
        return missing, invalid

    def __error_result(self, record: JSONObject, missing: list[str],
                       invalid: list[str]) -> JSONObject:
        result = self.__without_reflection(record)
        result.update({
            "ok": False,
            "error": self.ERROR_AI_FIELDS_REQUIRED,
            "missing": list(missing),
            "invalid": list(invalid),
            "message": ("Logic requires a successful Gemini (AI-enriched) "
                        "record and all 11 answers; it does not guess "
                        "outcomes without them."),
        })
        return result

    def __mismatch_result(self, record: JSONObject, gemini_score: float,
                          logic_score: float) -> JSONObject:
        result = self.__without_reflection(record)
        result.update({
            "ok": False,
            "error": self.ERROR_SCORE_MISMATCH,
            "logic_stress_score": logic_score,
            "message": (f"Gemini stress_score {gemini_score:g} does not "
                        f"match the answers ({logic_score:g}); no result "
                        "is given."),
        })
        return result

    def __without_reflection(self, record: JSONObject) -> JSONObject:
        return {key: value for key, value in record.items()
                if key not in ("feelings_text", "reflection")}

    def __compare(self, latest: float, previous: float) -> str:
        change = latest - previous
        if abs(change) <= TREND_SIMILAR_WITHIN:
            return TREND_SIMILAR
        return TREND_LOWER if change < 0 else TREND_HIGHER

    def __direction(self, scores: list[float]) -> str:
        if len(scores) < TREND_MIN_FOR_DIRECTION:
            return TREND_NOT_ENOUGH
        recent = scores[-TREND_WINDOW:]
        slope = self.__slope(recent)
        if slope < -TREND_SLOPE_THRESHOLD:
            return TREND_EASING
        if slope > TREND_SLOPE_THRESHOLD:
            return TREND_BUILDING
        return TREND_STEADY

    def __slope(self, values: list[float]) -> float:
        count = len(values)
        mean_x = (count - 1) / 2
        mean_y = sum(values) / count
        spread = sum((index - mean_x) ** 2 for index in range(count))
        return sum((index - mean_x) * (value - mean_y)
                   for index, value in enumerate(values)) / spread

    def __number(self, value: JSONValue) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return None
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def __scorable(self, key: str, value: JSONValue) -> bool:
        number = self.__number(value)
        if number is None or not self.__answer_in_range(key, value):
            return False
        return key == SLEEP_KEY or number.is_integer()

    def __require_number(self, answers: JSONObject, key: str) -> float:
        number = self.__number(answers.get(key))
        if number is None:
            raise ValueError(f"{key} is not a usable answer.")
        return number
