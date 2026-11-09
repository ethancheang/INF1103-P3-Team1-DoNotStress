"""MockAIManager: test double that answers every check-in with one fixed AI reply."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ai_manager import AIManagerInterface, AIProcessingError, AIResponseSchema, ScoreVerifier


class MockAIManager(AIManagerInterface):
    """TEST DOUBLE for AIManagerInterface. Never wired into the running app.

    It still runs the Logic Manager's score check, so a wrong hardcoded
    reply fails exactly like a wrong Gemini reply would.
    """

    def __init__(self, reply: Mapping[str, Any], verifier: ScoreVerifier | None = None) -> None:
        self.__reply = dict(reply)
        self.__verifier = verifier
        self.__calls = 0

    @property
    def calls(self) -> int:
        return self.__calls

    def analyse(self, student: Mapping[str, Any]) -> dict[str, Any]:
        self.__calls += 1
        reply = dict(self.__reply)
        if self.__verifier is not None:
            problem = self.__verifier.verify(reply, student)
            if problem:
                raise AIProcessingError(AIProcessingError.INVALID_RESPONSE, problem)
        enriched = {**dict(student), **reply, "source": AIResponseSchema.SOURCE}
        enriched.pop("feelings_text", None)
        return enriched
