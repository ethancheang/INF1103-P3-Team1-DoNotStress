"""RuleOutcome: what one business rule decided for one record."""

from __future__ import annotations

from dataclasses import dataclass

from .risk_tier import RiskTier


@dataclass(frozen=True)
class RuleOutcome:
    """What one business rule decided for one record.

    * ``lead_tips`` go before Gemini's tips.
    * ``extra_tips`` are added after Gemini's tips while there is room.
    * ``minimum_tier`` raises the final tier to at least this tier.
    * ``note`` is stored in ``logic_clamp_notes`` to explain the change.
    * ``context_flag`` marks the outcome as one of the four context flags.

    A rule that did not fire is not allowed to change anything. That check
    is part of the shared rule contract (Liskov Substitution).
    """

    rule_name: str
    triggered: bool
    lead_tips: tuple[str, ...] = ()
    extra_tips: tuple[str, ...] = ()
    minimum_tier: RiskTier | None = None
    note: str | None = None
    context_flag: bool = False

    def __post_init__(self) -> None:
        if not self.rule_name:
            raise ValueError("A rule outcome needs the rule's name.")
        changes_something = (
            bool(self.lead_tips or self.extra_tips or self.note)
            or self.minimum_tier is not None
        )
        if not self.triggered and changes_something:
            raise ValueError(f"Rule {self.rule_name!r} did not fire, so it cannot change the result.")

    @classmethod
    def not_triggered(cls, rule_name: str, *, context_flag: bool = False) -> RuleOutcome:
        """The outcome of a rule that did not apply to this record."""
        return cls(rule_name=rule_name, triggered=False, context_flag=context_flag)
