"""Tests for AI Manager.

All Gemini calls are replaced by a mock generate_fn so no live API key or
network connection is required. Covers response validation and failure cases
(malformed JSON, missing fields).
"""
from __future__ import annotations

import json
import pytest

import ai_manager
from sample_ai_records import LOW_STRESS_STUDENT, LOW_STRESS_REPLY


def make_mock_generate(reply_dict: dict):
    """Return a generate_fn that always yields the given JSON reply."""
    def generate_fn(prompt: str, model: str, api_key: str) -> str:
        return json.dumps(reply_dict)
    return generate_fn


class TestAnalyseStudentWithMock:
    def test_analyse_student_success_with_mock(self):
        mock_fn = make_mock_generate(LOW_STRESS_REPLY)
        ok, enriched, error = ai_manager.analyse_student(
            LOW_STRESS_STUDENT,
            generate_fn=mock_fn,
            max_attempts=1,
        )
        assert ok is True
        assert error is None
        assert enriched is not None
        assert enriched.get("risk_category") == "Low"
        assert "student_id" in enriched
        # reflection must be stripped
        assert "feelings_text" not in enriched
        assert "reflection" not in enriched

    def test_analyse_student_malformed_json(self):
        def bad_generate(prompt, model, api_key):
            return "this is not json {{{"
        ok, enriched, error = ai_manager.analyse_student(
            LOW_STRESS_STUDENT,
            generate_fn=bad_generate,
            max_attempts=1,
        )
        assert ok is False
        assert enriched is None
        assert error is not None
        # error uses "error_code" key
        assert error.get("error_code") in (
            "invalid_response", "retries_exhausted", "unavailable", "timeout"
        )

    def test_analyse_student_missing_required_fields(self):
        incomplete = {"risk_category": "Low"}  # missing stress_score etc.
        mock_fn = make_mock_generate(incomplete)
        ok, enriched, error = ai_manager.analyse_student(
            LOW_STRESS_STUDENT,
            generate_fn=mock_fn,
            max_attempts=1,
        )
        assert ok is False
        assert error is not None


class TestAIProcessingError:
    def test_error_codes(self):
        err = ai_manager.AIProcessingError("invalid_response", "bad json")
        assert err.code == "invalid_response"
        assert "invalid_response" in str(err)
