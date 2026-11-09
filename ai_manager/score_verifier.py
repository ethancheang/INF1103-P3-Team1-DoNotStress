"""ScoreVerifier: what the AI Manager needs from the Logic Manager's scoring rules."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ScoreVerifier(Protocol):
    """INTERFACE (structural): scoring instructions for the prompt and a check on the reply.

    The Logic Manager owns the scoring rules; ``logic_manager.AIScoreVerifier``
    satisfies this protocol without importing the AI Manager, so the two
    managers stay decoupled (Dependency Inversion).
    """

    def instructions(self) -> str:
        """The scoring formula and tier rules, written for the prompt."""
        ...

    def verify(self, ai_fields: Mapping[str, Any], answers: Mapping[str, Any]) -> str | None:
        """The first problem with the AI's numbers, or None when they are right."""
        ...
