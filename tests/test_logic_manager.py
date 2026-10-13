"""Tests for logic_manager: Logic validates Gemini's analysis, not replaces it.

No real Gemini call: the AI fields come from a fake generate_fn run through
ai_manager's own validation, or are written by hand for disagreement cases.
"""

from __future__ import annotations

import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_manager
import logic_manager as lm


def _answers(**changes):
    """All-3 answers with 6.5 h sleep: scored 3 each, average 3.0 (Moderate)."""
    answers = {key: 3 for key in lm.ANSWER_KEYS}
    answers["sleep_hours_avg"] = 6.5
    answers.update(changes)
    return answers


def _fake_generate_fn(**overrides):
    """A fake Gemini that replays the formula on the prompt's answers."""
    def generate(prompt, api_key, model_name):
        answers = json.loads(prompt[prompt.rfind("{"):])
        scored, stress = ai_manager.expected_stress_score(answers)
        category = ai_manager._category_for_stress_score(stress)
        reply = {
            "scored_items": scored,
            "stress_score": stress,
            "risk_category": category,
            "primary_stressors": ["academic_overload"],
            "confidence": 0.8,
            "reasoning": "Gemini reasoning for the student.",
            "soft_label": lm._CATEGORY_TO_LABEL[category],
            "tips": ["short_breaks", "rest_a_little_more"],
            "speak_prominence": lm._CATEGORY_TO_PROMINENCE[category],
        }
        reply.update(overrides)
        return json.dumps(reply)
    return generate


def _enriched(answers=None, **ai_overrides):
    """Run the real ai_manager.analyse_student with a fake generate_fn."""
    record = {"student_id": "2605581", "survey_version": "evidence-v3",
              "safety_flag": False, **(answers or _answers())}
    ok, enriched, error = ai_manager.analyse_student(
        record, generate_fn=_fake_generate_fn(**ai_overrides),
        max_attempts=1, retry_delay_sec=0,
    )
    assert ok, error
    return enriched


def _with_gemini_score(record, stress_score):
    """Replace Gemini's score with one that may disagree with the answers.

    ai_manager would reject a reply over 0.01 off, so this is set by hand to
    test Logic's own cross-check.
    """
    record = dict(record)
    record.update(stress_score=stress_score, risk_score=(stress_score - 1) / 4)
    return record


class CrossCheckTests(unittest.TestCase):

    def test_gemini_match_is_kept_untouched(self):
        enriched = _enriched()
        result = lm.apply_logic(enriched)
        self.assertTrue(result["ok"])
        for key in ("stress_score", "risk_score", "risk_category", "soft_label",
                    "speak_prominence", "tips", "primary_stressors", "reasoning"):
            self.assertEqual(result[key], enriched[key], key)
        self.assertEqual(result["logic_stress_score"], 3.0)
        self.assertEqual(result["logic_clamp_notes"], [])

    def test_gemini_within_0_01_is_kept_untouched(self):
        record = _with_gemini_score(_enriched(), 3.01)
        result = lm.apply_logic(record)
        self.assertTrue(result["ok"])
        self.assertEqual(result["stress_score"], 3.01)
        self.assertEqual(result["logic_stress_score"], 3.0)
        for key in ("risk_score", "risk_category", "soft_label",
                    "speak_prominence", "reasoning"):
            self.assertEqual(result[key], record[key], key)
        self.assertEqual(result["logic_clamp_notes"], [])

    def test_mismatch_over_0_01_returns_error(self):
        for gemini_score in (3.02, 2.98, 3.5, 2.1, 4.9):
            with self.subTest(gemini_score=gemini_score):
                record = _with_gemini_score(_enriched(), gemini_score)
                record["feelings_text"] = "private"
                result = lm.apply_logic(record)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], lm.ERROR_SCORE_MISMATCH)
                self.assertEqual(result["stress_score"], gemini_score)
                self.assertEqual(result["logic_stress_score"], 3.0)
                self.assertNotIn("feelings_text", result)
                # No outcome is invented on a mismatch.
                self.assertNotIn("logic_rule", result)
                self.assertNotIn("factor_insights", result)

    def test_mismatch_is_an_ai_failure_in_the_pipeline(self):
        import main
        record = _with_gemini_score(_enriched(), 4.5)
        with patch.object(main.ai_manager, "analyse_student",
                          return_value=(True, record, None)):
            ok, outcome = main.process_checkin(dict(record))
        self.assertFalse(ok)
        self.assertEqual(outcome, "unavailable")


class ScoringTests(unittest.TestCase):

    def test_reverse_scoring_and_sleep_conversion(self):
        answers = dict(pss_1=4, pss_2=2, pss_3=1, pss_4=3, sleep_hours_avg=5.5,
                       sleep_quality=2, pas_workload=5, pas_catchup=1,
                       fin_stress=2, mspss_friends=5, mspss_family=4)
        # 4 + (6-2) + (6-1) + 3 + 4 (5.5 h) + 2 + 5 + 1 + 2 + (6-5) + (6-4) = 33
        self.assertEqual(lm.score_answers(answers)["stress_score"], 3.0)

    def test_sleep_hour_bands(self):
        for hours, value in [(14, 1), (8, 1), (7.5, 2), (7, 2), (6.5, 3),
                             (6, 3), (5.5, 4), (5, 4), (4.5, 5), (0, 5)]:
            self.assertEqual(lm.sleep_hours_stress(hours), value, hours)

    def test_reversed_items_only(self):
        self.assertEqual(lm.REVERSED_KEYS, ("pss_2", "pss_3", "mspss_friends", "mspss_family"))
        for key in lm.ANSWER_KEYS:
            if key == "sleep_hours_avg":
                continue
            expected = 5 if key in lm.REVERSED_KEYS else 1
            self.assertEqual(lm.scored_value(key, 1), expected, key)

    def test_tier_boundaries(self):
        self.assertEqual(lm.category_for_score(2.49), "Low")
        self.assertEqual(lm.category_for_score(2.5), "Moderate")
        self.assertEqual(lm.category_for_score(3.5), "Moderate")
        self.assertEqual(lm.category_for_score(3.51), "High")


class FlagTipTests(unittest.TestCase):

    FLAG_CASES = (
        ("sleep", dict(sleep_hours_avg=5.5), "sleep_routine"),
        ("sleep", dict(sleep_quality=4), "sleep_routine"),
        ("workload", dict(pas_workload=4), "workload_chunks"),
        ("finances", dict(fin_stress=4), "money_worries"),
        ("support", dict(mspss_friends=2, mspss_family=2), "talk_to_someone"),
    )

    def test_each_flag_adds_its_tip(self):
        for flag, changes, tip in self.FLAG_CASES:
            with self.subTest(flag=flag, changes=changes):
                result = lm.apply_logic(_enriched(_answers(**changes)))
                self.assertTrue(result["context_flags"][flag])
                self.assertIn(tip, result["tips"])
                self.assertEqual(result["tips"][:2], ["short_breaks", "rest_a_little_more"])
                self.assertLessEqual(len(result["tips"]), lm.MAX_TIPS)

    def test_no_flag_adds_no_tip(self):
        result = lm.apply_logic(_enriched())
        self.assertFalse(any(result["context_flags"].values()))
        self.assertEqual(result["tips"], ["short_breaks", "rest_a_little_more"])

    def test_all_flags_never_exceed_four_or_replace_gemini_tips(self):
        gemini_tips = ["short_breaks", "rest_a_little_more", "keep_social_contact"]
        answers = _answers(sleep_hours_avg=4, pas_workload=5, fin_stress=5,
                           mspss_friends=1, mspss_family=1)
        result = lm.apply_logic(_enriched(answers, tips=gemini_tips))
        self.assertTrue(all(result["context_flags"].values()))
        self.assertEqual(len(result["tips"]), 4)
        self.assertEqual(result["tips"][:3], gemini_tips)

    def test_flags_never_change_the_tier(self):
        # Low average but workload and finances flagged.
        answers = {key: 1 for key in lm.ANSWER_KEYS}
        answers.update(sleep_hours_avg=8, pss_2=5, pss_3=5, mspss_friends=5,
                       mspss_family=5, pas_workload=5, fin_stress=5)
        result = lm.apply_logic(_enriched(answers))
        self.assertEqual(result["risk_category"], "Low")
        self.assertIn("workload_chunks", result["tips"])
        self.assertIn("money_worries", result["tips"])


class SafetyTests(unittest.TestCase):

    def test_safety_flag_forces_reach_out(self):
        record = _enriched(_answers(pss_1=1, pss_4=1))
        record["safety_flag"] = True
        record["feelings_text"] = "should never survive Logic"
        result = lm.apply_logic(record)
        self.assertEqual(result["risk_category"], "High")
        self.assertEqual(result["soft_label"], "Please reach out")
        self.assertEqual(result["speak_prominence"], "high")
        self.assertEqual(result["tips"][0], "talk_to_someone")
        self.assertLessEqual(len(result["tips"]), lm.MAX_TIPS)
        self.assertEqual(result["stress_score"], record["stress_score"])
        self.assertTrue(any(n.startswith("safety_override") for n in result["logic_clamp_notes"]))
        self.assertNotIn("feelings_text", result)

    def test_safety_moves_existing_talk_tip_first_without_dropping_gemini_tips(self):
        gemini_tips = ["short_breaks", "rest_a_little_more", "talk_to_someone"]
        record = _enriched(tips=gemini_tips)
        record["safety_flag"] = True
        result = lm.apply_logic(record)
        self.assertEqual(result["tips"][0], "talk_to_someone")
        self.assertTrue(set(gemini_tips) <= set(result["tips"]))

    def test_only_true_safety_flag_counts(self):
        record = _enriched(_answers(pss_1=1, pss_4=1))
        record["safety_flag"] = "yes"
        self.assertNotEqual(lm.apply_logic(record)["risk_category"], "High")


class OutputTests(unittest.TestCase):

    def test_output_contract(self):
        record = _enriched()
        record["feelings_text"] = "private"
        result = lm.apply_logic(record)
        self.assertEqual(result["source"], "ai_logic")
        self.assertIs(result["ai_ok"], True)
        self.assertEqual(result["logic_rule"], "v3")
        for key in ("stress_score", "logic_stress_score", "risk_category", "soft_label",
                    "speak_prominence", "tips", "primary_stressors", "reasoning",
                    "risk_score", "logic_clamp_notes", "factor_insights"):
            self.assertIn(key, result)
        self.assertEqual([card["title"] for card in result["factor_insights"]],
                         ["Rest & recovery", "Study demands", "Money pressures",
                          "Support & connection"])
        self.assertNotIn("feelings_text", result)

    def test_input_is_not_mutated(self):
        record = _enriched()
        snapshot = json.dumps(record, sort_keys=True)
        lm.apply_logic(record)
        self.assertEqual(json.dumps(record, sort_keys=True), snapshot)


class MissingFieldTests(unittest.TestCase):

    def test_missing_ai_field_gives_error_dict(self):
        for key in lm.REQUIRED_AI_FIELDS:
            with self.subTest(key=key):
                record = _enriched()
                del record[key]
                result = lm.apply_logic(record)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], lm.ERROR_AI_FIELDS_REQUIRED)
                self.assertIn(key, result["missing"])

    def test_missing_answer_gives_error_dict(self):
        for key in lm.ANSWER_KEYS:
            with self.subTest(key=key):
                record = _enriched()
                del record[key]
                result = lm.apply_logic(record)
                self.assertFalse(result["ok"])
                self.assertIn(key, result["missing"])

    def test_unusable_numbers_give_error_dict(self):
        for key, bad in (("stress_score", "high"), ("pss_1", None),
                         ("sleep_quality", 9), ("sleep_hours_avg", float("nan")),
                         ("fin_stress", 10 ** 400)):
            with self.subTest(key=key, bad=bad):
                record = _enriched()
                record[key] = bad
                result = lm.apply_logic(record)
                self.assertFalse(result["ok"])
                self.assertIn(key, result["invalid"])

    def test_non_dict_gives_error_dict(self):
        for bad in (None, [], "record"):
            result = lm.apply_logic(bad)
            self.assertFalse(result["ok"])
            self.assertIn("record", result["invalid"])


class LegacyRemovedTests(unittest.TestCase):

    LEGACY = ("stress_level", "academic_workload", "financial_stress", "social_support",
              "ANSWER_MAX", "PSS4", "_stress_to_pss4", "_rescale",
              "REQUIRED_STUDENT_FIELDS", "0.40", "0.75", "finalise")

    def test_no_legacy_names_in_logic_or_survey(self):
        for name in ("logic_manager.py", "survey.py"):
            text = (ROOT / name).read_text(encoding="utf-8")
            for legacy in self.LEGACY:
                with self.subTest(file=name, legacy=legacy):
                    self.assertIsNone(re.search(re.escape(legacy), text))

    def test_survey_only_holds_config_and_safety(self):
        import survey
        for gone in ("score", "finalise", "factor_insights", "explanation",
                     "scored_value", "sleep_hours_stress"):
            self.assertFalse(hasattr(survey, gone), gone)
        self.assertTrue(callable(survey.safety_check))


if __name__ == "__main__":
    unittest.main()
