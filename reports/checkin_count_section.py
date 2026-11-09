"""CheckinCountSection: how many check-ins are evaluated and how many are pending."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .report_section import ReportSection


class CheckinCountSection(ReportSection):
    """Total, evaluated and pending check-ins.

    Pending check-ins are students whose answers were saved but whom Gemini
    could not assess; staff may want to follow these up.
    """

    @property
    def key(self) -> str:
        return "checkins"

    def build(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        total = sum(1 for record in records if isinstance(record, Mapping))
        evaluated = len(self._evaluated(records))
        return {"total": total, "evaluated": evaluated, "pending": total - evaluated}
