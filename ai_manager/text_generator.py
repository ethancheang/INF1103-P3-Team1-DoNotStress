"""TextGenerator: the contract for anything that sends a prompt to a language model."""

from __future__ import annotations

from abc import ABC, abstractmethod


class TextGenerator(ABC):
    """ABSTRACT CLASS for one language-model client.

    ``generate`` is abstract; ``is_configured`` and ``redact`` are default
    hooks that a subclass may override (GeminiTextGenerator does both).
    GeminiAIManager only talks to this type, so the live Gemini client and
    the test doubles in ``tests/doubles`` are interchangeable (Liskov
    Substitution) and a different provider can be added as a new subclass
    without changing the manager (Open/Closed).
    """

    @abstractmethod
    def generate(self, prompt: str, model_name: str) -> str:
        """Send ``prompt`` to ``model_name`` and return the raw reply text.

        Raise any exception on a connection problem; the AI Manager
        classifies it (timeout, rate limit, model unavailable) and retries.
        """

    def is_configured(self) -> bool:
        """True when the client has what it needs to call the model (e.g. an API key)."""
        return True

    def redact(self, text: str) -> str:
        """``text`` with any secret removed, safe for the log. Nothing to hide by default."""
        return text
