"""AIProcessingError: the AI Manager could not give a usable result."""

from __future__ import annotations

from typing import ClassVar


class AIProcessingError(Exception):
    """Raised when Gemini's analysis cannot be used for this check-in.

    ``code`` is one short, fixed string that the I/O Manager turns into a
    student-facing message. The AI Manager never invents a result instead:
    the caller saves the check-in as pending and asks the student to retry.
    """

    MISSING_API_KEY: ClassVar[str] = "missing_api_key"
    TIMEOUT: ClassVar[str] = "timeout"
    INVALID_RESPONSE: ClassVar[str] = "invalid_response"
    RETRIES_EXHAUSTED: ClassVar[str] = "retries_exhausted"
    RATE_LIMITED: ClassVar[str] = "rate_limited"
    UNAVAILABLE: ClassVar[str] = "unavailable"
    CODES: ClassVar[tuple[str, ...]] = (
        MISSING_API_KEY, TIMEOUT, INVALID_RESPONSE, RETRIES_EXHAUSTED, RATE_LIMITED, UNAVAILABLE,
    )

    def __init__(self, code: str, detail: str = "") -> None:
        self.__code = code if code in self.CODES else self.UNAVAILABLE
        self.__detail = detail
        super().__init__(f"{self.__code}: {detail}" if detail else self.__code)

    @property
    def code(self) -> str:
        """One of ``CODES``; unknown codes become ``unavailable``."""
        return self.__code

    @property
    def detail(self) -> str:
        """Technical detail for the log (never shown to the student)."""
        return self.__detail
