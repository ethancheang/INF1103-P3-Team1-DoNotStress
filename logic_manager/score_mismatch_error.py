"""ScoreMismatchError: Gemini's score does not match the answers."""

from __future__ import annotations

from .logic_manager_error import LogicManagerError


class ScoreMismatchError(LogicManagerError):
    """Gemini's stress_score does not match the score worked out from the answers."""

    code = "score_mismatch"

    def __init__(self, ai_score: float, logic_score: float) -> None:
        self._ai_score = ai_score
        self._logic_score = logic_score
        super().__init__(
            f"Gemini stress_score {ai_score:g} does not match the answers "
            f"({logic_score:g}); no result is given."
        )

    @property
    def ai_score(self) -> float:
        """The score Gemini gave."""
        return self._ai_score

    @property
    def logic_score(self) -> float:
        """The score Logic worked out from the same answers."""
        return self._logic_score
