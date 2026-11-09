"""ContextFlagRule: abstract base for the four context-flag rules."""

from __future__ import annotations

from abc import abstractmethod
from typing import final

from .base_evaluator import BaseEvaluator
from .rule_context import RuleContext
from .rule_outcome import RuleOutcome


class ContextFlagRule(BaseEvaluator):
    """ABSTRACT CLASS for the four context flags.

    The shared behaviour lives here (Template Method pattern): a raised flag
    adds its own tip and is reported in ``context_flags``. Each subclass
    only decides WHEN its flag is raised, by implementing ``_is_raised``.

    Flags never change the tier and never remove one of Gemini's tips.
    Their tip is only added if there is room.
    """

    def __init__(self, tip_id: str) -> None:
        self._tip_id = tip_id

    @property
    def tip_id(self) -> str:
        """The tip this flag adds when it is raised."""
        return self._tip_id

    @final
    def evaluate(self, context: RuleContext) -> RuleOutcome:
        if not self._is_raised(context):
            return RuleOutcome.not_triggered(self.name, context_flag=True)
        return RuleOutcome(
            rule_name=self.name,
            triggered=True,
            extra_tips=(self._tip_id,),
            context_flag=True,
        )

    @abstractmethod
    def _is_raised(self, context: RuleContext) -> bool:
        """True when this flag applies to the record."""
