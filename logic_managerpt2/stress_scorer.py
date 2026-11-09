"""The scoring formula: the only place that knows how answers are scored."""

from __future__ import annotations

from ai.score_auditor import ScoreAuditor
from json_types import JSONObject
from logic.answer_reader import AnswerReader
from logic.context_flag import ContextFlag
from logic.high_answer_flag import HighAnswerFlag
from logic.score_card import ScoreCard
from logic.sleep_flag import SleepFlag
from logic.support_flag import SupportFlag
from logic.tier_table import TierTable

# Checked by Zhung Yi - 9/11/2026 7.30pm


class StressScorer(ScoreAuditor):
    """Scores the 11 answers and audits Gemini's arithmetic.

    Score: the mean of the 11 answers on the 1-5 stress scale, equal
    weight. Positively worded items are scored as 6 - answer. Sleep hours
    convert as 8+ h -> 1, 7 to <8 -> 2, 6 to <7 -> 3, 5 to <6 -> 4, under
    5 -> 5. The tier comes from TierTable.

    The answer reader, the tier table and the context flags are created
    here and belong to this scorer (composition). LogicManager lends the
    scorer to AIManager as its ScoreAuditor.
    """

    ANSWER_KEYS: tuple[str, ...] = (
        "pss_1", "pss_2", "pss_3", "pss_4", "sleep_hours_avg",
        "sleep_quality", "pas_workload", "pas_catchup", "fin_stress",
        "mspss_friends", "mspss_family",
    )
    REVERSED_KEYS: tuple[str, ...] = (
        "pss_2", "pss_3", "mspss_friends", "mspss_family")
    SUPPORT_KEYS: tuple[str, ...] = ("mspss_friends", "mspss_family")
    SLEEP_HOUR_BANDS: tuple[tuple[int, int], ...] = (
        (8, 1), (7, 2), (6, 3), (5, 4))
    SLEEP_HOURS_BELOW_ALL: int = 5
    TOLERANCE: float = 0.01

    def __init__(self) -> None:
        self.__reader: AnswerReader = AnswerReader()
        self.__tiers: TierTable = TierTable()
        self.__flags: list[ContextFlag] = [
            SleepFlag(),
            HighAnswerFlag("workload", "pas_workload", 4, "workload_chunks"),
            HighAnswerFlag("finances", "fin_stress", 4, "money_worries"),
            SupportFlag(),
        ]

    @property
    def flags(self) -> list[ContextFlag]:
        """The context flags, in the order their tips are suggested."""
        return list(self.__flags)

    def score(self, answers: JSONObject) -> ScoreCard:
        """Score usable answers. Raises ValueError for an unusable one."""
        items = self.scored_items(answers)
        stress = round(sum(items.values()) / len(items), 2)
        numbers = {key: self.__reader.read(answers, key)
                   for key in self.ANSWER_KEYS}
        support = [numbers[key] for key in self.SUPPORT_KEYS]
        support_mean = round(sum(support) / len(support), 2)
        flags = {flag.name: flag.raised(numbers, support_mean)
                 for flag in self.__flags}
        return ScoreCard(stress, items, support_mean,
                         self.category_for(stress), flags)

    def scored_items(self, answers: JSONObject) -> dict[str, int]:
        """The answers on the 1-5 stress scale: what Gemini must return."""
        return {key: int(self.scored_value(
                    key, self.__reader.read(answers, key)))
                for key in self.ANSWER_KEYS}

    def scored_value(self, key: str, answer: float) -> float:
        """Sleep hours converted; positively worded items as 6 - answer."""
        if key == AnswerReader.SLEEP_KEY:
            return self.sleep_hours_stress(answer)
        if key in self.REVERSED_KEYS:
            return (AnswerReader.SCALE_MIN + AnswerReader.SCALE_MAX) - answer
        return answer

    def sleep_hours_stress(self, hours: float) -> int:
        """Sleep hours on the 1-5 stress scale (more sleep, less stress)."""
        for at_least, value in self.SLEEP_HOUR_BANDS:
            if hours >= at_least:
                return value
        return self.SLEEP_HOURS_BELOW_ALL

    def category_for(self, stress_score: float) -> str:
        return self.__tiers.category_for(stress_score)

    def label_for(self, category: str) -> str:
        return self.__tiers.label_for(category)

    def prominence_for(self, category: str) -> str:
        return self.__tiers.prominence_for(category)

    def risk_score_for(self, stress_score: float) -> float:
        """The 1-5 score mapped onto 0-1. Kept for compatibility."""
        return ((stress_score - AnswerReader.SCALE_MIN)
                / (AnswerReader.SCALE_MAX - AnswerReader.SCALE_MIN))

    def within_tolerance(self, gemini_score: float,
                         logic_score: float) -> bool:
        """True when Gemini is at most 0.01 away from Logic.

        The tiny extra allowance absorbs float error, so exactly 0.01 off
        (for example 4.63 against 4.64) is accepted.
        """
        return abs(gemini_score - logic_score) <= self.TOLERANCE + 1e-9

    def instructions(self) -> str:
        """The formula and tiers, written as instructions for Gemini."""
        reversed_keys = ", ".join(self.REVERSED_KEYS)
        sleep_bands = ", ".join(
            f"{hours:g} or more{' hours' if index == 0 else ''} -> {value}"
            for index, (hours, value) in enumerate(self.SLEEP_HOUR_BANDS))
        low = self.label_for(TierTable.LOW)
        middle = self.label_for(TierTable.MODERATE)
        high = self.label_for(TierTable.HIGH)
        scale_min, scale_max = AnswerReader.SCALE_MIN, AnswerReader.SCALE_MAX
        scale = f"{scale_min} to {scale_max}"
        check_in = TierTable.CHECK_IN_FROM
        reach_out = TierTable.REACH_OUT_ABOVE
        return (
            f"Convert each answer onto the {scale} stress scale:\n"
            f"- {reversed_keys} are positively worded. Convert each as "
            f"{scale_min + scale_max} - answer.\n"
            f"- sleep_hours_avg is hours from {AnswerReader.SLEEP_HOURS_MIN} "
            f"to {AnswerReader.SLEEP_HOURS_MAX} in half-hour steps. Convert "
            f"it as: {sleep_bands}, otherwise {self.SLEEP_HOURS_BELOW_ALL}.\n"
            f"- Every other answer is already on the {scale} scale. Use "
            "the number as answered.\n"
            f"stress_score is the mean of those {len(self.ANSWER_KEYS)} "
            "converted values, rounded to 2 decimal places. Higher stress "
            "is worse.\n"
            "Then set the tier from that stress_score:\n"
            f"- below {check_in:g}: risk_category {TierTable.LOW}, "
            f'soft_label "{low}", speak_prominence '
            f"{self.prominence_for(TierTable.LOW)}\n"
            f"- {check_in:g} to {reach_out:g} inclusive: risk_category "
            f'{TierTable.MODERATE}, soft_label "{middle}", speak_prominence '
            f"{self.prominence_for(TierTable.MODERATE)}\n"
            f"- above {reach_out:g}: risk_category {TierTable.HIGH}, "
            f'soft_label "{high}", speak_prominence '
            f"{self.prominence_for(TierTable.HIGH)}\n"
            "These bands are a simple guide for this check-in, not clinical "
            "cut-offs.\n"
        )

    def verify(self, ai_fields: JSONObject,
               answers: JSONObject) -> str | None:
        """Check Gemini's tier, converted items and mean. Never raises.

        In order: the tier fields match the tier of Gemini's own score;
        scored_items equal the converted answers exactly; stress_score is
        within 0.01 of their mean. Returns a problem or None.
        """
        if not isinstance(ai_fields, dict) or not isinstance(answers, dict):
            return "verify needs the AI fields and the answers as dicts."
        unusable = [key for key in self.ANSWER_KEYS
                    if not self.__reader.scorable(key, answers.get(key))]
        if unusable:
            return (f"Cannot convert {', '.join(unusable)} onto the 1-5 "
                    "stress scale.")
        gemini_score = self.__reader.number(ai_fields.get("stress_score"))
        if gemini_score is None:
            return "stress_score must be a number."
        expected = self.category_for(gemini_score)
        if ai_fields.get("risk_category") != expected:
            return (f"risk_category must be {expected} for stress_score "
                    f"{gemini_score}.")
        if ai_fields.get("soft_label") != self.label_for(expected):
            return "soft_label must match risk_category."
        if ai_fields.get("speak_prominence") != self.prominence_for(expected):
            return "speak_prominence must match risk_category."
        if ai_fields.get("scored_items") != self.scored_items(answers):
            return "scored_items does not match the converted answers."
        logic_score = self.score(answers).stress_score
        if not self.within_tolerance(gemini_score, logic_score):
            return ("stress_score must match the mean of the 11 converted "
                    f"answers (expected {logic_score}).")
        return None
