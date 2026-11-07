"Checked by Qing Kai"
"Date: 7/11/2026"
"Time: 6.10pm"

"""Rule: each raised context flag suggests its matching tip."""

from __future__ import annotations

from logic.business_rule import BusinessRule
from logic.context_flag import ContextFlag
from logic.decision import Decision


class ContextFlagRule(BusinessRule):
    """Every raised flag suggests its own tip, in the flags' order.

    Flags only add tips after Gemini's own, never replace them, and never
    change the tier. The flags are passed in and shared with StressScorer
    (aggregation), so a new flag needs no change here.
    """

    def __init__(self, flags: list[ContextFlag]) -> None:
        self.__flags: list[ContextFlag] = list(flags)

    @property
    def name(self) -> str:
        return "context_flags"

    def applies(self, decision: Decision) -> bool:
        return any(decision.context_flags.values())

    def apply(self, decision: Decision) -> None:
        raised = decision.context_flags
        for flag in self.__flags:
            if raised.get(flag.name):
                decision.suggest(flag.tip_id)
