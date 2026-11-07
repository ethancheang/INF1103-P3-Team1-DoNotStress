"""ResultPresenter: student-facing view of one evaluated check-in.

Keeps presentation separate from the pipeline and the managers (SRP).
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import survey
from io_manager import StudentIO


class ResultPresenter:
    """Only send allow-listed, student-facing copy to the browser."""

    def __init__(self, io: StudentIO) -> None:
        self._io = io

    def build(self, record: Mapping[str, Any], saved: bool = False) -> dict[str, Any]:
        advisor = self._io.format_advisor(record["speak_prominence"])
        advisor.pop("cta", None)
        return {
            "soft": self._io.format_soft_label(record["soft_label"]),
            "tips": self._io.format_tips(record["tips"]),
            "advisor": advisor,
            "saved": saved,
            "insights": {
                "risk_category": record.get("risk_category", "Unknown"),
                "explanation": str(record.get("reasoning", "")).split(" Logic adjusted:")[0],
                "stressors": record.get("primary_stressors", []),
                "survey_version": record.get("survey_version", "legacy"),
                "stress_score": record.get("stress_score"),
                "support_mean": record.get("support_mean"),
                "context_flags": record.get("context_flags", {}),
                "factors": record.get("factor_insights", []),
                "safety_flag": record.get("safety_flag", False),
                "snapshot": {
                    key: record.get(key)
                    for key in (
                        "sleep_hours",
                        "stress_level",
                        "academic_workload",
                        "financial_stress",
                        "social_support",
                        *survey.QUESTION_MAP,
                    )
                },
            },
        }
