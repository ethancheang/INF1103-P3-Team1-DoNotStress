"""Flag: low friends and family suport score."""

from __future__ import annotations

from logic.context_flag import ContextFlag

# Checked by Zhung Yi - 9/11/2026 11.30pm


class SupportFlag(ContextFlag):
    """Raised when the friends and family answers average below 2.5."""

    LOW_BELOW: float = 2.5

    @property
    def name(self) -> str:
        return "support"

    @property
    def tip_id(self) -> str:
        return "talk_to_someone"

    def raised(self, answers: dict[str, float],
               support_mean: float) -> bool:
        return support_mean < self.LOW_BELOW
