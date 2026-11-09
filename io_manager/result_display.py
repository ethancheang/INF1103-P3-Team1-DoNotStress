"""ResultDisplay: the contract for showing results, records, lists and summaries."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping, Sequence
from typing import Any


class ResultDisplay(ABC):
    """INTERFACE for an output channel (terminal, test recorder, ...).

    Domain classes never print. They hand plain dicts to a ResultDisplay,
    so terminal output stays separate from domain logic, and any display
    can be swapped for another (Liskov Substitution).
    """

    @abstractmethod
    def display_result(self, view: Mapping[str, Any]) -> None:
        """Show one student's result (``EvaluationResult.to_display()``)."""

    @abstractmethod
    def display_record(self, record: Mapping[str, Any]) -> None:
        """Show one stored record."""

    @abstractmethod
    def display_list(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Show a list of stored records."""

    @abstractmethod
    def display_summary(self, summary: Mapping[str, Any]) -> None:
        """Show a cohort summary report (``CohortSummaryReport.build()``)."""
