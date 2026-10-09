"""Extra tests for logic_manager."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logic_manager as lm


OK_LABEL = "You're doing ok"


def _enriched(**overrides):
    """A calm, valid AI-enriched record; each test overrides only what it needs."""
    record = {
        "student_id": "2605581",
        "sleep_hours": 8.0,
        "stress_level": 3,
        "academic_workload": 4,
        "financial_stress": 2,
        "social_support": 8,
        "risk_score": 0.22,
        "risk_category": "Low",
        "primary_stressors": ["high_stress"],
        "confidence": 0.80,
        "reasoning": "Signals look steady overall.",
        "soft_label": OK_LABEL,
        "tips": ["sleep_routine", "short_breaks"],
        "speak_prominence": "low",
    }
    record.update(overrides)
    return record


class LogicOutcomeTests(unittest.TestCase):

    # -----------------------------------------------------------------------
    # Safe handling of the caller's data
    # -----------------------------------------------------------------------

    def test_huge_numbers_are_handled_without_a_crash(self):
        bad_score = lm.apply_logic(_enriched(risk_score=10 ** 400))
        self.assertIs(bad_score["ok"], False)
        self.assertIn("risk_score", bad_score["invalid"])

        huge_stress = lm.apply_logic(_enriched(stress_level=10 ** 400))
        self.assertIs(huge_stress["ok"], False)
        self.assertIn("stress_level", huge_stress["invalid"])

    def test_stress_level_is_required(self):
        record = _enriched()
        del record["stress_level"]
        result = lm.apply_logic(record)
        self.assertIs(result["ok"], False)
        self.assertIn("stress_level", result["missing"])

    def test_out_of_range_answers_are_clamped(self):
        result = lm.apply_logic(_enriched(stress_level=50))
        self.assertEqual(result["stress_score_pss4"], 16)
        self.assertEqual(result["soft_label"], lm.SOFT_LABEL_REACH_OUT)

    # -----------------------------------------------------------------------
    # a. Stress band (stress_level mapped onto PSS-4 0–16)
    # -----------------------------------------------------------------------

    def test_stress_band_boundaries(self):
        expected = {
            1: OK_LABEL, 5: OK_LABEL,
            6: lm.SOFT_LABEL_CHECK_IN, 7: lm.SOFT_LABEL_CHECK_IN,
            8: lm.SOFT_LABEL_REACH_OUT, 10: lm.SOFT_LABEL_REACH_OUT,
        }
        for stress, label in expected.items():
            with self.subTest(stress_level=stress):
                result = lm.apply_logic(_enriched(stress_level=stress))
                self.assertEqual(result["soft_label"], label)
                self.assertEqual(result["logic_rule"], "stress_band")

    def test_prominence_and_category_follow_the_label(self):
        result = lm.apply_logic(_enriched(stress_level=9))
        self.assertEqual(result["speak_prominence"], "high")
        self.assertEqual(result["risk_category"], "High")

    # -----------------------------------------------------------------------
    # b. Context flags
    # -----------------------------------------------------------------------

    def test_each_flag_threshold(self):
        cases = [
            ("sleep_hours", 5.5, 6.0, "sleep"),
            ("academic_workload", 8, 7, "workload"),
            ("financial_stress", 7, 6, "finance"),
            ("social_support", 3, 4, "support"),
        ]
        for field, raises, stays_off, flag in cases:
            with self.subTest(field=field):
                on = lm.apply_logic(_enriched(**{field: raises}))
                off = lm.apply_logic(_enriched(**{field: stays_off}))
                self.assertEqual(on["logic_flags"], [flag])
                self.assertEqual(off["logic_flags"], [])

    def test_one_flag_does_not_change_the_label(self):
        result = lm.apply_logic(_enriched(sleep_hours=4))
        self.assertEqual(result["soft_label"], OK_LABEL)
        self.assertEqual(result["tips"][0], "sleep_routine")

    def test_two_flags_raise_ok_to_check_in(self):
        result = lm.apply_logic(_enriched(sleep_hours=4, financial_stress=9))
        self.assertEqual(result["soft_label"], lm.SOFT_LABEL_CHECK_IN)
        self.assertEqual(result["logic_rule"], "context_flags")
        self.assertEqual(result["tips"][:2], ["sleep_routine", "money_worries"])

    def test_flags_alone_never_reach_out(self):
        result = lm.apply_logic(_enriched(
            stress_level=7, sleep_hours=3, academic_workload=10,
            financial_stress=10, social_support=1,
        ))
        self.assertEqual(len(result["logic_flags"]), 4)
        self.assertEqual(result["soft_label"], lm.SOFT_LABEL_CHECK_IN)

    # -----------------------------------------------------------------------
    # c. Crisis-language safety override
    # -----------------------------------------------------------------------

    def test_crisis_language_forces_reach_out(self):
        for text in (
            "I keep thinking about suicide",
            "honestly I don’t want to live like this",
            "I've been hurting myself",
            "everyone would be better off dead without me",
            "i wanna die",
        ):
            with self.subTest(text=text):
                result = lm.apply_logic(_enriched(feelings_text=text))
                self.assertIs(result["crisis_language"], True)
                self.assertEqual(result["soft_label"], lm.SOFT_LABEL_REACH_OUT)
                self.assertEqual(result["logic_rule"], "crisis_language")
                self.assertEqual(result["tips"][:2], ["talk_to_someone", "feelings_check_in"])

    def test_ordinary_text_does_not_change_the_label(self):
        result = lm.apply_logic(_enriched(
            feelings_text="Exams are killing me and I'm dying to finish this module.",
        ))
        self.assertIs(result["crisis_language"], False)
        self.assertEqual(result["soft_label"], OK_LABEL)
        for text in ("Cut myself some slack this week", "it hurt my self-esteem"):
            with self.subTest(text=text):
                self.assertIs(lm.apply_logic(_enriched(feelings_text=text))["crisis_language"], False)

    # -----------------------------------------------------------------------
    # d. Gemini may raise the label, never lower it
    # -----------------------------------------------------------------------

    def test_ai_can_raise_the_label(self):
        result = lm.apply_logic(_enriched(
            soft_label=lm.SOFT_LABEL_REACH_OUT, speak_prominence="high",
        ))
        self.assertEqual(result["soft_label"], lm.SOFT_LABEL_REACH_OUT)
        self.assertEqual(result["logic_rule"], "ai_raised")

    def test_ai_cannot_lower_the_label(self):
        result = lm.apply_logic(_enriched(stress_level=9))  # AI said "ok"
        self.assertEqual(result["soft_label"], lm.SOFT_LABEL_REACH_OUT)
        self.assertEqual(result["speak_prominence"], "high")

    # -----------------------------------------------------------------------
    # Tip list size
    # -----------------------------------------------------------------------

    def test_tips_are_capped_when_no_flag_fires(self):
        result = lm.apply_logic(_enriched(tips=list(lm.TIPS_ALLOWLIST)))
        self.assertEqual(result["logic_flags"], [])
        self.assertEqual(len(result["tips"]), lm._MAX_TIPS)
        self.assertIn("tips", result["logic_clamp_notes"])

    def test_tips_are_capped_when_logic_adds_tips(self):
        result = lm.apply_logic(_enriched(
            stress_level=9, social_support=1, tips=list(lm.TIPS_ALLOWLIST),
        ))
        self.assertEqual(result["soft_label"], lm.SOFT_LABEL_REACH_OUT)
        self.assertEqual(len(result["tips"]), lm._MAX_TIPS)
        self.assertEqual(
            result["tips"][:3],
            ["talk_to_someone", "feelings_check_in", "keep_social_contact"],
        )


if __name__ == "__main__":
    unittest.main()
