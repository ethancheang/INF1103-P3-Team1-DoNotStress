"""RetryPolicy: how many times, on which models and how long to wait between AI calls."""

from __future__ import annotations

import time
from typing import ClassVar


class RetryPolicy:
    """Retry limits, model fallback order and exponential back-off.

    Each model is tried up to ``tries_per_model()`` times (at most 3), and
    one check-in never makes more than ``MAX_TOTAL_CALLS`` calls in total.
    """

    MODEL_CHAIN: ClassVar[tuple[str, ...]] = (
        "gemini-3.6-flash",
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3-flash-preview",
        "gemini-3.8-flash",
    )
    DEFAULT_MODEL: ClassVar[str] = MODEL_CHAIN[0]
    MAX_TOTAL_CALLS: ClassVar[int] = 6
    MAX_TRIES_PER_MODEL: ClassVar[int] = 3
    MAX_BACKOFF_SECONDS: ClassVar[float] = 8.0

    def __init__(self, max_attempts: int = 3, retry_delay_sec: float = 0.5) -> None:
        self.__max_attempts = max_attempts
        self.__retry_delay_sec = retry_delay_sec

    def models_for(self, model_name: str) -> tuple[str, ...]:
        """``model_name`` first, then the rest of the fallback chain."""
        if model_name in self.MODEL_CHAIN:
            return self.MODEL_CHAIN[self.MODEL_CHAIN.index(model_name):]
        return (model_name, *self.MODEL_CHAIN)

    def tries_per_model(self) -> int:
        return max(1, min(self.__max_attempts, self.MAX_TRIES_PER_MODEL))

    def has_budget(self, calls_made: int) -> bool:
        return calls_made < self.MAX_TOTAL_CALLS

    def backoff_seconds(self, attempt: int) -> float:
        """0.5 s, 1 s, 2 s ... (doubling, capped) before the next try on the same model."""
        return min(self.__retry_delay_sec * (2 ** (attempt - 1)), self.MAX_BACKOFF_SECONDS)

    def wait(self, attempt: int) -> None:
        time.sleep(self.backoff_seconds(attempt))
