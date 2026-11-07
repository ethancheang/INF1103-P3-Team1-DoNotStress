"""RuleReport: the combined decisions of every business rule for one record."""

from __future__ import annotations

from dataclasses import dataclass

from .risk_tier import RiskTier
from .rule_outcome import RuleOutcome


@dataclass(frozen=True)
class RuleReport:
    """Everything the business rules decided for one record, in rule order."""

    outcomes: tuple[RuleOutcome, ...] = ()

    @property
    def lead_tips(self) -> tuple[str, ...]:
        return tuple(tip for outcome in self.outcomes for tip in outcome.lead_tips)

    @property
    def extra_tips(self) -> tuple[str, ...]:
        return tuple(tip for outcome in self.outcomes for tip in outcome.extra_tips)

    @property
    def escalations(self) -> tuple[RiskTier, ...]:
        """Tiers that rules asked for (the final tier is at least each of these)."""
        return tuple(o.minimum_tier for o in self.outcomes if o.minimum_tier is not None)

    @property
    def notes(self) -> tuple[str, ...]:
        """Why Logic changed anything (empty when nothing changed)."""
        return tuple(o.note for o in self.outcomes if o.note)

    @property
    def context_flags(self) -> dict[str, bool]:
        """The context flags, e.g. {"sleep": True, "workload": False, ...}."""
        return {o.rule_name: o.triggered for o in self.outcomes if o.context_flag}

    @property
    def triggered_rules(self) -> tuple[str, ...]:
        return tuple(o.rule_name for o in self.outcomes if o.triggered)

    def fired(self, rule_name: str) -> bool:
        """True if the rule called ``rule_name`` applied to this record."""
        return rule_name in self.triggered_rules
