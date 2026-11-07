"Checked by Qing Kai"
"Date: 7/11/2026"
"Time: 6.10pm"

"""The contract every context flag follows."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ContextFlag(ABC):
    """Interface for one reason, read from the answers, to add a tip.

    Flags steer tips and never change the tier. A new flag is a new
    class added to StressScorer's list; ContextFlagRule and
    StressScorer.score() do not change.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """The key used in context_flags, e.g. "sleep"."""

    @property
    @abstractmethod
    def tip_id(self) -> str:
        """The tip this flag suggests when it is raised."""

    @abstractmethod
    def raised(self, answers: dict[str, float],
               support_mean: float) -> bool:
        """True when these answers call for this flag's tip."""
