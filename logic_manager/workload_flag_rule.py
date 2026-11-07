"""WorkloadFlagRule: raised when the student agrees coursework is too much."""

from __future__ import annotations

from .constants import FLAG_WORKLOAD
from .context_flag_rule import ContextFlagRule
from .rule_context import RuleContext


class WorkloadFlagRule(ContextFlagRule):
    """The student agrees (4) or strongly agrees (5) that coursework is too much.

    The catch-up answer counts in the score but does not raise this flag.
    """

    def __init__(self, agree_from: int = 4) -> None:
        super().__init__("workload_chunks")
        self.__agree_from = agree_from

    @property
    def name(self) -> str:
        return FLAG_WORKLOAD

    @property
    def agree_from(self) -> int:
        return self.__agree_from

    def _is_raised(self, context: RuleContext) -> bool:
        return context.answers.pas_workload >= self.__agree_from
