"""DoNotStress - Logic Layer (LogicManager).

The parent of the Logic layer. It owns the scorer and the ordered list of
business rules, and is the only class main.py talks to. For one
AI-enriched check-in it:

  1. asks StressScorer to re-score the 11 raw answers (an audit; Logic
     never substitutes its own number),
  2. rejects the record when Gemini's stress_score is more than 0.01 from
     the audit score (score_mismatch),
  3. builds a Decision that starts as exactly what Gemini returned,
  4. runs its business rules in order on that Decision (safety first, then
     support-priority, then the context flags), and
  5. assembles the final result dict the rest of the app reads.

LogicManager also lends its StressScorer to AIManager as the ScoreAuditor,
so the scoring formula lives in one place and the AI layer holds no domain
rules.

Composition: the scorer and the rule list are created here and belong to
this manager. Aggregation: the flags are created by the scorer and shared
with ContextFlagRule, so a new flag needs no change to this class.

Pipeline position:
  User -> io_manager -> ai_manager (required) -> logic_manager -> data_manager
"""

from __future__ import annotations

from ai.score_auditor import ScoreAuditor
from json_types import JSONObject
from logic.answer_reader import AnswerReader
from logic.business_rule import BusinessRule
from logic.context_flag_rule import ContextFlagRule
from logic.decision import Decision
from logic.safety_override_rule import SafetyOverrideRule
from logic.score_card import ScoreCard
from logic.stress_scorer import StressScorer
from logic.support_priority_rule import SupportPriorityRule
from logic.tier_table import TierTable

# Checked by Zhung Yi - 8/11/2026 8.28pm


class LogicManager:
    """Validates Gemini's analysis against the answers and applies the rules.

    The scorer and the rules are created here and owned by this manager
    (composition). The rules run in a fixed order, so changing a rule or
    adding one is a change to a BusinessRule subclass, not to this class.
    """

    SOURCE: str = "ai_logic"       # marks a record that passed Logic
    RULE: str = "v3"               # the scoring/rule version
    ERROR_SCORE_MISMATCH: str = "score_mismatch"

    # The 11 answers must be present and usable before Logic will score.
    REQUIRED_AI_FIELDS: tuple[str, ...] = (
        "stress_score", "risk_category", "soft_label", "speak_prominence",
        "primary_stressors", "tips", "reasoning", "confidence",
    )

    # Short internal note stored with each record. The student never sees
    # it; the UI shows tips instead. Keyed by the final tier.
    RECOMMENDED_SUPPORT: dict[str, str] = {
        TierTable.LOW:
            "Internal: low stress. The UI shows tips, not this field.",
        TierTable.MODERATE:
            "Internal: moderate stress. The UI shows tips, not this field.",
        TierTable.HIGH:
            "Internal: high stress. The UI shows tips, not this field.",
    }

    MAX_TIPS: int = 4

    def __init__(self) -> None:
        self.__scorer: StressScorer = StressScorer()
        self.__reader: AnswerReader = AnswerReader()
        self.__tiers: TierTable = TierTable()
        # Order matters: safety forces High first, support-priority then
        # leads with "talk to someone", context flags fill the rest. This
        # mirrors the original apply_logic precedence exactly.
        self.__rules: list[BusinessRule] = [
            SafetyOverrideRule(),
            SupportPriorityRule(),
            ContextFlagRule(self.__scorer.flags),
        ]

    @property
    def auditor(self) -> ScoreAuditor:
        """The scorer, lent to AIManager as its ScoreAuditor."""
        return self.__scorer

    @property
    def rules(self) -> list[BusinessRule]:
        """The business rules, in the order they run."""
        return list(self.__rules)

    def evaluate(self, record: JSONObject) -> JSONObject:
        """Run every business rule on the AI-enriched record.

        Returns the final decision dict (ok=True with the outcome fields),
        or an error dict (ok=False) when a field is missing or unusable or
        when Gemini's score does not match the answers. Never mutates the
        record it is given.
        """
        if not isinstance(record, dict):
            return self.__error(
                {}, missing=list(self.REQUIRED_AI_FIELDS), invalid=["record"])

        missing, invalid = self.__field_problems(record)
        if missing or invalid:
            return self.__error(record, missing=missing, invalid=invalid)

        card = self.__scorer.score(record)
        gemini_score = self.__reader.read(record, "stress_score")

        # Cross-check only: Logic never substitutes its own score.
        if not self.__scorer.within_tolerance(gemini_score, card.stress_score):
            return self.__mismatch(record, gemini_score, card.stress_score)

        decision = Decision(record, card.context_flags)
        for rule in self.__rules:
            rule.run(decision)

        return self.__result(record, card, decision, gemini_score)

    def score(self, record: JSONObject) -> float | None:
        """The verified AI stress_score, or None if Logic rejects it.

        Logic never substitutes its own number; the audit score is kept
        for staff only.
        """
        result = self.evaluate(record)
        if not result.get("ok"):
            return None
        return float(result["stress_score"])

    def route(self, result: JSONObject) -> str:
        """The outcome path: a tier name, or "unavailable".

        Routes on the final risk_category only when the soft_label agrees
        with it. Pass the dict evaluate() returned.
        """
        if not isinstance(result, dict) or not result.get("ok"):
            return "unavailable"
        category = result.get("risk_category")
        if self.__tiers.label_matches(category, result.get("soft_label")):
            return category
        return "unavailable"

    def __result(self, record: JSONObject, card: ScoreCard,
                 decision: Decision, gemini_score: float) -> JSONObject:
        """Assemble the success dict from the card and the ruled decision."""
        tips = self.__merge_tips(
            decision.lead_tips, decision.gemini_tips, decision.extra_tips)
        category = decision.risk_category
        enriched = dict(record)
        enriched.pop("feelings_text", None)
        enriched.update({
            "ok": True,
            "error": None,
            "source": self.SOURCE,
            "ai_ok": True,
            "logic_rule": self.RULE,
            "stress_score": record["stress_score"],
            "logic_stress_score": card.stress_score,
            "risk_score": self.__scorer.risk_score_for(gemini_score),
            "recommended_support": self.RECOMMENDED_SUPPORT[category],
            "risk_category": category,
            "soft_label": decision.soft_label,
            "speak_prominence": decision.speak_prominence,
            "tips": tips,
            "primary_stressors": list(record["primary_stressors"]),
            "reasoning": record["reasoning"],
            "logic_clamp_notes": decision.notes,
            "support_priority": decision.support_priority,
            "context_flags": card.context_flags,
            "support_mean": card.support_mean,
        })
        return enriched

    def __merge_tips(self, lead: list[str], gemini: list[str],
                     extra: list[str]) -> list[str]:
        """lead first, then Gemini's tips, then extra tips while there is room.

        Gemini gives at most 3 tips and lead holds at most one, so Gemini's
        tips are never pushed out of the first MAX_TIPS.
        """
        ordered: list[str] = []
        for tip_id in lead + gemini:
            if tip_id not in ordered:
                ordered.append(tip_id)
        for tip_id in extra:
            if len(ordered) >= self.MAX_TIPS:
                break
            if tip_id not in ordered:
                ordered.append(tip_id)
        return ordered[:self.MAX_TIPS]

    def __field_problems(self, record: JSONObject) -> tuple[
            list[str], list[str]]:
        """Return (missing keys, unusable keys).

        Checks only that the fields exist and that the numbers Logic scores
        with are usable. Gemini's schema is ai_manager's job.
        """
        keys = self.REQUIRED_AI_FIELDS + self.__scorer.ANSWER_KEYS
        missing = [key for key in keys if key not in record]
        invalid = [
            key for key in ("stress_score",) + self.__scorer.ANSWER_KEYS
            if key in record
            and not self.__reader.in_range(key, record[key])
        ]
        for key in ("tips", "primary_stressors"):
            if key in record and not isinstance(record[key], list):
                invalid.append(key)
        return missing, invalid

    def __error(self, record: JSONObject, *, missing: list[str],
                invalid: list[str]) -> JSONObject:
        """An error dict. ok=False is a hard stop, not a fallback outcome."""
        result = dict(record) if isinstance(record, dict) else {}
        result.pop("feelings_text", None)
        result.update({
            "ok": False,
            "error": "ai_fields_required",
            "missing": list(missing),
            "invalid": list(invalid),
            "message": (
                "Logic requires a successful Gemini (AI-enriched) record and "
                "all 11 answers; it does not guess outcomes without them."),
        })
        return result

    def __mismatch(self, record: JSONObject, gemini_score: float,
                   logic_score: float) -> JSONObject:
        """Gemini's score disagrees with the answers; no outcome is produced."""
        result = dict(record)
        result.pop("feelings_text", None)
        result.update({
            "ok": False,
            "error": self.ERROR_SCORE_MISMATCH,
            "stress_score": record["stress_score"],
            "logic_stress_score": logic_score,
            "message": (
                f"Gemini stress_score {gemini_score:g} does not match the "
                f"answers ({logic_score:g}); no result is given."),
        })
        return result
