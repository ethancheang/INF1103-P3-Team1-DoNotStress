"""RecordingDisplay: test double that remembers what it was asked to show."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from io_manager import ResultDisplay


class RecordingDisplay(ResultDisplay):
    """TEST DOUBLE for ResultDisplay."""

    def __init__(self) -> None:
        self.__shown: list[tuple[str, Any]] = []

    @property
    def shown(self) -> tuple[tuple[str, Any], ...]:
        return tuple(self.__shown)

    def display_result(self, view: Mapping[str, Any]) -> None:
        self.__shown.append(("result", dict(view)))

    def display_record(self, record: Mapping[str, Any]) -> None:
        self.__shown.append(("record", dict(record)))

    def display_list(self, records: Sequence[Mapping[str, Any]]) -> None:
        self.__shown.append(("list", [dict(record) for record in records]))

    def display_summary(self, summary: Mapping[str, Any]) -> None:
        self.__shown.append(("summary", dict(summary)))
