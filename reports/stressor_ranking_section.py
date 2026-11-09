"""StressorRankingSection: the stressors Gemini named most often."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from typing import Any

from .report_section import ReportSection


class StressorRankingSection(ReportSection):
    """The most common ``primary_stressors`` across evaluated check-ins."""

    def __init__(self, top: int = 3) -> None:
        if top < 1:
            raise ValueError("top must be at least 1.")
        self.__top = top

    @property
    def key(self) -> str:
        return "stressors"

    @property
    def top(self) -> int:
        return self.__top

    def build(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        counts: Counter[str] = Counter()
        for record in self._evaluated(records):
            stressors = record.get("primary_stressors")
            if isinstance(stressors, (list, tuple)):
                counts.update({item for item in stressors if isinstance(item, str) and item})
        ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))[: self.__top]
        return {"items": [{"id": stressor, "count": count} for stressor, count in ranked]}
