"""FinanceFlagRule: raised when money stress is high or overwhelming."""

from __future__ import annotations

from .constants import FLAG_FINANCES
from .context_flag_rule import ContextFlagRule
from .rule_context import RuleContext


class FinanceFlagRule(ContextFlagRule):
    """High (4) or overwhelming (5) stress about money."""

    def __init__(self, stress_from: int = 4) -> None:
        super().__init__("money_worries")
        self.__stress_from = stress_from

    @property
    def name(self) -> str:
        return FLAG_FINANCES

    @property
    def stress_from(self) -> int:
        return self.__stress_from

    def _is_raised(self, context: RuleContext) -> bool:
        return context.answers.fin_stress >= self.__stress_from
