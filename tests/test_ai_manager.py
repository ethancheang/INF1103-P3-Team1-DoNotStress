"""Gemini estimates stress from raw answers. These tests never call the API."""
import json
import os
import unittest
from unittest.mock import patch

import ai_manager
import io_manager
import survey


def _checkin():
    """A full record with scores and a reflection Gemini must not see."""
    return {
        "student_id": "2605581",
        "feelings_text": "PRIVATE REFLECTION that must stay off the prompt",
        "survey_version": survey.VERSION,
        "pss_1": 4,
        "pss_2": 2,
        "pss_3": 5,
        "pss_4": 3,
        "sleep_hours_avg": 6.5,
        "sleep_quality": 4,
        "pas_workload": 5,
        "pas_catchup": 2,
        "fin_stress": 1,
        "mspss_friends": 2,
        "mspss_family": 5,
        "stress_score": 9.99,
        "scored_item_count": 11,
        "support_mean": 1.25,
        "support_item_count": 2,
        "context_flags": {"SENTINEL_FLAG": True},
        "risk_category": "SENTINEL_CATEGORY",
        "soft_label": "SENTINEL_SOFT_LABEL",
        "speak_prominence": "SENTINEL_PROMINENCE",
        "safety_flag": True,
        "risk_score": 0.99,
    }


def _gemini(**overrides):
    """A Moderate reply. Overrides replace fields; they do not fill gaps."""
    payload = {
        "stress_score": 3.0,
        "risk_category": "Moderate",
        "primary_stressors": ["academic_overload"],
        "confidence": 0.8,
        "reasoning": (
            "School looks a bit heavy right now. "
            "A smaller plan for the week could take some of the pressure off."
        ),
        "soft_label": "Worth a check-in",
        "tips": ["workload_chunks", "short_breaks"],
        "speak_prominence": "medium",
    }
    payload.update(overrides)
    return payload


def _for_score(score, **overrides):
    """Tier fields that match score, plus any extra overrides."""
    if score < 2.5:
        category, label, prominence = "Low", "You're doing ok", "low"
    elif score <= 3.5:
        category, label, prominence = "Moderate", "Worth a check-in", "medium"
    else:
        category, label, prominence = "High", "Please reach out", "high"
    payload = _gemini(
        stress_score=score,
        risk_category=category,
        soft_label=label,
        speak_prominence=prominence,
    )
    payload.update(overrides)
    return payload


def _input_payload(prompt):
    """The JSON object at the end of the prompt is the only student data."""
    start = prompt.rfind("{")
    return json.loads(prompt[start:])


class PromptTests(unittest.TestCase):
    def test_prompt_has_raw_answers_and_wording_only(self):
        prompt = ai_manager.build_prompt(_checkin())
        payload = _input_payload(prompt)

        self.assertEqual(set(payload), set(ai_manager.STUDENT_PROMPT_FIELDS))
        self.assertEqual(payload["pss_1"], 4)
        self.assertEqual(payload["pss_2"], 2)
        self.assertEqual(payload["sleep_hours_avg"], 6.5)
        self.assertEqual(payload["mspss_family"], 5)
        self.assertEqual(payload["survey_version"], survey.VERSION)
        for banned in (
            "student_id",
            "feelings_text",
            "stress_score",
            "context_flags",
            "risk_category",
            "soft_label",
            "speak_prominence",
            "support_mean",
            "scored_item_count",
            "risk_score",
            "safety_flag",
        ):
            self.assertNotIn(banned, payload)

        self.assertIn(survey.QUESTION_MAP["pss_1"]["prompt"], prompt)
        self.assertIn(survey.QUESTION_MAP["fin_stress"]["prompt"], prompt)
        self.assertIn("1 = Never", prompt)
        self.assertIn("5 = Very often", prompt)
        self.assertIn("1 = No stress at all", prompt)
        self.assertIn("5 = Overwhelming stress", prompt)
        self.assertIn("half-hour", prompt)
        self.assertIn("positively worded", prompt.lower())
        self.assertIn("Talk to someone", prompt)
        self.assertIn("SIT Counselling", prompt)

        self.assertNotIn("2605581", prompt)
        self.assertNotIn("PRIVATE REFLECTION", prompt)
        self.assertNotIn("student_id", prompt)
        self.assertNotIn("feelings_text", prompt)
        self.assertNotIn("context_flags", prompt)
        self.assertNotIn("SENTINEL_FLAG", prompt)
        self.assertNotIn("SENTINEL_CATEGORY", prompt)
        self.assertNotIn("SENTINEL_SOFT_LABEL", prompt)
        self.assertNotIn("SENTINEL_PROMINENCE", prompt)
        self.assertNotIn("9.99", prompt)
        self.assertNotIn("support_mean", prompt)
        self.assertNotIn("risk_score", prompt)
        self.assertNotIn("Speak to advisor", prompt)
        self.assertNotIn("advisor dashboard", prompt)
        self.assertNotIn("emotional_distress", prompt)
        self.assertNotIn("feelings_check_in", prompt)
        self.assertNotIn("6 - answer", prompt)

    def test_default_wording_matches_the_questionnaire(self):
        self.assertFalse(hasattr(ai_manager, "survey"))
        self.assertEqual(
            [item["key"] for item in ai_manager.DEFAULT_QUESTIONS],
            [item["key"] for item in survey.QUESTIONS],
        )
        for default, live in zip(ai_manager.DEFAULT_QUESTIONS, survey.QUESTIONS):
            self.assertEqual(default["prompt"], live["prompt"])
            self.assertEqual(list(default.get("options") or []), list(live.get("options") or []))

    def test_caller_can_pass_question_wording(self):
        seen = {}

        def generate_fn(prompt, api_key, model_name):
            seen["prompt"] = prompt
            return json.dumps(_for_score(1.0, tips=["short_breaks"], primary_stressors=[]))

        ok, enriched, error = ai_manager.analyse_student(
            _checkin(),
            api_key="stub",
            max_attempts=1,
            retry_delay_sec=0,
            generate_fn=generate_fn,
            questions=[{
                "key": "pss_1",
                "prompt": "UNIQUE WORDING XYZ",
                "options": ["No", "Yes"],
            }],
        )
        self.assertTrue(ok, error)
        self.assertIn("UNIQUE WORDING XYZ", seen["prompt"])
        self.assertIn("1 = No", seen["prompt"])
        self.assertNotIn("2605581", seen["prompt"])
        self.assertEqual(enriched["source"], "gemini")
        self.assertEqual(enriched["stress_score"], 1.0)
        self.assertEqual(enriched["risk_score"], 0.0)


class ResponseValidationTests(unittest.TestCase):
    def test_valid_response_computes_risk_score(self):
        supplied = _for_score(2.5)
        supplied["risk_score"] = 0.99
        supplied["recommended_support"] = "Speak to advisor"
        ok, result = ai_manager.validate_ai_response(json.dumps(supplied))
        self.assertTrue(ok, result)
        self.assertEqual(result["stress_score"], 2.5)
        self.assertEqual(result["risk_score"], (2.5 - 1) / 4)
        self.assertEqual(result["risk_category"], "Moderate")
        self.assertEqual(result["soft_label"], "Worth a check-in")
        self.assertEqual(result["speak_prominence"], "medium")
        self.assertNotIn("advisor", result["recommended_support"].lower())
        self.assertTrue(result["recommended_support"].strip())

        for score in (1.0, 3.0, 5.0):
            ok, result = ai_manager.validate_ai_response(_for_score(score))
            self.assertTrue(ok, result)
            self.assertEqual(result["risk_score"], (score - 1) / 4)

    def test_band_edges_and_stripped_category(self):
        for score in (1, 2.49, 2.5, 3.5, 3.51, 5):
            ok, result = ai_manager.validate_ai_response(_for_score(score))
            self.assertTrue(ok, (score, result))
            self.assertAlmostEqual(result["risk_score"], (float(score) - 1) / 4)

        padded = _for_score(3.0, risk_category="  Moderate  ")
        ok, result = ai_manager.validate_ai_response(padded)
        self.assertTrue(ok, result)
        self.assertEqual(result["risk_category"], "Moderate")

    def test_out_of_range_stress_score_fails(self):
        for bad in (0.9, 5.1, 0, 6, -1, True, False, None, "high", "",
                    float("nan"), float("inf"), float("-inf")):
            ok, message = ai_manager.validate_ai_response(_for_score(3.0, stress_score=bad))
            self.assertFalse(ok, bad)
            self.assertIn("stress_score", message)

    def test_tier_mismatch_fails(self):
        low_score_high_tier = _for_score(
            2.0,
            risk_category="High",
            soft_label="Please reach out",
            speak_prominence="high",
        )
        self.assertFalse(ai_manager.validate_ai_response(low_score_high_tier)[0])

        label_mismatch = _for_score(
            4.0,
            risk_category="High",
            soft_label="You're doing ok",
            speak_prominence="high",
        )
        self.assertFalse(ai_manager.validate_ai_response(label_mismatch)[0])

        prominence_mismatch = _for_score(
            4.0,
            risk_category="High",
            soft_label="Please reach out",
            speak_prominence="low",
        )
        self.assertFalse(ai_manager.validate_ai_response(prominence_mismatch)[0])

    def test_removed_ids_are_rejected(self):
        self.assertNotIn("emotional_distress", ai_manager.ALLOWED_PRIMARY_STRESSORS)
        self.assertNotIn("feelings_check_in", ai_manager.ALLOWED_TIP_IDS)
        self.assertFalse(ai_manager.validate_ai_response(
            _for_score(3.0, primary_stressors=["emotional_distress"])
        )[0])
        self.assertFalse(ai_manager.validate_ai_response(
            _for_score(3.0, primary_stressors=["academic_overload", "emotional_distress"])
        )[0])
        self.assertFalse(ai_manager.validate_ai_response(
            _for_score(3.0, tips=["feelings_check_in"])
        )[0])
        self.assertFalse(ai_manager.validate_ai_response(
            _for_score(3.0, tips=["short_breaks", "feelings_check_in"])
        )[0])

    def test_remaining_tip_ids_still_format(self):
        self.assertTrue(ai_manager.ALLOWED_TIP_IDS <= set(io_manager.TIPS_ALLOWLIST))
        formatted = io_manager.format_tips(sorted(ai_manager.ALLOWED_TIP_IDS))
        self.assertEqual(
            {item["id"] for item in formatted["items"]},
            set(ai_manager.ALLOWED_TIP_IDS),
        )
        legacy = io_manager.format_tips(["feelings_check_in"])
        self.assertEqual(legacy["items"][0]["id"], "feelings_check_in")


class GeminiCallTests(unittest.TestCase):
    def test_mismatch_is_an_invalid_response(self):
        def generate_fn(prompt, api_key, model_name):
            return json.dumps(_for_score(
                4.2,
                risk_category="Low",
                soft_label="You're doing ok",
                speak_prominence="low",
            ))

        ok, result, error = ai_manager.call_gemini(
            "check-in",
            api_key="stub",
            max_attempts=1,
            retry_delay_sec=0,
            generate_fn=generate_fn,
        )
        self.assertFalse(ok)
        self.assertIsNone(result)
        self.assertEqual(error["error_code"], "invalid_response")
        self.assertEqual(error["source"], "gemini")

    def test_missing_api_key_does_not_call_generator(self):
        def generate_fn(prompt, api_key, model_name):
            raise AssertionError("generator must not be called")

        with patch.object(ai_manager, "_default_generate", generate_fn):
            ok, result, error = ai_manager.call_gemini("check-in", api_key="  ")
        self.assertFalse(ok)
        self.assertIsNone(result)
        self.assertEqual(error["error_code"], "missing_api_key")
        self.assertEqual(error["source"], "gemini")

        with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
            with patch.object(ai_manager, "_default_generate", generate_fn):
                ok, result, error = ai_manager.call_gemini("check-in")
        self.assertFalse(ok)
        self.assertEqual(error["error_code"], "missing_api_key")

    def test_structured_schema_is_sent_with_the_mime_type(self):
        captured = {}

        class FakeModels:
            def generate_content(self, *, model, contents, config):
                captured["model"] = model
                captured["contents"] = contents
                captured["config"] = config

                class Response:
                    text = "{}"

                return Response()

        class FakeClient:
            def __init__(self, *, api_key, http_options):
                captured["api_key"] = api_key
                self.models = FakeModels()

        with patch("google.genai.Client", FakeClient):
            text = ai_manager._default_generate("prompt text", "secret-key", "gemini-3.6-flash")

        self.assertEqual(text, "{}")
        self.assertEqual(captured["api_key"], "secret-key")
        self.assertEqual(captured["model"], "gemini-3.6-flash")
        config = captured["config"]
        self.assertEqual(config["response_mime_type"], "application/json")
        self.assertIs(config["response_schema"], ai_manager.RESPONSE_SCHEMA)
        self.assertEqual(config["temperature"], 0.2)
        self.assertNotIn("risk_score", config["response_schema"]["properties"])

        properties = ai_manager.RESPONSE_SCHEMA["properties"]
        self.assertEqual(properties["risk_category"]["enum"], ["Low", "Moderate", "High"])
        self.assertEqual(properties["soft_label"]["enum"], list(ai_manager.SOFT_LABELS))
        self.assertEqual(properties["speak_prominence"]["enum"], ["low", "medium", "high"])
        self.assertEqual(
            set(properties["primary_stressors"]["items"]["enum"]),
            set(ai_manager.ALLOWED_PRIMARY_STRESSORS),
        )
        self.assertEqual(
            set(properties["tips"]["items"]["enum"]),
            set(ai_manager.ALLOWED_TIP_IDS),
        )
        self.assertNotIn("emotional_distress", properties["primary_stressors"]["items"]["enum"])
        self.assertNotIn("feelings_check_in", properties["tips"]["items"]["enum"])

        from google.genai import types
        types.GenerateContentConfig.model_validate({
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "response_schema": ai_manager.RESPONSE_SCHEMA,
            "automatic_function_calling": {"disable": True},
        })


if __name__ == "__main__":
    unittest.main()
