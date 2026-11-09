"""RecordFilter: the search criteria for saved check-ins."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, ClassVar


class RecordFilter:
    """Matches stored records against optional criteria (all must match).

    * ``student_id``    - any part of the student ID
    * ``risk_category`` - "Low", "Moderate" or "High"
    * ``tier``          - a student-facing tier name, e.g. "Worth a check-in"
    * ``cohort_year``   - "26" or "2026" (the first two ID digits are the cohort)

    Empty criteria match everything. Use ``matches`` as a predicate for
    ``RecordRepository.query`` or ``apply`` on an already-loaded list.
    """

    TIER_TO_CATEGORY: ClassVar[dict[str, str]] = {
        "You're doing ok": "Low",
        "Worth a check-in": "Moderate",
        "Please reach out": "High",
    }

    def __init__(
        self,
        *,
        student_id: str = "",
        risk_category: str = "",
        tier: str = "",
        cohort_year: str = "",
    ) -> None:
        self.__student_id = str(student_id or "").strip()
        self.__risk_category = str(risk_category or "").strip()
        self.__tier = str(tier or "").strip()
        self.__cohort_year = str(cohort_year or "").strip()

    @classmethod
    def category_for(cls, tier: str) -> str | None:
        """The risk_category behind a tier name, or None for an unknown tier."""
        return cls.TIER_TO_CATEGORY.get(tier)

    @classmethod
    def tier_for(cls, category: Any) -> str | None:
        """The tier name for a risk_category, or None."""
        for tier, known in cls.TIER_TO_CATEGORY.items():
            if known == category:
                return tier
        return None

    def matches(self, record: Mapping[str, Any]) -> bool:
        if not isinstance(record, Mapping):
            return False
        student_id = str(record.get("student_id", ""))
        if self.__student_id and self.__student_id not in student_id:
            return False
        if self.__risk_category and record.get("risk_category") != self.__risk_category:
            return False
        if self.__tier and not self.__matches_tier(record):
            return False
        if self.__cohort_year and not self.__matches_cohort(student_id):
            return False
        return True

    def apply(self, records: Iterable[Mapping[str, Any]]) -> list[Any]:
        """The records that match, in their original order."""
        return [record for record in records if self.matches(record)]

    def __matches_tier(self, record: Mapping[str, Any]) -> bool:
        label = record.get("soft_label") or record.get("risk_category")
        return label == self.__tier or record.get("risk_category") == self.category_for(self.__tier)

    def __matches_cohort(self, student_id: str) -> bool:
        prefix = student_id[:2] if len(student_id) >= 2 else ""
        year = self.__cohort_year
        return prefix == year or (len(year) == 4 and student_id.startswith(year[2:]))
