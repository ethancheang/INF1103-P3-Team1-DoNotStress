"""AIManagerInterface: the contract every AI Manager follows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping
from typing import Any


class AIManagerInterface(ABC):
    """INTERFACE for the AI Manager.

    The check-in pipeline only depends on this type (Dependency Inversion),
    so the real Gemini manager and the test double can stand in for each
    other (Liskov Substitution).

    Contract for ``analyse``:
      * it receives one validated check-in from the I/O Manager;
      * on success it returns the student's answers merged with the
        validated AI fields, with any reflection text removed;
      * on failure it raises ``AIProcessingError`` and never invents a result.
    """

    @abstractmethod
    def analyse(self, student: Mapping[str, Any]) -> dict[str, Any]:
        """Analyse one validated check-in. Raises AIProcessingError on failure."""
