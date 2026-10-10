"""Unit tests for logic_manager under the standardised 1.0-5.0 design."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logic_manager as lm


def _enriched(**overrides):
    """Calm, valid AI-enriched record on the 1.0-5.0 scale."""
    record = {
        "student_id": "2605581",
        "pss_1": 2,
        "pss_2": 2,
        "pss_3": 2,
        "pss_4": 2,
        "sleep_hours_avg": 7.5,
        "sleep_quality": 1,
        "pas_workload": 3,
        "fin_stress": 8,
        "mspss_friends": 6,
        "mspss_family": 6,
        "perceived_stress_score": 2.0,
        "explanation": "You seem to be handling your academic routine with manageable levels of stress.",
        "tips": ["sleep_routine", "short_breaks"],
    }
    record.update(overrides)
    return record


class LogicOutcomeTests(unittest.TestCase):

    # -----------------------------------------------------------------------
    # 1. Reference score calculation (average of 4 PSS items, 1.0-5.0)
    # -----------------------------------------------------------------------

    def test_compute_reference_score_extremes(self):
        self.assertAlmostEqual(lm.compute_reference_score({"pss_1": 1, "pss_2": 1, "pss_3": 1, "pss_4": 1}), 1.0)
        self.assertAlmostEqual(lm.compute_reference_score({"pss_1": 5, "pss_2": 5, "pss_3": 5, "pss_4": 5}), 5.0)
        self.assertAlmostEqual(lm.compute_reference_score({"pss_1": 2, "pss_2": 3, "pss_3": 4, "pss_4": 5}), 3.5)

    # -----------------------------------------------------------------------
    # 2. Tier assignment (below 2.5: ok; 2.5-3.5: check-in; above 3.5: reach out)
    # -----------------------------------------------------------------------

    def test_assign_tier_boundaries(self):
        self.assertEqual(lm.assign_tier(1.0), lm.TIER_OK)
        self.assertEqual(lm.assign_tier(2.4), lm.TIER_OK)
        self.assertEqual(lm.assign_tier(2.5), lm.TIER_CHECK_IN)
        self.assertEqual(lm.assign_tier(3.0), lm.TIER_CHECK_IN)
        self.assertEqual(lm.assign_tier(3.5), lm.TIER_CHECK_IN)
        self.assertEqual(lm.assign_tier(3.51), lm.TIER_REACH_OUT)
        self.assertEqual(lm.assign_tier(5.0), lm.TIER_REACH_OUT)

    # -----------------------------------------------------------------------
    # 3. Cross-check score with SCORE_TOLERANCE = 0.5
    # -----------------------------------------------------------------------

    def test_cross_check_score_within_tolerance(self):
        score, mismatch = lm.cross_check_score(ai_score=2.8, reference=3.0)
        self.assertAlmostEqual(score, 2.8)
        self.assertFalse(mismatch)

        score, mismatch = lm.cross_check_score(ai_score=3.5, reference=3.0)
        self.assertAlmostEqual(score, 3.5)
        self.assertFalse(mismatch)

    def test_cross_check_score_exceeds_tolerance(self):
        score, mismatch = lm.cross_check_score(ai_score=4.0, reference=3.0)
        self.assertAlmostEqual(score, 3.0)
        self.assertTrue(mismatch)

        score, mismatch = lm.cross_check_score(ai_score=1.5, reference=3.0)
        self.assertAlmostEqual(score, 3.0)
        self.assertTrue(mismatch)

    # -----------------------------------------------------------------------
    # 4. Pipeline integration: apply_logic
    # -----------------------------------------------------------------------

    def test_apply_logic_within_tolerance_uses_ai_score(self):
        record = _enriched(
            pss_1=2, pss_2=2, pss_3=2, pss_4=2,  # reference = 2.0
            perceived_stress_score=2.3,           # diff = 0.3 <= 0.5
        )
        res = lm.apply_logic(record)
        self.assertTrue(res["ok"])
        self.assertEqual(res["score_source"], "ai")
        self.assertFalse(res["score_mismatch"])
        self.assertAlmostEqual(res["perceived_stress_score"], 2.3)
        self.assertEqual(res["soft_label"], lm.TIER_OK)

    def test_apply_logic_mismatch_uses_reference_score(self):
        record = _enriched(
            pss_1=2, pss_2=2, pss_3=2, pss_4=2,  # reference = 2.0
            perceived_stress_score=4.0,           # diff = 2.0 > 0.5
        )
        res = lm.apply_logic(record)
        self.assertTrue(res["ok"])
        self.assertEqual(res["score_source"], "reference")
        self.assertTrue(res["score_mismatch"])
        self.assertAlmostEqual(res["perceived_stress_score"], 2.0)
        self.assertEqual(res["soft_label"], lm.TIER_OK)

    # -----------------------------------------------------------------------
    # 5. Rule removal: 2+ context flags do NOT raise the tier
    # -----------------------------------------------------------------------

    def test_context_flags_do_not_raise_tier(self):
        # Stress is low (reference = 1.0, AI = 1.0 -> tier = 'You\'re doing ok')
        # But sleep, workload, and finance are all flagged (3 flags)
        record = _enriched(
            pss_1=1, pss_2=1, pss_3=1, pss_4=1,
            perceived_stress_score=1.0,
            sleep_hours_avg=4.0, sleep_quality=3,  # sleep flagged
            pas_workload=5,                         # workload flagged
            fin_stress=2,                           # finance flagged
        )
        res = lm.apply_logic(record)
        self.assertTrue(res["context_flags"]["sleep"])
        self.assertTrue(res["context_flags"]["workload"])
        self.assertTrue(res["context_flags"]["finances"])
        # Crucial: tier must NOT be raised to "Worth a check-in"
        self.assertEqual(res["soft_label"], lm.TIER_OK)

    # -----------------------------------------------------------------------
    # 6. Safety override: crisis language still gives "Please reach out"
    # -----------------------------------------------------------------------

    def test_crisis_language_safety_override(self):
        record = _enriched(
            pss_1=1, pss_2=1, pss_3=1, pss_4=1,
            perceived_stress_score=1.0,
            feelings_text="I want to kill myself",
        )
        res = lm.apply_logic(record)
        self.assertTrue(res["safety_flag"])
        self.assertEqual(res["soft_label"], lm.TIER_REACH_OUT)
        self.assertEqual(res["speak_prominence"], "high")

    # -----------------------------------------------------------------------
    # 7. Safe handling of missing / invalid inputs
    # -----------------------------------------------------------------------

    def test_missing_pss_or_ai_fields_handled_gracefully(self):
        record = _enriched()
        del record["pss_1"]
        res = lm.apply_logic(record)
        self.assertFalse(res["ok"])
        self.assertIn("pss_1", res["missing"])

        record = _enriched()
        del record["perceived_stress_score"]
        res = lm.apply_logic(record)
        self.assertFalse(res["ok"])
        self.assertIn("perceived_stress_score", res["missing"])


if __name__ == "__main__":
    unittest.main()
