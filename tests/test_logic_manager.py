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
from plain_tests import case, function_suite


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


# --- Cross Check -----------------------------------------------------------

def test_gemini_match_is_kept_untouched():
    enriched = _enriched()
    result = lm.apply_logic(enriched)
    assert result["ok"]
    for key in ("stress_score", "risk_score", "risk_category", "soft_label",
                "speak_prominence", "tips", "primary_stressors", "reasoning"):
        assert result[key] == enriched[key], key
    assert result["logic_stress_score"] == 3.0
    assert result["logic_clamp_notes"] == []


def test_gemini_within_0_01_is_kept_untouched():
    record = _with_gemini_score(_enriched(), 3.01)
    result = lm.apply_logic(record)
    assert result["ok"]
    assert result["stress_score"] == 3.01
    assert result["logic_stress_score"] == 3.0
    for key in ("risk_score", "risk_category", "soft_label",
                "speak_prominence", "reasoning"):
        assert result[key] == record[key], key
    assert result["logic_clamp_notes"] == []


def test_mismatch_over_0_01_returns_error():
    for gemini_score in (3.02, 2.98, 3.5, 2.1, 4.9):
        with case(gemini_score=gemini_score):
            record = _with_gemini_score(_enriched(), gemini_score)
            record["feelings_text"] = "private"
            result = lm.apply_logic(record)
            assert not result["ok"]
            assert result["error"] == lm.ERROR_SCORE_MISMATCH
            assert result["stress_score"] == gemini_score
            assert result["logic_stress_score"] == 3.0
            assert "feelings_text" not in result
            # No outcome is invented on a mismatch.
            assert "logic_rule" not in result
            assert "factor_insights" not in result


def test_mismatch_is_an_ai_failure_in_the_pipeline():
    import main
    record = _with_gemini_score(_enriched(), 4.5)
    with patch.object(main.ai_manager, "analyse_student",
                      return_value=(True, record, None)):
        ok, outcome = main.process_checkin(dict(record))
    assert not ok
    assert outcome == "unavailable"


# --- Scoring ---------------------------------------------------------------

def test_reverse_scoring_and_sleep_conversion():
    answers = dict(pss_1=4, pss_2=2, pss_3=1, pss_4=3, sleep_hours_avg=5.5,
                   sleep_quality=2, pas_workload=5, pas_catchup=1,
                   fin_stress=2, mspss_friends=5, mspss_family=4)
    # 4 + (6-2) + (6-1) + 3 + 4 (5.5 h) + 2 + 5 + 1 + 2 + (6-5) + (6-4) = 33
    assert lm.score_answers(answers)["stress_score"] == 3.0


def test_sleep_hour_bands():
    for hours, value in [(14, 1), (8, 1), (7.5, 2), (7, 2), (6.5, 3),
                         (6, 3), (5.5, 4), (5, 4), (4.5, 5), (0, 5)]:
        assert lm.sleep_hours_stress(hours) == value, hours


def test_reversed_items_only():
    assert lm.REVERSED_KEYS == ("pss_2", "pss_3", "mspss_friends", "mspss_family")
    for key in lm.ANSWER_KEYS:
        if key == "sleep_hours_avg":
            continue
        expected = 5 if key in lm.REVERSED_KEYS else 1
        assert lm.scored_value(key, 1) == expected, key


def test_tier_boundaries():
    assert lm.category_for_score(2.49) == "Low"
    assert lm.category_for_score(2.5) == "Moderate"
    assert lm.category_for_score(3.5) == "Moderate"
    assert lm.category_for_score(3.51) == "High"


# --- Flag Tip --------------------------------------------------------------

FLAG_CASES = (
    ("sleep", dict(sleep_hours_avg=5.5), "sleep_routine"),
    ("sleep", dict(sleep_quality=4), "sleep_routine"),
    ("workload", dict(pas_workload=4), "workload_chunks"),
    ("finances", dict(fin_stress=4), "money_worries"),
    ("support", dict(mspss_friends=2, mspss_family=2), "talk_to_someone"),
)


def test_each_flag_adds_its_tip():
    for flag, changes, tip in FLAG_CASES:
        with case(flag=flag, changes=changes):
            result = lm.apply_logic(_enriched(_answers(**changes)))
            assert result["context_flags"][flag]
            assert tip in result["tips"]
            assert result["tips"][:2] == ["short_breaks", "rest_a_little_more"]
            assert len(result["tips"]) <= lm.MAX_TIPS


def test_no_flag_adds_no_tip():
    result = lm.apply_logic(_enriched())
    assert not any(result["context_flags"].values())
    assert result["tips"] == ["short_breaks", "rest_a_little_more"]


def test_all_flags_never_exceed_four_or_replace_gemini_tips():
    gemini_tips = ["short_breaks", "rest_a_little_more", "keep_social_contact"]
    answers = _answers(sleep_hours_avg=4, pas_workload=5, fin_stress=5,
                       mspss_friends=1, mspss_family=1)
    result = lm.apply_logic(_enriched(answers, tips=gemini_tips))
    assert all(result["context_flags"].values())
    assert len(result["tips"]) == 4
    assert result["tips"][:3] == gemini_tips


def test_flags_never_change_the_tier():
    # Low average but workload and finances flagged.
    answers = {key: 1 for key in lm.ANSWER_KEYS}
    answers.update(sleep_hours_avg=8, pss_2=5, pss_3=5, mspss_friends=5,
                   mspss_family=5, pas_workload=5, fin_stress=5)
    result = lm.apply_logic(_enriched(answers))
    assert result["risk_category"] == "Low"
    assert "workload_chunks" in result["tips"]
    assert "money_worries" in result["tips"]


# --- Safety ----------------------------------------------------------------

def test_safety_flag_forces_reach_out():
    record = _enriched(_answers(pss_1=1, pss_4=1))
    record["safety_flag"] = True
    record["feelings_text"] = "should never survive Logic"
    result = lm.apply_logic(record)
    assert result["risk_category"] == "High"
    assert result["soft_label"] == "Please reach out"
    assert result["speak_prominence"] == "high"
    assert result["tips"][0] == "talk_to_someone"
    assert len(result["tips"]) <= lm.MAX_TIPS
    assert result["stress_score"] == record["stress_score"]
    assert any(n.startswith("safety_override") for n in result["logic_clamp_notes"])
    assert "feelings_text" not in result


def test_safety_moves_existing_talk_tip_first_without_dropping_gemini_tips():
    gemini_tips = ["short_breaks", "rest_a_little_more", "talk_to_someone"]
    record = _enriched(tips=gemini_tips)
    record["safety_flag"] = True
    result = lm.apply_logic(record)
    assert result["tips"][0] == "talk_to_someone"
    assert set(gemini_tips) <= set(result["tips"])


def test_only_true_safety_flag_counts():
    record = _enriched(_answers(pss_1=1, pss_4=1))
    record["safety_flag"] = "yes"
    assert lm.apply_logic(record)["risk_category"] != "High"


# --- Output ----------------------------------------------------------------

def test_output_contract():
    record = _enriched()
    record["feelings_text"] = "private"
    result = lm.apply_logic(record)
    assert result["source"] == "ai_logic"
    assert result["ai_ok"] is True
    assert result["logic_rule"] == "v3"
    for key in ("stress_score", "logic_stress_score", "risk_category", "soft_label",
                "speak_prominence", "tips", "primary_stressors", "reasoning",
                "risk_score", "logic_clamp_notes", "factor_insights"):
        assert key in result
    assert [card["title"] for card in result["factor_insights"]] == (["Rest & recovery", "Study demands", "Money pressures",
                      "Support & connection"])
    assert "feelings_text" not in result


def test_input_is_not_mutated():
    record = _enriched()
    snapshot = json.dumps(record, sort_keys=True)
    lm.apply_logic(record)
    assert json.dumps(record, sort_keys=True) == snapshot


# --- Missing Field ---------------------------------------------------------

def test_missing_ai_field_gives_error_dict():
    for key in lm.REQUIRED_AI_FIELDS:
        with case(key=key):
            record = _enriched()
            del record[key]
            result = lm.apply_logic(record)
            assert not result["ok"]
            assert result["error"] == lm.ERROR_AI_FIELDS_REQUIRED
            assert key in result["missing"]


def test_missing_answer_gives_error_dict():
    for key in lm.ANSWER_KEYS:
        with case(key=key):
            record = _enriched()
            del record[key]
            result = lm.apply_logic(record)
            assert not result["ok"]
            assert key in result["missing"]


def test_unusable_numbers_give_error_dict():
    for key, bad in (("stress_score", "high"), ("pss_1", None),
                     ("sleep_quality", 9), ("sleep_hours_avg", float("nan")),
                     ("fin_stress", 10 ** 400)):
        with case(key=key, bad=bad):
            record = _enriched()
            record[key] = bad
            result = lm.apply_logic(record)
            assert not result["ok"]
            assert key in result["invalid"]


def test_non_dict_gives_error_dict():
    for bad in (None, [], "record"):
        result = lm.apply_logic(bad)
        assert not result["ok"]
        assert "record" in result["invalid"]


# --- Legacy Removed --------------------------------------------------------

LEGACY = ("stress_level", "academic_workload", "financial_stress", "social_support",
          "ANSWER_MAX", "PSS4", "_stress_to_pss4", "_rescale",
          "REQUIRED_STUDENT_FIELDS", "0.40", "0.75", "finalise")


def test_no_legacy_names_in_logic_or_survey():
    for name in ("logic_manager.py", "survey.py"):
        text = (ROOT / name).read_text(encoding="utf-8")
        for legacy in LEGACY:
            with case(file=name, legacy=legacy):
                assert re.search(re.escape(legacy), text) is None


def test_survey_only_holds_config_and_safety():
    import survey
    for gone in ("score", "finalise", "factor_insights", "explanation",
                 "scored_value", "sleep_hours_stress"):
        assert not hasattr(survey, gone), gone
    assert callable(survey.safety_check)


def load_tests(loader, tests, pattern):
    """Let `python -m unittest discover -s tests` run this file's test_ functions."""
    return function_suite(globals())


if __name__ == "__main__":
    unittest.main()
