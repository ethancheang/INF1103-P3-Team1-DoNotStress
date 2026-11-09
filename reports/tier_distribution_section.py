"""TierDistributionSection: how evaluated check-ins split across the three tiers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from logic_manager import RiskTier

from .report_section import ReportSection


class TierDistributionSection(ReportSection):
    """Count and share of Low, Moderate and High check-ins (final tier after the rules)."""

    @property
    def key(self) -> str:
        return "tiers"

    def build(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        evaluated = self._evaluated(records)
        items = []
        for tier in RiskTier:
            count = sum(1 for record in evaluated if record.get("risk_category") == tier.category)
            items.append({
                "category": tier.category,
                "soft_label": tier.soft_label,
                "count": count,
                "percent": self._percent(count, len(evaluated)),
            })
        return {"items": items}
