"""CheckinPipeline: AI must succeed before Logic may finalise an assessment."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from ai_manager import AIManagerInterface, AIProcessingError
from logic_manager import LogicManager, LogicManagerError

logger = logging.getLogger(__name__)


class CheckinPipeline:
    """Runs one validated check-in through the AI Manager and then the Logic Manager.

    ``process`` returns ``(True, evaluated_record)`` or ``(False, error_code)``.
    It depends on the AIManagerInterface abstraction, so the live Gemini
    manager or a test double can be injected without changing this class
    (Dependency Inversion / Liskov Substitution). Both managers are
    associations: they are created by the app and only used here.
    """

    def __init__(self, ai: AIManagerInterface, logic: LogicManager) -> None:
        self.__ai = ai
        self.__logic = logic

    def process(self, record: Mapping[str, Any]) -> tuple[bool, Any]:
        try:
            enriched = self.__ai.analyse(record)
        except AIProcessingError as exc:
            logger.warning("Check-in could not complete: %s", exc.code)
            return False, exc.code
        if not isinstance(enriched, dict):
            logger.warning("Check-in could not complete: the AI Manager returned %s", type(enriched).__name__)
            return False, AIProcessingError.UNAVAILABLE
        try:
            result = self.__logic.evaluate(enriched)
        except LogicManagerError as exc:
            logger.warning("Logic rejected the check-in: %s", exc.code)
            return False, AIProcessingError.UNAVAILABLE
        return True, result.to_record()
