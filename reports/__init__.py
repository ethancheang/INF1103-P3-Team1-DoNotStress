"""Staff cohort summary (Phase 2 new feature).

    CohortSummaryReport            builds the summary from saved check-ins
      '- ReportSection (abstract)  one part of the summary
           |- CheckinCountSection      total / evaluated / pending
           |- TierDistributionSection  Low / Moderate / High counts and shares
           |- StressScoreSection       average score, support-priority and safety counts
           |- StressorRankingSection   most common AI-named stressors
           '- FactorFlagSection        how often each context flag was raised

The admin "Saved records" page shows the summary for the current filters.
Each class lives in its own .py file.
"""

from .checkin_count_section import CheckinCountSection
from .cohort_summary_report import CohortSummaryReport
from .factor_flag_section import FactorFlagSection
from .report_section import ReportSection
from .stress_score_section import StressScoreSection
from .stressor_ranking_section import StressorRankingSection
from .tier_distribution_section import TierDistributionSection

__all__ = [
    "CheckinCountSection",
    "CohortSummaryReport",
    "FactorFlagSection",
    "ReportSection",
    "StressScoreSection",
    "StressorRankingSection",
    "TierDistributionSection",
]
