"""ScriptedTextGenerator: test double for the Gemini API client."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from ai_manager import TextGenerator


class ScriptedTextGenerator(TextGenerator):
    """TEST DOUBLE for TextGenerator: plays back a script instead of calling Gemini.

    Each script item is either reply text (returned) or an exception
    (raised), in order. When the script runs out, ``default`` is used.
    It records every prompt and model it was asked for, so tests can check
    what would have been sent to the API (for example that no student ID
    is in the prompt).
    """

    def __init__(self, script: Iterable[Any] = (), default: Any = "not json", configured: bool = True) -> None:
        self.__script = list(script)
        self.__default = default
        self.__configured = configured
        self.__prompts: list[str] = []
        self.__models: list[str] = []

    @property
    def prompts(self) -> list[str]:
        return list(self.__prompts)

    @property
    def models(self) -> list[str]:
        return list(self.__models)

    def queue(self, *items: Any) -> None:
        """Add more replies or exceptions to the end of the script."""
        self.__script.extend(items)

    def is_configured(self) -> bool:
        return self.__configured

    def generate(self, prompt: str, model_name: str) -> str:
        self.__prompts.append(prompt)
        self.__models.append(model_name)
        item = self.__script.pop(0) if self.__script else self.__default
        if isinstance(item, BaseException):
            raise item
        return str(item)
