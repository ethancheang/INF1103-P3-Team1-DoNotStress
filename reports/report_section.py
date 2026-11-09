"""ReportSection: one part of the staff cohort summary."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from data_manager import RecordStatus
from logic_manager.field_reader import FieldReader


class ReportSection(ABC):
    """ABSTRACT CLASS for one section of the cohort summary (Strategy pattern).

    CohortSummaryReport calls ``build`` on every section in the same way and
    never checks which section it has (polymorphism), so a new section can
    be added without changing the report (Open/Closed).

    Contract every subclass keeps (Liskov Substitution):
      * ``key`` is a short, unique, fixed name for the section;
      * ``build(records)`` only reads the records, never changes them, and
        returns a JSON-ready dict;
      * it never raises for odd records (missing fields, wrong types); it
        just leaves them out of its counts.

    Shared helpers for the subclasses live here too.
    """

    @property
    @abstractmethod
    def key(self) -> str:
        """The section's name in the report, e.g. "tiers"."""

    @abstractmethod
    def build(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """This section's numbers for ``records``."""

    @staticmethod
    def _evaluated(records: Iterable[Any]) -> list[Mapping[str, Any]]:
        """The records the AI finished evaluating (pending rows have no AI fields)."""
        return [record for record in records if isinstance(record, Mapping) and RecordStatus.is_evaluated(record)]

    @staticmethod
    def _percent(part: int, whole: int) -> float:
        """``part`` as a percentage of ``whole``, to one decimal place (0.0 when empty)."""
        return round(100.0 * part / whole, 1) if whole else 0.0

    @staticmethod
    def _number(value: Any) -> float | None:
        """A finite number, or None for anything else (text, True/False, NaN)."""
        return FieldReader.to_number(value)
