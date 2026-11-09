"""Rule: Forces "Please reach out" due to reflection content matching."""

from __future__ import annotations

from logic.business_rule import BusinessRule
from logic.decision import Decision
from logic.tier_table import TierTable

# Checked by Zhung Yi - 9/11/2026 1.30pm


class SafetyOverrideRule(BusinessRule):
    """If the safety check fired, show High / "Please reach out".

    "Talk to someone" leads the tips. The stress score is never changed,
    and the reflection text itself is never seen here.
    """

    TIER: str = TierTable.HIGH
    TALK_TO_SOMEONE: str = "talk_to_someone"

    @property
    def name(self) -> str:
        return "safety_override"

    def applies(self, decision: Decision) -> bool:
        return decision.field("safety_flag") is True

    def apply(self, decision: Decision) -> None:
        decision.risk_category = self.TIER
        decision.soft_label = TierTable.LABELS[self.TIER]
        decision.speak_prominence = TierTable.PROMINENCE[self.TIER]
        decision.lead_with(self.TALK_TO_SOMEONE)
        decision.note("safety_override: reflection safety check fired")
