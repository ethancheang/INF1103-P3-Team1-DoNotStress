"""RecordsQueryService: filters and shapes saved check-ins for the admin table."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from data_manager import RecordFilter, RecordStatus
from survey import Questionnaire


class RecordsQueryService:
    """The admin list of saved check-ins. Never exposes free text or keys.

    SRP: choosing which stored records the admin page shows, and in what
    shape. Loading belongs to the Data Manager and HTTP to CampusApp.
    """

    COLUMNS: ClassVar[tuple[str, ...]] = (
        "student_id", "stress_score", "risk_category", "soft_label",
        "pss_1", "pss_2", "pss_3", "pss_4", "sleep_hours_avg", "sleep_quality",
        "pas_workload", "pas_catchup", "fin_stress", "mspss_friends", "mspss_family",
        "saved_at", "survey_version",
    )
    TIER_MESSAGE: ClassVar[str] = "Choose a tier: You're doing ok, Worth a check-in, or Please reach out."
    COHORT_MESSAGE: ClassVar[str] = "Choose a valid cohort year."

    def current_version(self, records: Sequence[Any]) -> list[dict[str, Any]]:
        """Only records from the current questionnaire (older scales are skipped)."""
        return [item for item in records if isinstance(item, dict) and item.get("survey_version") == Questionnaire.VERSION]

    def cohorts(self, records: Sequence[Mapping[str, Any]]) -> list[str]:
        """The two-digit cohort years present, newest first."""
        prefixes = {str(item.get("student_id", ""))[:2] for item in records}
        return sorted((prefix for prefix in prefixes if len(prefix) == 2 and prefix.isascii() and prefix.isdigit()),
                      reverse=True)

    def validate_filters(self, tier: str, cohort: str) -> str | None:
        """A message for an unknown tier or a malformed cohort year, else None."""
        if tier and RecordFilter.category_for(tier) is None:
            return self.TIER_MESSAGE
        if cohort and (len(cohort) not in (2, 4) or not cohort.isascii() or not cohort.isdigit()):
            return self.COHORT_MESSAGE
        return None

    def matching(
        self, records: Sequence[Mapping[str, Any]], *, student_id: str = "", tier: str = "", cohort: str = ""
    ) -> list[Any]:
        """The records that match the admin's search and filters."""
        return RecordFilter(student_id=student_id, tier=tier, cohort_year=cohort).apply(records)

    def rows(self, records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """One table row per record (allow-listed columns + status), newest first."""
        rows = []
        for item in records:
            row = {key: item.get(key) for key in self.COLUMNS}
            if not row.get("soft_label"):
                row["soft_label"] = RecordFilter.tier_for(row.get("risk_category"))
            row["status"] = RecordStatus.of(item)
            rows.append(row)
        rows.sort(key=lambda row: str(row.get("saved_at") or ""), reverse=True)
        return rows
