"""LOGIC.trend() on plain check-in dicts, without Gemini or files."""
import unittest

import logic_manager as lm
from logic_manager import LogicManager
from plain_tests import case, function_suite

LOGIC = LogicManager()

STUDENT = "2605581"


def history(*scores):
    """Finished check-ins as plain dicts, one per day, oldest first."""
    return [{
        "student_id": STUDENT,
        "survey_version": "evidence-v3",
        "stress_score": score,
        "risk_category": "Moderate",
        "soft_label": "Worth a check-in",
        "source": "ai_logic",
        "ai_ok": True,
        "saved_at": f"2026-10-{day:02d}T01:00:00+00:00",
    } for day, score in enumerate(scores, 1)]


def test_trend_compares_the_latest_score_with_the_previous_one():
    cases = (((), lm.TREND_NONE, None), ((3.0,), lm.TREND_FIRST, None),
             ((3.0, 2.5), lm.TREND_LOWER, -0.5),
             ((3.0, 3.25), lm.TREND_SIMILAR, 0.25),
             ((3.0, 2.8), lm.TREND_SIMILAR, -0.2),
             ((2.0, 3.64), lm.TREND_HIGHER, 1.64))
    for scores, comparison, change in cases:
        with case(scores=scores):
            trend = LOGIC.trend(history(*scores))
            assert trend["comparison"] == comparison
            assert trend["change"] == change
    pending = {"student_id": STUDENT, "status": "pending", "ai_ok": False,
               "saved_at": "2026-10-09T01:00:00+00:00"}
    assert LOGIC.trend(history(3.0, 2.5) + [pending])["comparison"] == lm.TREND_LOWER
    assert LOGIC.trend(None)["comparison"] == lm.TREND_NONE


def test_trend_direction_needs_three_scores_and_uses_recent_ones():
    cases = (((3.0, 2.0), lm.TREND_NOT_ENOUGH),
             ((4.0, 3.5, 3.0), lm.TREND_EASING),
             ((2.0, 2.05, 1.95, 2.0), lm.TREND_STEADY),
             ((1.5, 2.0, 2.6, 3.1), lm.TREND_BUILDING),
             # Only the last five count: an old high is forgotten.
             ((5.0, 2.0, 2.0, 2.05, 1.95, 2.0), lm.TREND_STEADY))
    for scores, direction in cases:
        with case(scores=scores):
            assert LOGIC.trend(history(*scores))["direction"] == direction
    trend = LOGIC.trend(list(reversed(history(4.0, 3.0, 2.0))))
    assert (trend["latest"], trend["previous"], trend["average"]) == (2.0, 3.0, 3.0)


def load_tests(loader, tests, pattern):
    """Let `python -m unittest discover -s tests` run this file's tests."""
    return function_suite(globals())


if __name__ == "__main__":
    unittest.main()
