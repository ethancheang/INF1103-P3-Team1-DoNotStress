"""Data Manager tests: persistence, querying, filtering and failure handling.

Every test uses its own temporary folder, so no real records are touched.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from data_manager import DataStoreError, JsonRecordRepository, RecordFilter, RecordStatus
from doubles import InMemoryRecordRepository
from logic_manager import LogicManager
from sample_ai_records import HIGH_LOW_SUPPORT, LOW_STRESS, MODERATE_SLEEP_WORKLOAD


class JsonRecordRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "student_records.json"
        self.repo = JsonRecordRepository(self.path)
        logic = LogicManager()
        self.low, self.moderate, self.high = (
            logic.evaluate(record).to_record() for record in (LOW_STRESS, MODERATE_SLEEP_WORKLOAD, HIGH_LOW_SUPPORT)
        )

    def tearDown(self):
        self.folder.cleanup()

    def test_missing_and_empty_files_read_as_no_records(self):
        self.assertEqual(self.repo.load(), [])
        self.path.write_text("   ", encoding="utf-8")
        self.assertEqual(self.repo.load(), [])

    def test_records_persist_across_separate_runs(self):
        saved = self.repo.save(self.low)
        self.assertTrue(saved["record_id"])
        self.assertIn("saved_at", saved)
        reopened = JsonRecordRepository(self.path)  # a new run of the app
        self.assertEqual(reopened.load(), [saved])

    def test_reflection_text_is_never_written(self):
        self.repo.save({**self.low, "feelings_text": "very private words"})
        self.repo.save_pending({**LOW_STRESS, "feelings_text": "very private words"})
        self.assertNotIn("very private words", self.path.read_text(encoding="utf-8"))

    def test_only_ai_processed_records_are_saved_as_evaluated(self):
        for bad in ({**self.low, "source": "logic_fallback"},
                    {**self.low, "source": "", "ai_ok": False},
                    {k: v for k, v in self.low.items() if k != "risk_score"},
                    {**self.low, "confidence": 1.7},
                    {**self.low, "risk_category": ["High"]},
                    "not a record"):
            with self.subTest(record=str(bad)[:40]), self.assertRaises(DataStoreError):
                self.repo.save(bad)
        self.assertEqual(self.repo.load(), [])

    def test_pending_row_is_upgraded_not_duplicated(self):
        pending = self.repo.save_pending({**LOW_STRESS, "record_id": "abc"})
        self.assertEqual((pending["status"], pending["ai_ok"]), ("pending", False))
        self.repo.replace_pending("abc", self.low)
        records = self.repo.load()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["record_id"], "abc")
        self.assertNotIn("status", records[0])
        self.assertEqual(RecordStatus.of(records[0]), "Evaluated")

    def test_corrupt_file_is_reported_and_never_overwritten(self):
        for content in (b"{ not valid json", b'{"a": 1}', b"\xff\xfe garbage"):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                for action in (self.repo.load, lambda: self.repo.save(self.low), lambda: self.repo.save_pending(LOW_STRESS)):
                    with self.assertRaises(DataStoreError):
                        action()
                self.assertEqual(self.path.read_bytes(), content)

    def test_unwritable_location_raises_data_store_error(self):
        blocked = JsonRecordRepository(Path(self.folder.name))  # a folder, not a file
        with self.assertRaises(DataStoreError):
            blocked.save(self.low)

    def test_query_with_a_predicate_and_a_filter(self):
        for record in (self.low, self.moderate, self.high):
            self.repo.save(record)
        high = self.repo.query(lambda record: record["risk_category"] == "High")
        self.assertEqual([r["student_id"] for r in high], ["2400001"])
        cohort_25 = self.repo.query(RecordFilter(cohort_year="2025").matches)
        self.assertEqual([r["student_id"] for r in cohort_25], ["2512345"])

    def test_file_is_valid_json_after_saves(self):
        self.repo.save(self.low)
        self.repo.save(self.high)
        self.assertEqual(len(json.loads(self.path.read_text(encoding="utf-8"))), 2)


class RecordFilterTests(unittest.TestCase):
    RECORDS = [
        {"student_id": "2605581", "risk_category": "Low", "soft_label": "You're doing ok"},
        {"student_id": "2512345", "risk_category": "Moderate"},
        {"student_id": "2400001", "risk_category": "High", "soft_label": "Please reach out"},
        "not a record",
    ]

    def test_empty_filter_matches_every_record(self):
        self.assertEqual(len(RecordFilter().apply(self.RECORDS)), 3)

    def test_each_criterion(self):
        cases = {
            "student_id": ({"student_id": "558"}, ["2605581"]),
            "tier label": ({"tier": "Please reach out"}, ["2400001"]),
            "tier via category": ({"tier": "Worth a check-in"}, ["2512345"]),
            "two-digit cohort": ({"cohort_year": "26"}, ["2605581"]),
            "four-digit cohort": ({"cohort_year": "2024"}, ["2400001"]),
            "combined": ({"cohort_year": "26", "tier": "Please reach out"}, []),
        }
        for label, (criteria, expected) in cases.items():
            with self.subTest(case=label):
                found = [r["student_id"] for r in RecordFilter(**criteria).apply(self.RECORDS)]
                self.assertEqual(found, expected)

    def test_tier_names(self):
        self.assertEqual(RecordFilter.category_for("Worth a check-in"), "Moderate")
        self.assertIsNone(RecordFilter.category_for("Bogus"))
        self.assertEqual(RecordFilter.tier_for("High"), "Please reach out")


class RepositoryContractTests(unittest.TestCase):
    """Liskov Substitution: the in-memory double keeps the same contract as the JSON store."""

    def test_both_repositories_behave_the_same(self):
        record = LogicManager().evaluate(LOW_STRESS).to_record()
        with tempfile.TemporaryDirectory() as folder:
            for repo in (JsonRecordRepository(Path(folder) / "r.json"), InMemoryRecordRepository()):
                with self.subTest(repo=type(repo).__name__):
                    repo.save_pending({**LOW_STRESS, "record_id": "p1", "feelings_text": "x"})
                    repo.replace_pending("p1", record)
                    repo.save(record)
                    loaded = repo.load()
                    self.assertEqual(len(loaded), 2)
                    self.assertTrue(all("feelings_text" not in r for r in loaded))
                    self.assertEqual(loaded[0]["record_id"], "p1")


if __name__ == "__main__":
    unittest.main()
