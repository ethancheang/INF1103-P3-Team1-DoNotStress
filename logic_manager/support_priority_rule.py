"""SupportPriorityRule: the multi-condition rule on two AI fields."""

from __future__ import annotations

from .base_evaluator import BaseEvaluator
from .constants import RULE_SUPPORT_PRIORITY
from .risk_tier import RiskTier
from .rule_context import RuleContext
from .rule_outcome import RuleOutcome


class SupportPriorityRule(BaseEvaluator):
    """The brief's multi-condition rule, using two fields from Gemini's reply.

    Fires when Gemini rated the check-in High (``risk_category``) AND named
    low social support as a stressor (``primary_stressors``). Then "talk to
    someone" goes first and "keep in touch" is added if there is room.

    It reads Gemini's own tier, not the tier after the safety override,
    exactly as in Phase 1.
    """

    REQUIRED_TIER = RiskTier.HIGH
    REQUIRED_STRESSOR = "low_social_support"
    LEAD_TIP = "talk_to_someone"
    EXTRA_TIP = "keep_social_contact"
    NOTE = "support_priority: High tier with low social support"

    @property
    def name(self) -> str:
        return RULE_SUPPORT_PRIORITY

    def evaluate(self, context: RuleContext) -> RuleOutcome:
        ai = context.assessment
        high_tier = ai.tier is self.REQUIRED_TIER
        low_support = self.REQUIRED_STRESSOR in ai.primary_stressors
        if not (high_tier and low_support):
            return RuleOutcome.not_triggered(self.name)
        return RuleOutcome(
            rule_name=self.name,
            triggered=True,
            lead_tips=(self.LEAD_TIP,),
            extra_tips=(self.EXTRA_TIP,),
            note=self.NOTE,
        )
