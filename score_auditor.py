"""The contract the AI layer needs from whoever owns the scoring rules."""

from __future__ import annotations

from abc import ABC, abstractmethod

from json_types import JSONObject

# Checked by Zhung Yi + Qing Kai - 8/11/2026 10.12pm


class ScoreAuditor(ABC):
    """What AIManager asks of the scorer, without knowing the formula.

    AIManager holds no domain rules. It is handed a ScoreAuditor (the
    Logic layer's StressScorer) and only ever calls the two methods
    below: one to write the scoring rules into the prompt, one to check a
    reply against the answers. The formula itself stays in Logic, so a
    change to the rules never touches the AI layer (dependency inversion:
    the AI layer depends on this interface, not on StressScorer).
    """

    @abstractmethod
    def instructions(self) -> str:
        """The scoring formula and tier rules, written for the prompt."""

    @abstractmethod
    def verify(self, ai_fields: JSONObject,
               answers: JSONObject) -> str | None:
        """Check Gemini's reply against the answers. Never raises.

        Returns a short problem message when the reply does not match the
        answers, or None when the arithmetic and tier are correct. A
        message is treated by AIManager like any other invalid reply.
        """
