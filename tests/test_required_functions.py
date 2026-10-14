"""Checks for the brief's required function names. No real Gemini call.

Plain assert functions (no classes). Run with pytest, or directly:
    python tests/test_required_functions.py
unittest discover also runs them through load_tests() at the bottom.
"""

from __future__ import annotations

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ai_manager
import data_manager
import io_manager
import logic_manager


def _answers() -> dict:
    """All-3 answers with 6.5 h sleep: average 3.0 (Moderate)."""
    answers = {key: 3 for key in logic_manager.ANSWER_KEYS}
    answers["sleep_hours_avg"] = 6.5
    return answers


def _fake_generate(prompt: str, api_key: str, model_name: str) -> str:
    """Fake Gemini: replays the formula on the prompt's answers."""
    answers = json.loads(prompt[prompt.rfind("{"):])
    scored, stress = ai_manager.expected_stress_score(answers)
    category = ai_manager._category_for_stress_score(stress)
    return json.dumps({
        "scored_items": scored,
        "stress_score": stress,
        "risk_category": category,
        "primary_stressors": ["academic_overload"],
        "confidence": 0.8,
        "reasoning": "A short, warm note.",
        "soft_label": logic_manager._CATEGORY_TO_LABEL[category],
        "tips": ["short_breaks"],
        "speak_prominence": logic_manager._CATEGORY_TO_PROMINENCE[category],
    })


def _failing_generate(prompt: str, api_key: str, model_name: str) -> str:
    raise TimeoutError("deadline exceeded")


def _enriched() -> dict:
    record = {"student_id": "2605581", "survey_version": "evidence-v3",
              "safety_flag": False, **_answers()}
    ok, enriched, error = ai_manager.analyse_student(
        record, generate_fn=_fake_generate, max_attempts=1, retry_delay_sec=0)
    assert ok, error
    return enriched


def test_call_api_and_validate_with_fake_generate() -> None:
    prompt = ai_manager.build_prompt(_answers())
    ok, fields, error = ai_manager.call_api(prompt, generate_fn=_fake_generate)
    assert ok and error is None
    assert fields["stress_score"] == 3.0
    ok, data = ai_manager.validate_response(_fake_generate(prompt, "", ""))
    assert ok and data["risk_category"] == "Moderate"


def test_call_api_timeout_does_not_crash() -> None:
    ok, fields, error = ai_manager.call_api("prompt", generate_fn=_failing_generate)
    assert not ok and fields is None
    assert error["error_code"] in ai_manager.AI_ERROR_CODES


def test_parse_response_handles_bad_formats() -> None:
    assert ai_manager.parse_response('```json\n{"a": 1}\n```') == {"a": 1}
    assert ai_manager.parse_response("not json") is None
    assert ai_manager.parse_response("{broken") is None
    assert ai_manager.parse_response(None) is None


def test_validate_response_rejects_malformed() -> None:
    assert ai_manager.validate_response({})[0] is False
    assert ai_manager.validate_response("[]")[0] is False


def test_evaluate_score_route() -> None:
    record = _enriched()
    decision = logic_manager.evaluate(record)
    assert decision["ok"] is True
    assert logic_manager.score(record) == record["stress_score"]
    assert logic_manager.route(decision) == "Moderate"


def test_score_rejects_mismatched_ai_score() -> None:
    record = dict(_enriched(), stress_score=4.5)
    assert logic_manager.score(record) is None
    assert logic_manager.route(logic_manager.evaluate(record)) == "unavailable"


def test_save_load_query_and_missing_or_corrupt_file() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "records.json")
        assert data_manager.load(path) == []
        record = logic_manager.evaluate(_enriched())
        assert data_manager.save(record, path, opt_in=True)["ok"] is True
        assert len(data_manager.load(path)) == 1
        assert len(data_manager.query(lambda r: r["risk_category"] == "Moderate", path)) == 1
        assert data_manager.query(lambda r: False, path) == []
        Path(path).write_text("{not json", encoding="utf-8")
        assert data_manager.load(path) == []


def test_display_functions_print() -> None:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        io_manager.display_record(_answers())
        io_manager.display_list([])
        io_manager.display_result(logic_manager.evaluate(_enriched()))
        io_manager.display_result({"ok": False, "error_code": "timeout"})
    assert "Stress score: 3.0" in buffer.getvalue()


_TESTS = [value for name, value in sorted(globals().items())
          if name.startswith("test_") and callable(value)]


def load_tests(loader, standard_tests, pattern):
    """Let `python -m unittest discover` run the plain functions above."""
    return unittest.TestSuite(unittest.FunctionTestCase(fn) for fn in _TESTS)


if __name__ == "__main__":
    unittest.main()
