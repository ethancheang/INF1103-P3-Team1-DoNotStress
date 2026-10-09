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
        self.assertIs(huge_stress["ok"], True)
        self.assertEqual(huge_stress["logic_rule"], "ai_clamped")

    # -----------------------------------------------------------------------
    # Tip list size
    # -----------------------------------------------------------------------

    def test_tips_are_capped_even_when_no_rule_fires(self):
        result = lm.apply_logic(_enriched(tips=list(lm.TIPS_ALLOWLIST)))
        self.assertEqual(result["logic_rules"], [])
        self.assertEqual(len(result["tips"]), lm._MAX_TIPS)
        self.assertIn("tips", result["logic_clamp_notes"])

    def test_tips_are_capped_when_a_rule_adds_tips(self):
        result = lm.apply_logic(_enriched(
            risk_score=0.9, stress_level=9, social_support=1,
            tips=list(lm.TIPS_ALLOWLIST),
        ))
        self.assertEqual(result["soft_label"], lm.SOFT_LABEL_REACH_OUT)
        self.assertEqual(len(result["tips"]), lm._MAX_TIPS)
        self.assertEqual(result["tips"][:2], ["talk_to_someone", "feelings_check_in"])


if __name__ == "__main__":
    unittest.main()
