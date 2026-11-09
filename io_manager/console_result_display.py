"""ConsoleResultDisplay: shows results, records and summaries in a terminal."""

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from typing import Any, TextIO

from .result_display import ResultDisplay
from .student_io import StudentIO


class ConsoleResultDisplay(ResultDisplay):
    """Plain-text output for a terminal (staff scripts and demos).

    It formats through the StudentIO it is given (association) so the
    terminal shows the same wording as the web and desktop apps. The output
    stream can be replaced, which is how the tests read what was printed.
    """

    def __init__(self, io: StudentIO, stream: TextIO | None = None) -> None:
        self.__io = io
        self.__stream = stream if stream is not None else sys.stdout

    def display_result(self, view: Mapping[str, Any]) -> None:
        soft_label = str(view.get("soft_label", ""))
        self.__write(self.__io.format_soft_label(soft_label).get("heading", soft_label))
        for item in self.__io.format_tips(view.get("tips", []))["items"]:
            self.__write(f"• {item['text']}")

    def display_record(self, record: Mapping[str, Any]) -> None:
        self.__write(str(self.__io.format_record(record)))

    def display_list(self, records: Sequence[Mapping[str, Any]]) -> None:
        for record in records:
            self.display_record(record)

    def display_summary(self, summary: Mapping[str, Any]) -> None:
        summary = self.__io.format_summary(summary)
        checkins = summary.get("checkins", {})
        self.__write(
            f"Check-ins: {checkins.get('total', 0)} "
            f"({checkins.get('evaluated', 0)} evaluated, {checkins.get('pending', 0)} pending)"
        )
        for tier in summary.get("tiers", {}).get("items", []):
            self.__write(f"  {tier['label']}: {tier['count']} ({tier['percent']}%)")
        stress = summary.get("stress", {})
        if stress.get("average_score") is not None:
            self.__write(f"Average stress score: {stress['average_score']} / 5")
        for stressor in summary.get("stressors", {}).get("items", []):
            self.__write(f"  Stressor {stressor['label']}: {stressor['count']}")
        for factor in summary.get("factors", {}).get("items", []):
            self.__write(f"  Flagged {factor['label']}: {factor['count']} ({factor['percent']}%)")

    def __write(self, text: str) -> None:
        print(text, file=self.__stream)
