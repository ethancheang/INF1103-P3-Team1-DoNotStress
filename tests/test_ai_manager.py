"""Unit tests for ai_manager: fallback chain, schema validation, prompt building, and error handling."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

import ai_manager


class AiManagerTests(unittest.TestCase):

    def test_model_fallback_chain_constant(self):
        self.assertEqual(
            ai_manager.MODEL_FALLBACK_CHAIN,
            ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"),
        )

    def test_build_prompt_privacy_and_plain_labels(self):
        student = {
            "student_id": "2605581",
            "pss_1": 2,
            "pss_2": 4,  # reverse-scored
            "pss_3": 4,  # reverse-scored
            "pss_4": 3,
            "reference_score": 3.25,
            "feelings_text": "Private journal note",
        }
        prompt = ai_manager.build_prompt(student)
        self.assertNotIn("2605581", prompt)
        self.assertNotIn("Private journal", prompt)
        self.assertNotIn("reference_score", prompt)
        self.assertNotIn("3.25", prompt)
        # Check plain labels
        self.assertIn("Feeling unable to control important things in life", prompt)
        self.assertIn("Difficulty handling personal problems", prompt)
        # Check no tier fields requested in prompt
        self.assertNotIn("risk_category", prompt)
        self.assertNotIn("soft_label", prompt)
        self.assertNotIn("speak_prominence", prompt)

    def test_validation_accepts_valid_payload(self):
        payload = {
            "perceived_stress_score": 3.2,
            "explanation": "You are balancing multiple priorities and finding manageable ways to keep going.",
            "tips": ["workload_chunks", "short_breaks"],
        }
        ok, res = ai_manager.validate_ai_response(payload)
        self.assertTrue(ok)
        self.assertEqual(res["perceived_stress_score"], 3.2)
        self.assertEqual(res["tips"], ["workload_chunks", "short_breaks"])

    def test_validation_rejects_digits_in_explanation(self):
        payload = {
            "perceived_stress_score": 3.2,
            "explanation": "You have a score of 3 out of 5 which looks okay.",
            "tips": ["workload_chunks"],
        }
        ok, err = ai_manager.validate_ai_response(payload)
        self.assertFalse(ok)
        self.assertIn("must not contain numbers", err)

    def test_validation_rejects_forbidden_words(self):
        for bad_word, sentence in [
            ("AI", "The AI thinks you are doing fine."),
            ("Gemini", "According to Gemini you need a break."),
            ("PSS", "Your PSS rating indicates moderate pressure."),
            ("score", "Your score shows steady progress."),
            ("diagnosis", "You do not have a diagnosis of depression."),
        ]:
            payload = {
                "perceived_stress_score": 2.5,
                "explanation": sentence,
                "tips": ["short_breaks"],
            }
            ok, err = ai_manager.validate_ai_response(payload)
            self.assertFalse(ok, f"Should reject word: {bad_word}")

    def test_validation_rejects_over_400_chars(self):
        payload = {
            "perceived_stress_score": 2.5,
            "explanation": "You are doing okay. " * 30,  # > 400 chars without digits
            "tips": ["short_breaks"],
        }
        ok, err = ai_manager.validate_ai_response(payload)
        self.assertFalse(ok)
        self.assertIn("400 characters", err)

    def test_validation_rejects_out_of_range_score(self):
        for bad_score in (0.9, 5.1, float("nan"), float("inf"), "high"):
            payload = {
                "perceived_stress_score": bad_score,
                "explanation": "You are doing your best with your studies.",
                "tips": ["short_breaks"],
            }
            ok, err = ai_manager.validate_ai_response(payload)
            self.assertFalse(ok)

    def test_fallback_chain_one_attempt_per_model(self):
        models_called = []

        def mock_generate(prompt, key, model):
            models_called.append(model)
            if model == "gemini-3.6-flash":
                raise RuntimeError("503 Service Unavailable")
            if model == "gemini-3.5-flash":
                raise RuntimeError("429 Resource Exhausted")
            # gemini-3.5-flash-lite succeeds
            return json.dumps({
                "perceived_stress_score": 2.5,
                "explanation": "You seem to be handling things calmly this week.",
                "tips": ["short_breaks"],
            })

        ok, result, err = ai_manager.call_gemini(
            "test prompt",
            api_key="fake-key",
            generate_fn=mock_generate,
        )
        self.assertTrue(ok)
        self.assertEqual(result["ai_model"], "gemini-3.5-flash-lite")
        # Exactly one call per model
        self.assertEqual(
            models_called,
            ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"],
        )

    def test_immediate_failure_on_401_or_missing_key(self):
        models_called = []

        def mock_generate(prompt, key, model):
            models_called.append(model)
            raise RuntimeError("401 UNAUTHENTICATED: Invalid credentials")

        ok, result, err = ai_manager.call_gemini(
            "test prompt",
            api_key="invalid-key",
            generate_fn=mock_generate,
        )
        self.assertFalse(ok)
        self.assertEqual(err["error_code"], ai_manager.ERROR_CODE_MISSING_API_KEY)
        # Did NOT try subsequent models
        self.assertEqual(models_called, ["gemini-3.6-flash"])

    def test_all_models_failing_quota_returns_quota_exhausted(self):
        def mock_generate(prompt, key, model):
            raise RuntimeError("429 RESOURCE_EXHAUSTED: quota exceeded")

        ok, result, err = ai_manager.call_gemini(
            "test prompt",
            api_key="fake-key",
            generate_fn=mock_generate,
        )
        self.assertFalse(ok)
        self.assertEqual(err["error_code"], ai_manager.ERROR_CODE_QUOTA_EXHAUSTED)


if __name__ == "__main__":
    unittest.main()
