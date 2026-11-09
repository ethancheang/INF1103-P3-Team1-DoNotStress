"""EvaluationResult: the output contract of the Logic Manager."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar

from .constants import RULE_SUPPORT_PRIORITY
from .enriched_record import EnrichedRecord
from .factor_card import FactorCard
from .risk_tier import RiskTier
from .rule_report import RuleReport
from .score_breakdown import ScoreBreakdown


@dataclass(frozen=True)
class EvaluationResult:
    """OUTPUT CONTRACT: Logic's final decision for one check-in.

    Use ``to_record()`` for data_manager and ``to_display()`` for io_manager.
    Gemini's stress score is kept as it is; Logic's own score is only an
    audit value (``logic_stress_score``).
    """

    record: EnrichedRecord
    scores: ScoreBreakdown
    tier: RiskTier
    tips: tuple[str, ...]
    risk_score: float
    report: RuleReport
    factor_cards: tuple[FactorCard, ...]
    logic_rule: str

    SOURCE: ClassVar[str] = "ai_logic"

    @property
    def stress_score(self) -> float:
        """Gemini's verified 1-5 stress score."""
        return self.record.assessment.stress_score

    @property
    def logic_stress_score(self) -> float:
        """Logic's own score for the same answers (audit only)."""
        return self.scores.stress_score

    @property
    def route(self) -> str:
        """The outcome path: "Low", "Moderate" or "High"."""
        return self.tier.category

    @property
    def soft_label(self) -> str:
        return self.tier.soft_label

    @property
    def speak_prominence(self) -> str:
        return self.tier.speak_prominence

    @property
    def recommended_support(self) -> str:
        return self.tier.recommended_support

    @property
    def notes(self) -> tuple[str, ...]:
        return self.report.notes

    @property
    def context_flags(self) -> dict[str, bool]:
        return self.report.context_flags

    @property
    def support_priority(self) -> bool:
        """True when the multi-condition rule (High tier + low social support) fired."""
        return self.report.fired(RULE_SUPPORT_PRIORITY)

    def to_record(self) -> dict[str, Any]:
        """OUTPUT CONTRACT for data_manager: one JSON-ready dict per check-in.

        Same keys and values as a Phase 1 evaluated record, so saved files
        and the admin table keep working:

        * identity: student_id (str|None), survey_version (str|None), safety_flag (bool)
        * the 11 raw answers (int, sleep_hours_avg float)
        * Gemini: scored_items (dict|None), stress_score (float 1-5),
          primary_stressors (list[str]), reasoning (str), confidence (float 0-1)
        * final outcome: risk_category, soft_label, speak_prominence (str),
          tips (list[str], at most 4)
        * Logic: ok=True, error=None, source="ai_logic", ai_ok=True,
          logic_rule (str), logic_stress_score (float), risk_score (float 0-1,
          not a probability), recommended_support (str),
          logic_clamp_notes (list[str]), support_priority (bool),
          context_flags (dict[str, bool]), support_mean (float),
          factor_insights (list of 4 dicts: title, flagged, value, text)

        The reflection text is never part of a record.
        """
        ai = self.record.assessment
        return {
            "student_id": self.record.student_id,
            "survey_version": self.record.survey_version,
            **self.record.answers.to_dict(),
            "safety_flag": self.record.safety_flag,
            "scored_items": None if ai.scored_items is None else dict(ai.scored_items),
            "stress_score": ai.stress_score,
            "risk_category": self.tier.category,
            "soft_label": self.soft_label,
            "speak_prominence": self.speak_prominence,
            "primary_stressors": list(ai.primary_stressors),
            "tips": list(self.tips),
            "reasoning": ai.reasoning,
            "confidence": ai.confidence,
            "ok": True,
            "error": None,
            "source": self.SOURCE,
            "ai_ok": True,
            "logic_rule": self.logic_rule,
            "logic_stress_score": self.logic_stress_score,
            "risk_score": self.risk_score,
            "recommended_support": self.recommended_support,
            "logic_clamp_notes": list(self.notes),
            "support_priority": self.support_priority,
            "context_flags": self.context_flags,
            "support_mean": self.scores.support_mean,
            "factor_insights": [card.to_dict() for card in self.factor_cards],
        }

    def to_display(self) -> dict[str, Any]:
        """OUTPUT CONTRACT for io_manager: what the student's result page needs.

        Tips are IDs; io_manager turns them into wording and adds the support
        contacts. Raw scores are left out on purpose: the stress score stays
        in the admin table, not on the student page.
        """
        ai = self.record.assessment
        return {
            "soft_label": self.soft_label,
            "speak_prominence": self.speak_prominence,
            "risk_category": self.tier.category,
            "tips": list(self.tips),
            "reasoning": ai.reasoning,
            "primary_stressors": list(ai.primary_stressors),
            "factor_insights": [card.to_dict() for card in self.factor_cards],
            "context_flags": self.context_flags,
            "safety_flag": self.record.safety_flag,
            "survey_version": self.record.survey_version,
            "answers": self.record.answers.to_dict(),
        }
