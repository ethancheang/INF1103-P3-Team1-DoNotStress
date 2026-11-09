"""Flag: Flag for poor sleep quality/low sleep duration."""

from __future__ import annotations

from logic.context_flag import ContextFlag

# Checked by Zhung Yi - 9/11/2026 2.10pm


class SleepFlag(ContextFlag):
    """Raised for under 6 hours of sleep or sleep quality of 4 or more."""

    HOURS_KEY: str = "sleep_hours_avg"
    QUALITY_KEY: str = "sleep_quality"
    SHORT_BELOW_HOURS: float = 6
    POOR_QUALITY_FROM: float = 4

    @property
    def name(self) -> str:
        return "sleep"

    @property
    def tip_id(self) -> str:
        return "sleep_routine"

    def raised(self, answers: dict[str, float],
               support_mean: float) -> bool:
        return (answers[self.HOURS_KEY] < self.SHORT_BELOW_HOURS
                or answers[self.QUALITY_KEY] >= self.POOR_QUALITY_FROM)
