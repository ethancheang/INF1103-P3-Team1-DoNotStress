"""FactorFlagSection: how often each context flag (sleep, study, money, support) was raised."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from logic_manager.constants import FLAG_FINANCES, FLAG_SLEEP, FLAG_SUPPORT, FLAG_WORKLOAD

from .report_section import ReportSection


class FactorFlagSection(ReportSection):
    """Count and share of evaluated check-ins with each Logic Manager context flag raised."""

    FLAGS = (FLAG_SLEEP, FLAG_WORKLOAD, FLAG_FINANCES, FLAG_SUPPORT)

    @property
    def key(self) -> str:
        return "factors"

    def build(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        evaluated = self._evaluated(records)
        items = []
        for flag in self.FLAGS:
            count = sum(1 for record in evaluated if self.__raised(record, flag))
            items.append({"id": flag, "count": count, "percent": self._percent(count, len(evaluated))})
        return {"items": items}

    @staticmethod
    def __raised(record: Mapping[str, Any], flag: str) -> bool:
        flags = record.get("context_flags")
        return isinstance(flags, Mapping) and flags.get(flag) is True
