"""RuleContext: the read-only view a business rule receives."""

from __future__ import annotations

from dataclasses import dataclass

from .ai_assessment import AIAssessment
from .enriched_record import EnrichedRecord
from .score_breakdown import ScoreBreakdown
from .student_answers import StudentAnswers


@dataclass(frozen=True)
class RuleContext:
    """Everything a business rule may look at. Rules read it and never change it."""

    record: EnrichedRecord
    scores: ScoreBreakdown

    @property
    def answers(self) -> StudentAnswers:
        return self.record.answers

    @property
    def assessment(self) -> AIAssessment:
        return self.record.assessment
