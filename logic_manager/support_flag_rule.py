"""SupportFlagRule: raised when the student reports low social support."""

from __future__ import annotations

from .constants import FLAG_SUPPORT
from .context_flag_rule import ContextFlagRule
from .rule_context import RuleContext


class SupportFlagRule(ContextFlagRule):
    """Mostly disagreeing that friends and family are there (raw mean below 2.5)."""

    def __init__(self, mean_below: float = 2.5) -> None:
        super().__init__("talk_to_someone")
        self.__mean_below = mean_below

    @property
    def name(self) -> str:
        return FLAG_SUPPORT

    @property
    def mean_below(self) -> float:
        return self.__mean_below

    def _is_raised(self, context: RuleContext) -> bool:
        return context.scores.support_mean < self.__mean_below
