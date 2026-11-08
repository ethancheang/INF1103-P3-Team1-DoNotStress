"""Flag: one answer at or above threshold."""

from __future__ import annotations

from logic.context_flag import ContextFlag

# Checked by Zhung Yi - 8/11/2026 8.28pm


class HighAnswerFlag(ContextFlag):
    """Raised when one answer is at least `minimum`.

    One class serves several flags: StressScorer makes one object for
    workload (pas_workload >= 4) and one for finances (fin_stress >= 4).
    """

    def __init__(self, name: str, key: str, minimum: float,
                 tip_id: str) -> None:
        self.__name: str = name
        self.__key: str = key
        self.__minimum: float = minimum
        self.__tip_id: str = tip_id

    @property
    def name(self) -> str:
        return self.__name

    @property
    def tip_id(self) -> str:
        return self.__tip_id

    def raised(self, answers: dict[str, float],
               support_mean: float) -> bool:
        return answers[self.__key] >= self.__minimum
