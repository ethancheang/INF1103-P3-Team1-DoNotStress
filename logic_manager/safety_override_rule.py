"""SafetyOverrideRule: raise the tier when the reflection safety check fired."""

from __future__ import annotations

from .base_evaluator import BaseEvaluator
from .constants import RULE_SAFETY_OVERRIDE
from .risk_tier import RiskTier
from .rule_context import RuleContext
from .rule_outcome import RuleOutcome


class SafetyOverrideRule(BaseEvaluator):
    """If the reflection safety check fired, show "Please reach out".

    The check itself runs in io_manager. Logic only sees the True/False
    safety_flag, never the text. The tier is raised to High and "talk to
    someone" goes first. The stress score is not changed.
    """

    TIP = "talk_to_someone"
    NOTE = "safety_override: reflection safety check fired"

    @property
    def name(self) -> str:
        return RULE_SAFETY_OVERRIDE

    def evaluate(self, context: RuleContext) -> RuleOutcome:
        if not context.record.safety_flag:
            return RuleOutcome.not_triggered(self.name)
        return RuleOutcome(
            rule_name=self.name,
            triggered=True,
            lead_tips=(self.TIP,),
            minimum_tier=RiskTier.HIGH,
            note=self.NOTE,
        )
