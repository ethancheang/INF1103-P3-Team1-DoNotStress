"""SleepFlagRule: raised when sleep is short or quality is poor."""

from __future__ import annotations

from .constants import FLAG_SLEEP
from .context_flag_rule import ContextFlagRule
from .rule_context import RuleContext


class SleepFlagRule(ContextFlagRule):
    """Short sleep (under 6 hours) OR poor sleep quality (fairly or very bad)."""

    def __init__(self, short_sleep_below: float = 6, poor_quality_from: int = 4) -> None:
        super().__init__("sleep_routine")
        self.__short_sleep_below = short_sleep_below
        self.__poor_quality_from = poor_quality_from

    @property
    def name(self) -> str:
        return FLAG_SLEEP

    @property
    def short_sleep_below(self) -> float:
        return self.__short_sleep_below

    @property
    def poor_quality_from(self) -> int:
        return self.__poor_quality_from

    def _is_raised(self, context: RuleContext) -> bool:
        answers = context.answers
        return (
            answers.sleep_hours_avg < self.__short_sleep_below
            or answers.sleep_quality >= self.__poor_quality_from
        )
