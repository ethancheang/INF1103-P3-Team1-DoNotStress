"""I/O Manager tests: input validation (invalid user input) and output formatting."""

from __future__ import annotations

import io
import unittest

from io_manager import ConsoleResultDisplay, StudentFormValidator, StudentIO
from survey import Questionnaire

VALID_FORM = {
    "student_id": "2605581",
    "feelings_text": "",
    "pss_1": "2", "pss_2": "4", "pss_3": "4", "pss_4": "2",
    "sleep_hours_avg": "7.5", "sleep_quality": "2",
    "pas_workload": "2", "pas_catchup": "2",
    "fin_stress": "2",
    "mspss_friends": "4", "mspss_family": "5",
}


class FormValidationTests(unittest.TestCase):
    def setUp(self):
        self.io = StudentIO()

    def test_valid_form_becomes_a_clean_record(self):
        ok, record = self.io.validate_form(VALID_FORM)
        self.assertTrue(ok)
        self.assertEqual(record["pss_1"], 2)
        self.assertEqual(record["sleep_hours_avg"], 7.5)
        self.assertEqual(record["survey_version"], Questionnaire.VERSION)
        self.assertFalse(record["safety_flag"])

    def test_every_problem_is_reported_at_once(self):
        form = {**VALID_FORM, "student_id": "12345", "pss_1": "", "sleep_hours_avg": "7.25", "fin_stress": "9"}
        ok, errors = self.io.validate_form(form)
        self.assertFalse(ok)
        self.assertEqual(set(errors), {"student_id", "pss_1", "sleep_hours_avg", "fin_stress"})

    def test_invalid_student_ids(self):
        for bad in ("", None, "1605581", "26055812", "26O5581", "2٦٠٥٥٨١", "abc"):
            with self.subTest(student_id=bad):
                self.assertFalse(self.io.validate_student_id(bad)[0])
        self.assertEqual(self.io.validate_student_id(" 2605581 "), (True, "2605581"))

    def test_invalid_answer_types(self):
        for bad in (True, [], {}, "three", "nan", "inf", 0, 6, 2.5):
            with self.subTest(value=bad):
                ok, errors = self.io.validate_form({**VALID_FORM, "pss_2": bad})
                self.assertFalse(ok)
                self.assertIn("pss_2", errors)

    def test_reflection_limit_and_safety_flag(self):
        self.assertFalse(self.io.validate_form({**VALID_FORM, "feelings_text": "x" * 2001})[0])
        ok, record = self.io.validate_form({**VALID_FORM, "feelings_text": "I don't want to live like this"})
        self.assertTrue(ok)
        self.assertTrue(record["safety_flag"])

    def test_not_a_form(self):
        self.assertEqual(self.io.validate_form("nope"), (False, {"form": StudentFormValidator.FORM_MESSAGE}))


class FormattingTests(unittest.TestCase):
    def setUp(self):
        self.io = StudentIO()

    def test_unknown_tips_and_labels_fall_back_safely(self):
        tips = self.io.format_tips(["short_breaks", "invented_tip"])
        self.assertEqual([item["id"] for item in tips["items"]], ["short_breaks"])
        self.assertEqual(self.io.format_soft_label("bogus")["heading"], "Worth a check-in")

    def test_advisor_panel_always_has_the_contacts(self):
        for prominence in ("low", "medium", "high", "unexpected"):
            with self.subTest(prominence=prominence):
                panel = self.io.format_advisor(prominence)
                self.assertEqual(panel["helpline"], "6592 2030")
                self.assertIn("heading", panel)

    def test_ai_error_copy(self):
        copy = self.io.format_ai_error("rate_limited")
        self.assertEqual(copy["speak_to_advisor"]["prominence"], "high")
        self.assertEqual(self.io.format_ai_error("unknown")["body"], StudentIO.AI_ERROR_HINTS["unavailable"])

    def test_returned_copy_cannot_change_the_shared_wording(self):
        self.io.format_soft_label("Please reach out")["heading"] = "changed"
        self.assertEqual(self.io.format_soft_label("Please reach out")["heading"], "Please reach out")

    def test_summary_labels(self):
        summary = {"tiers": {"items": [{"category": "High", "soft_label": "Please reach out", "count": 1, "percent": 50.0}]},
                   "stressors": {"items": [{"id": "academic_overload", "count": 2}, {"id": "new_one", "count": 1}]},
                   "factors": {"items": [{"id": "sleep", "count": 1, "percent": 50.0}]}}
        labelled = self.io.format_summary(summary)
        self.assertEqual(labelled["tiers"]["items"][0]["label"], "Please reach out")
        self.assertEqual([s["label"] for s in labelled["stressors"]["items"]], ["Academic overload", "New one"])
        self.assertEqual(labelled["factors"]["items"][0]["label"], "Rest & recovery")
        self.assertNotIn("label", summary["stressors"]["items"][0])  # the input is not changed


class ConsoleDisplayTests(unittest.TestCase):
    def test_terminal_output(self):
        stream = io.StringIO()
        display = ConsoleResultDisplay(StudentIO(), stream=stream)
        display.display_result({"soft_label": "Please reach out", "tips": ["talk_to_someone"]})
        display.display_list([{"student_id": "2605581", "risk_category": "Low", "reasoning": "r"}])
        display.display_summary({"checkins": {"total": 2, "evaluated": 1, "pending": 1}, "stress": {"average_score": 3.0}})
        text = stream.getvalue()
        self.assertIn("Please reach out", text)
        self.assertIn("• Reach out to a friend", text)
        self.assertIn("2605581", text)
        self.assertIn("Check-ins: 2 (1 evaluated, 1 pending)", text)
        self.assertIn("Average stress score: 3.0 / 5", text)


if __name__ == "__main__":
    unittest.main()
