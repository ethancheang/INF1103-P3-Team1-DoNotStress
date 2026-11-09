"""New feature tests: the staff cohort summary report."""

from __future__ import annotations

import copy
import unittest

from logic_manager import LogicManager
from reports import (
    CheckinCountSection,
    CohortSummaryReport,
    FactorFlagSection,
    ReportSection,
    StressorRankingSection,
    StressScoreSection,
    TierDistributionSection,
)
from sample_ai_records import HIGH_LOW_SUPPORT, LOW_STRESS, MODERATE_SLEEP_WORKLOAD, SAFETY_FLAGGED

PENDING = {"student_id": "2600009", "status": "pending", "ai_ok": False, "survey_version": "evidence-v3"}


class CohortSummaryTests(unittest.TestCase):
    def setUp(self):
        logic = LogicManager()
        self.records = [logic.evaluate(r).to_record()
                        for r in (LOW_STRESS, MODERATE_SLEEP_WORKLOAD, HIGH_LOW_SUPPORT, SAFETY_FLAGGED)]
        self.records.append(dict(PENDING))
        self.summary = CohortSummaryReport().build(self.records)

    def test_counts_split_evaluated_and_pending(self):
        self.assertEqual(self.summary["checkins"], {"total": 5, "evaluated": 4, "pending": 1})

    def test_tier_distribution_uses_the_final_tier(self):
        tiers = {item["category"]: (item["count"], item["percent"]) for item in self.summary["tiers"]["items"]}
        # the safety-flagged low scorer is raised to High by the safety override rule
        self.assertEqual(tiers, {"Low": (1, 25.0), "Moderate": (1, 25.0), "High": (2, 50.0)})

    def test_average_score_and_attention_counts(self):
        self.assertEqual(self.summary["stress"],
                         {"average_score": 2.91, "scored": 4, "support_priority": 1, "safety_flags": 1})

    def test_top_stressors_are_ranked(self):
        self.assertEqual(self.summary["stressors"]["items"][:2],
                         [{"id": "academic_overload", "count": 2}, {"id": "sleep_deprivation", "count": 2}])

    def test_factor_flags(self):
        factors = {item["id"]: item["count"] for item in self.summary["factors"]["items"]}
        self.assertEqual(factors, {"sleep": 2, "workload": 2, "finances": 1, "support": 1})

    def test_empty_and_odd_input_never_crashes(self):
        empty = CohortSummaryReport().build([])
        self.assertEqual(empty["checkins"], {"total": 0, "evaluated": 0, "pending": 0})
        self.assertIsNone(empty["stress"]["average_score"])
        odd = [{"ai_ok": True, "stress_score": "not a number", "primary_stressors": "oops", "context_flags": []}, "x"]
        self.assertEqual(CohortSummaryReport().build(odd)["stress"]["average_score"], None)

    def test_the_records_are_not_changed(self):
        before = copy.deepcopy(self.records)
        CohortSummaryReport().build(self.records)
        self.assertEqual(self.records, before)


class ReportDesignTests(unittest.TestCase):
    def test_every_section_keeps_the_shared_contract(self):
        """Liskov Substitution: any section can stand in for any other."""
        records = [LogicManager().evaluate(LOW_STRESS).to_record(), PENDING]
        for section in CohortSummaryReport.default_sections():
            with self.subTest(section=type(section).__name__):
                self.assertIsInstance(section, ReportSection)
                self.assertIsInstance(section.build(records), dict)
                self.assertEqual(section.build(records), section.build(records))

    def test_a_new_section_plugs_in_without_changing_the_report(self):
        """Open/Closed: extend the report by passing a new ReportSection."""

        class PendingStudentsSection(ReportSection):
            @property
            def key(self):
                return "pending_students"

            def build(self, records):
                return {"ids": [r["student_id"] for r in records if r not in self._evaluated(records)]}

        report = CohortSummaryReport((CheckinCountSection(), PendingStudentsSection()))
        self.assertEqual(report.build([PENDING])["pending_students"], {"ids": ["2600009"]})

    def test_sections_must_be_valid(self):
        with self.assertRaises(TypeError):
            CohortSummaryReport(["not a section"])
        with self.assertRaises(ValueError):
            CohortSummaryReport((TierDistributionSection(), TierDistributionSection()))
        with self.assertRaises(ValueError):
            StressorRankingSection(top=0)

    def test_section_keys(self):
        keys = [s.key for s in (CheckinCountSection(), TierDistributionSection(), StressScoreSection(),
                                StressorRankingSection(), FactorFlagSection())]
        self.assertEqual(keys, ["checkins", "tiers", "stress", "stressors", "factors"])


if __name__ == "__main__":
    unittest.main()
