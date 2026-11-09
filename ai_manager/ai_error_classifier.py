"""AIErrorClassifier: turns API exceptions into the AI Manager's error codes."""

from __future__ import annotations

from collections.abc import Sequence

from .ai_processing_error import AIProcessingError


class AIErrorClassifier:
    """Decides what a failed call means and what the final error code is.

    * rate limit (HTTP 429, "quota", "too many requests")  -> ``rate_limited``
    * "timeout" / "timed out"                              -> ``timeout``
    * model gone (404) or busy (503)                       -> ``unavailable``, try the next model now
    * anything else                                        -> ``unavailable``
    """

    def classify(self, error: BaseException, detail: str) -> tuple[str, bool]:
        """``(error_code, switch_model)`` for one exception.

        ``detail`` is the exception text with secrets already removed.
        ``switch_model`` is True when retrying the same model is pointless.
        """
        lowered = detail.lower()
        if self.is_rate_limited(error):
            return AIProcessingError.RATE_LIMITED, False
        if "timeout" in lowered or "timed out" in lowered:
            return AIProcessingError.TIMEOUT, False
        if "404" in detail or "NOT_FOUND" in detail or "no longer available" in lowered:
            return AIProcessingError.UNAVAILABLE, True
        if "503" in detail or "UNAVAILABLE" in detail or "high demand" in lowered:
            return AIProcessingError.UNAVAILABLE, True
        return AIProcessingError.UNAVAILABLE, False

    def final_code(self, last_code: str, calls_made: int, failure_codes: Sequence[str]) -> str:
        """The code reported after every attempt failed."""
        if last_code in (AIProcessingError.MISSING_API_KEY, AIProcessingError.RATE_LIMITED):
            return last_code
        if calls_made >= 3 or len(set(failure_codes)) > 1:
            return AIProcessingError.RETRIES_EXHAUSTED
        return last_code or AIProcessingError.UNAVAILABLE

    @staticmethod
    def is_rate_limited(error: BaseException) -> bool:
        status = getattr(error, "status_code", None) or getattr(error, "code", None)
        try:
            if status is not None and int(status) == 429:
                return True
        except (TypeError, ValueError):
            pass
        message = str(error).lower()
        signals = ("rate limit", "resource exhausted", "quota", "too many requests", "http error 429")
        return any(signal in message for signal in signals)
