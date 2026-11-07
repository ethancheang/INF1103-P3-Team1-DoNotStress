"""CheckinPipeline: AI must succeed before Logic may finalize an assessment.

Open/Closed: a different AI manager or Logic manager can be injected without
changing this class. Liskov: any GeminiAIManager-compatible object can stand in.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

from ai_manager import AIProcessingError, GeminiAIManager
from logic_manager import AIScoreVerifier, LogicManager, LogicManagerError

logger = logging.getLogger(__name__)


class CheckinPipeline:
    """Runs one check-in through the AI Manager and then the Logic Manager.

    Returns (True, evaluated record dict) or (False, error code).
    """

    def __init__(
        self,
        ai: GeminiAIManager,
        logic: LogicManager,
        verifier: AIScoreVerifier,
    ) -> None:
        self._ai = ai
        self._logic = logic
        self._verifier = verifier

    def process(
        self,
        record: Mapping[str, Any],
        *,
        generate_fn=None,
        max_attempts: int = 3,
        retry_delay_sec: float = 0.5,
    ) -> tuple[bool, Any]:
        try:
            worker = self._ai
            if generate_fn is not None or max_attempts != 3 or retry_delay_sec != 0.5:
                worker = GeminiAIManager(
                    verifier=self._verifier,
                    generate_fn=generate_fn,
                    max_attempts=max_attempts,
                    retry_delay_sec=retry_delay_sec,
                )
            enriched = worker.analyse(record)
        except AIProcessingError as exc:
            logger.warning("Check-in could not complete: %s", exc.code)
            return False, exc.code
        if not isinstance(enriched, dict):
            logger.warning("Check-in could not complete: unavailable")
            return False, "unavailable"
        try:
            result = self._logic.evaluate(enriched)
        except LogicManagerError as exc:
            logger.warning("Logic rejected the check-in: %s", exc.code)
            return False, "unavailable"
        return True, result.to_record()
