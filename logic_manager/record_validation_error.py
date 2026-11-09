"""RecordValidationError: the AI-enriched record is incomplete or unusable."""

from __future__ import annotations

from collections.abc import Iterable

from .logic_manager_error import LogicManagerError


class RecordValidationError(LogicManagerError):
    """The record from ai_manager is missing fields or has unusable values."""

    code = "ai_fields_required"

    def __init__(self, missing: Iterable[str] = (), invalid: Iterable[str] = ()) -> None:
        self._missing = tuple(missing)
        self._invalid = tuple(invalid)
        details = []
        if self._missing:
            details.append("missing " + ", ".join(self._missing))
        if self._invalid:
            details.append("unusable " + ", ".join(self._invalid))
        super().__init__(
            "Logic needs a complete AI-enriched record ("
            + ("; ".join(details) or "no details")
            + ")."
        )

    @property
    def missing(self) -> tuple[str, ...]:
        """Keys that were not in the record."""
        return self._missing

    @property
    def invalid(self) -> tuple[str, ...]:
        """Keys that were present but held a value Logic cannot use."""
        return self._invalid
