"""RecordsQueryService: filter and shape saved check-ins for the admin table.

SRP: querying and presenting stored records, separate from the Data Manager
(which only loads and filters by tier/cohort) and from the HTTP route.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import survey
from data_manager import TIER_TO_CATEGORY


class RecordsQueryService:
    """Admin list of saved check-ins. Never exposes free text or keys."""

    COLUMNS = (
        "student_id",
        "stress_score",
        "risk_category",
        "soft_label",
        "pss_1",
        "pss_2",
        "pss_3",
        "pss_4",
        "sleep_hours_avg",
        "sleep_quality",
        "pas_workload",
        "pas_catchup",
        "fin_stress",
        "mspss_friends",
        "mspss_family",
        "saved_at",
        "survey_version",
    )
    PROCESSED_SOURCES = {
        "gemini",
        "ai",
        "ai_manager",
        "gemini+logic",
        "ai_logic",
    }

    def cohorts(self, records: Sequence[Mapping[str, Any]]) -> list[str]:
        return sorted(
            {
                str(item.get("student_id", ""))[:2]
                for item in records
                if len(str(item.get("student_id", ""))) >= 2
                and str(item.get("student_id", ""))[:2].isascii()
                and str(item.get("student_id", ""))[:2].isdigit()
            },
            reverse=True,
        )

    def current_version(self, records: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
        return [
            item
            for item in records
            if isinstance(item, dict) and item.get("survey_version") == survey.VERSION
        ]

    def validate_filters(self, tier: str, cohort: str) -> str | None:
        if tier and tier not in TIER_TO_CATEGORY:
            return "Choose a tier: You're doing ok, Worth a check-in, or Please reach out."
        if cohort and (len(cohort) not in (2, 4) or not cohort.isascii() or not cohort.isdigit()):
            return "Choose a valid cohort year."
        return None

    def rows(
        self,
        records: Sequence[Mapping[str, Any]],
        *,
        student_id: str = "",
        tier: str = "",
        cohort: str = "",
        store,
    ) -> list[dict[str, Any]]:
        filtered = store.filter(
            list(records),
            **{key: value for key, value in {"tier": tier, "cohort_year": cohort}.items() if value},
        )
        filtered = [item for item in filtered if student_id in str(item.get("student_id", ""))]
        rows = []
        for item in filtered:
            row = {key: item.get(key) for key in self.COLUMNS}
            if not row.get("soft_label"):
                row["soft_label"] = {
                    value: name for name, value in TIER_TO_CATEGORY.items()
                }.get(row.get("risk_category"))
            source = str(item.get("source", "")).lower()
            processed = item.get("ai_ok") is True or source in self.PROCESSED_SOURCES
            pending = str(item.get("status", "")).strip().lower() == "pending"
            row["status"] = "Pending" if pending or not processed else "Evaluated"
            rows.append(row)
        rows.sort(key=lambda row: str(row.get("saved_at") or ""), reverse=True)
        return rows
