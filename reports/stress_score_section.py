"""StressScoreSection: the average stress score and the cases that need attention."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .report_section import ReportSection


class StressScoreSection(ReportSection):
    """Average 1-5 stress score, plus how many check-ins triggered the
    multi-condition support-priority rule or the reflection safety check."""

    SCORE_MIN = 1.0
    SCORE_MAX = 5.0

    @property
    def key(self) -> str:
        return "stress"

    def build(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        evaluated = self._evaluated(records)
        scores = []
        for record in evaluated:
            score = self._number(record.get("stress_score"))
            if score is not None and self.SCORE_MIN <= score <= self.SCORE_MAX:
                scores.append(score)
        return {
            "average_score": round(sum(scores) / len(scores), 2) if scores else None,
            "scored": len(scores),
            "support_priority": sum(1 for record in evaluated if record.get("support_priority") is True),
            "safety_flags": sum(1 for record in evaluated if record.get("safety_flag") is True),
        }
