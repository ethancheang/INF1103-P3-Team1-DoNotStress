"""AI Manager tests: prompt, parsing, schema validation, retries and failure codes.

The live Gemini client is replaced by ScriptedTextGenerator, so no API key or
network is needed. Hardcoded replies come from sample_ai_records.py.
"""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

from ai_manager import (
    AIErrorClassifier,
    AIProcessingError,
    GeminiAIManager,
    GeminiTextGenerator,
    PromptBuilder,
    ResponseParser,
    ResponseValidator,
    RetryPolicy,
    ScoreVerifier,
)
from doubles import ScriptedTextGenerator
from logic_manager import AIScoreVerifier, ScoreCalculator
from sample_ai_records import HIGH_REPLY, HIGH_STUDENT, LOW_STRESS_REPLY, LOW_STRESS_STUDENT, MODERATE_REPLY
from survey import Questionnaire


def manager_with(*script, verifier=True, max_attempts=3):
    """A GeminiAIManager whose API client plays back ``script`` (no delays)."""
    generator = ScriptedTextGenerator(script)
    check = AIScoreVerifier(ScoreCalculator()) if verifier else None
    manager = GeminiAIManager(check, generator, questions=Questionnaire.QUESTIONS,
                              max_attempts=max_attempts, retry_delay_sec=0)
    return manager, generator


class PromptBuilderTests(unittest.TestCase):
    def setUp(self):
        self.student = {**HIGH_STUDENT, "feelings_text": "very private words"}
        self.prompt = PromptBuilder(Questionnaire.QUESTIONS).build(self.student, "SCORING RULES HERE")

    def test_student_id_and_reflection_are_never_sent(self):
        self.assertNotIn(self.student["student_id"], self.prompt)
        self.assertNotIn("very private words", self.prompt)

    def test_only_the_eleven_answers_and_version_are_sent(self):
        payload = json.loads(self.prompt.rsplit("Student check-in:\n", 1)[1])
        self.assertEqual(set(payload), {*Questionnaire.QUESTION_MAP, "survey_version"})
        self.assertEqual(payload["pss_1"], 5)

    def test_prompt_asks_for_json_and_includes_the_scoring_rules_and_wording(self):
        self.assertIn("Return ONLY a single JSON object", self.prompt)
        self.assertIn("SCORING RULES HERE", self.prompt)
        self.assertIn("pss_1: In the past month", self.prompt)
        self.assertIn("(0 hours → 14 hours)", self.prompt)  # the sleep slider has no option labels


class ResponseParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = ResponseParser()

    def test_plain_and_fenced_json(self):
        self.assertEqual(self.parser.parse('{"a": 1}'), {"a": 1})
        self.assertEqual(self.parser.parse('```json\n{"a": 1}\n```'), {"a": 1})

    def test_malformed_replies_give_none(self):
        for raw in ("not json {{{", "", "[1, 2]", '"text"', None, 42):
            with self.subTest(raw=raw):
                self.assertIsNone(self.parser.parse(raw))


class ResponseValidatorTests(unittest.TestCase):
    def setUp(self):
        self.validator = ResponseValidator()

    def test_a_complete_reply_passes_and_is_cleaned(self):
        ok, cleaned = self.validator.validate({**MODERATE_REPLY, "reasoning": "  Warm words.  ", "extra": 1})
        self.assertTrue(ok)
        self.assertEqual(cleaned["reasoning"], "Warm words.")
        self.assertNotIn("extra", cleaned)

    def test_missing_fields_are_listed(self):
        reply = {k: v for k, v in MODERATE_REPLY.items() if k not in ("tips", "confidence")}
        self.assertEqual(self.validator.validate(reply), (False, "missing fields: confidence, tips"))

    def test_every_field_is_checked(self):
        cases = {
            "scored_items": {**MODERATE_REPLY["scored_items"], "pss_1": 7},
            "stress_score": 5.5,
            "risk_category": "Severe",
            "primary_stressors": ["made_up"],
            "confidence": 1.5,
            "reasoning": "   ",
            "soft_label": "All good",
            "tips": ["short_breaks", "sleep_routine", "money_worries", "workload_chunks"],
            "speak_prominence": "urgent",
        }
        for field, bad in cases.items():
            with self.subTest(field=field):
                self.assertEqual(self.validator.validate({**MODERATE_REPLY, field: bad}), (False, f"{field} invalid"))

    def test_strange_types_are_rejected_not_crashed(self):
        for field in ("risk_category", "speak_prominence", "stress_score", "tips"):
            with self.subTest(field=field):
                self.assertFalse(self.validator.validate({**MODERATE_REPLY, field: ["a", {"b": 1}]})[0])
        self.assertFalse(self.validator.validate(["not", "an", "object"])[0])


class GeminiAIManagerTests(unittest.TestCase):
    def test_success_merges_answers_and_strips_the_reflection(self):
        manager, generator = manager_with(json.dumps(LOW_STRESS_REPLY))
        enriched = manager.analyse({**LOW_STRESS_STUDENT, "feelings_text": "private"})
        self.assertEqual(enriched["risk_category"], "Low")
        self.assertEqual(enriched["student_id"], LOW_STRESS_STUDENT["student_id"])
        self.assertEqual(enriched["source"], "gemini")
        self.assertNotIn("feelings_text", enriched)
        self.assertEqual(len(generator.prompts), 1)

    def test_a_malformed_reply_is_retried(self):
        manager, generator = manager_with("this is not json {{{", json.dumps(LOW_STRESS_REPLY))
        self.assertEqual(manager.analyse(LOW_STRESS_STUDENT)["stress_score"], 1.82)
        self.assertEqual(len(generator.prompts), 2)

    def test_wrong_arithmetic_is_retried_then_rejected(self):
        wrong = json.dumps({**LOW_STRESS_REPLY, "stress_score": 4.9, "risk_category": "High",
                            "soft_label": "Please reach out", "speak_prominence": "high"})
        manager, _ = manager_with(wrong, wrong, wrong)
        with self.assertRaises(AIProcessingError) as caught:
            manager.analyse(LOW_STRESS_STUDENT)
        self.assertEqual(caught.exception.code, "retries_exhausted")

    def test_invalid_schema_every_time_never_invents_a_result(self):
        manager, generator = manager_with(*[json.dumps({"risk_category": "Low"})] * 10)
        with self.assertRaises(AIProcessingError) as caught:
            manager.analyse(LOW_STRESS_STUDENT)
        self.assertIn(caught.exception.code, ("invalid_response", "retries_exhausted"))
        self.assertLessEqual(len(generator.prompts), RetryPolicy.MAX_TOTAL_CALLS)

    def test_connection_failures_are_retried_then_reported(self):
        class RateLimited(Exception):
            code = 429

        cases = {
            "rate_limited": RateLimited("slow down"),
            "retries_exhausted": ConnectionError("connection refused"),
        }
        for expected, error in cases.items():
            with self.subTest(expected=expected):
                manager, generator = manager_with(*[error] * 10)
                with self.assertRaises(AIProcessingError) as caught:
                    manager.analyse(LOW_STRESS_STUDENT)
                self.assertEqual(caught.exception.code, expected)
                self.assertEqual(len(generator.prompts), RetryPolicy.MAX_TOTAL_CALLS)

    def test_a_timeout_is_retried_and_can_still_succeed(self):
        manager, generator = manager_with(TimeoutError("The read operation timed out"), json.dumps(LOW_STRESS_REPLY))
        self.assertEqual(manager.analyse(LOW_STRESS_STUDENT)["risk_category"], "Low")
        self.assertEqual(len(generator.prompts), 2)

    def test_a_model_that_is_gone_falls_back_to_the_next_model(self):
        manager, generator = manager_with(RuntimeError("404 NOT_FOUND"), json.dumps(LOW_STRESS_REPLY))
        manager.analyse(LOW_STRESS_STUDENT)
        self.assertEqual(generator.models, list(RetryPolicy.MODEL_CHAIN[:2]))

    def test_missing_api_key_fails_fast_without_calling_the_api(self):
        with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
            manager = GeminiAIManager(None, GeminiTextGenerator(), retry_delay_sec=0)
            with self.assertRaises(AIProcessingError) as caught:
                manager.analyse(LOW_STRESS_STUDENT)
        self.assertEqual(caught.exception.code, "missing_api_key")

    def test_input_that_is_not_a_dict_is_refused(self):
        manager, generator = manager_with(json.dumps(LOW_STRESS_REPLY))
        with self.assertRaises(AIProcessingError):
            manager.analyse(["not", "a", "dict"])
        self.assertEqual(generator.prompts, [])

    def test_required_functions_are_methods(self):
        manager, _ = manager_with()
        self.assertTrue(manager.validate_response(HIGH_REPLY)[0])
        self.assertEqual(manager.parse_response(json.dumps({"a": 1})), {"a": 1})
        self.assertIn("Student check-in:", manager.build_prompt(HIGH_STUDENT))


class SupportingClassTests(unittest.TestCase):
    def test_logic_verifier_satisfies_the_ai_managers_interface(self):
        self.assertIsInstance(AIScoreVerifier(ScoreCalculator()), ScoreVerifier)

    def test_error_codes_are_restricted(self):
        self.assertEqual(AIProcessingError("weird").code, "unavailable")
        self.assertEqual(AIProcessingError("timeout", "slow").detail, "slow")

    def test_classifier(self):
        classifier = AIErrorClassifier()
        self.assertEqual(classifier.classify(Exception("HTTP Error 429: Too Many Requests"),
                                             "HTTP Error 429: Too Many Requests"), ("rate_limited", False))
        self.assertEqual(classifier.classify(Exception("x"), "503 UNAVAILABLE"), ("unavailable", True))
        self.assertEqual(classifier.classify(TimeoutError("timed out"), "timed out"), ("timeout", False))
        self.assertEqual(classifier.final_code("timeout", 1, ["timeout"]), "timeout")
        self.assertEqual(classifier.final_code("timeout", 3, ["timeout"] * 3), "retries_exhausted")

    def test_retry_policy(self):
        policy = RetryPolicy(max_attempts=10, retry_delay_sec=0.5)
        self.assertEqual(policy.tries_per_model(), 3)
        self.assertEqual([policy.backoff_seconds(n) for n in (1, 2, 3, 6)], [0.5, 1.0, 2.0, 8.0])
        self.assertEqual(policy.models_for("custom-model")[0], "custom-model")

    def test_live_client_masks_its_key(self):
        generator = GeminiTextGenerator(api_key="SECRET-KEY-123")
        self.assertTrue(generator.is_configured())
        self.assertEqual(generator.redact("url?key=SECRET-KEY-123 failed"), "url?key=*** failed")


if __name__ == "__main__":
    unittest.main()
