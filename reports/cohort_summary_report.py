"""CohortSummaryReport: the staff overview of saved check-ins (Phase 2 new feature)."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from .checkin_count_section import CheckinCountSection
from .factor_flag_section import FactorFlagSection
from .report_section import ReportSection
from .stress_score_section import StressScoreSection
from .stressor_ranking_section import StressorRankingSection
from .tier_distribution_section import TierDistributionSection


class CohortSummaryReport:
    """Summarises a set of saved check-ins for SIT wellbeing staff.

    Problem it solves: in Phase 1 staff could only read the records table
    row by row. The summary shows at a glance how many students in the
    current filter (for example one cohort year) are in each tier, the
    average stress score, the most common stressors and which factors are
    flagged most, so staff can spot a cohort that needs outreach.

    Relationships: the sections are created outside and handed in, or the
    default ones are used (aggregation). Each section is a ReportSection,
    and the report calls them all the same way (polymorphism).
    """

    def __init__(self, sections: Iterable[ReportSection] | None = None) -> None:
        self.__sections = tuple(sections) if sections is not None else self.default_sections()
        if not all(isinstance(section, ReportSection) for section in self.__sections):
            raise TypeError("Every section must be a ReportSection.")
        keys = [section.key for section in self.__sections]
        if len(keys) != len(set(keys)):
            raise ValueError("Every section needs a different key.")

    @staticmethod
    def default_sections() -> tuple[ReportSection, ...]:
        return (
            CheckinCountSection(),
            TierDistributionSection(),
            StressScoreSection(),
            StressorRankingSection(),
            FactorFlagSection(),
        )

    @property
    def sections(self) -> tuple[ReportSection, ...]:
        return self.__sections

    def build(self, records: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        """One JSON-ready dict with a key per section."""
        rows = list(records)
        return {section.key: section.build(rows) for section in self.__sections}
