"""Gemini calculates the stress average from raw answers. These tests never call the API."""
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
        "scored_items": {key: 3 for key in ai_manager.RAW_ANSWER_KEYS},
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
        self.assertIn("6 - answer", prompt)
        self.assertIn("scored_items", prompt)
        self.assertIn("rounded to 2 decimal places", prompt)
        self.assertIn("8 or more hours -> 1", prompt)
        self.assertIn("otherwise 5", prompt)
        self.assertNotIn("estimate", prompt.lower())

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
            scored, stress = ai_manager.expected_stress_score(_checkin())
            return json.dumps(_for_score(
                stress, scored_items=scored, tips=["short_breaks"], primary_stressors=[],
            ))

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
        scored, stress = ai_manager.expected_stress_score(_checkin())
        self.assertEqual(enriched["source"], "gemini")
        self.assertEqual(enriched["stress_score"], stress)
        self.assertEqual(enriched["scored_items"], scored)
        self.assertAlmostEqual(enriched["risk_score"], (stress - 1) / 4)


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
        scored_items = properties["scored_items"]
        self.assertEqual(scored_items["type"], "OBJECT")
        self.assertEqual(set(scored_items["required"]), set(ai_manager.RAW_ANSWER_KEYS))
        self.assertEqual(set(scored_items["properties"]), set(ai_manager.RAW_ANSWER_KEYS))
        for spec in scored_items["properties"].values():
            self.assertEqual(spec, {"type": "INTEGER", "minimum": 1, "maximum": 5})
        self.assertNotIn("estimate", json.dumps(ai_manager.RESPONSE_SCHEMA).lower())

        from google.genai import types
        types.GenerateContentConfig.model_validate({
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "response_schema": ai_manager.RESPONSE_SCHEMA,
            "automatic_function_calling": {"disable": True},
        })


def _minimum_stress():
    """Answers that convert to 1 on every item. stress_score is 1.00."""
    return {
        "pss_1": 1,
        "pss_2": 5,
        "pss_3": 5,
        "pss_4": 1,
        "sleep_hours_avg": 8,
        "sleep_quality": 1,
        "pas_workload": 1,
        "pas_catchup": 1,
        "fin_stress": 1,
        "mspss_friends": 5,
        "mspss_family": 5,
        "survey_version": "evidence-v3",
    }


def _exact_reply(answers, **overrides):
    scored, stress = ai_manager.expected_stress_score(answers)
    payload = _for_score(stress, scored_items=scored)
    payload.update(overrides)
    return payload


class FormulaTests(unittest.TestCase):
    def test_exact_response_passes(self):
        answers = _minimum_stress()
        ok, result = ai_manager.validate_ai_response(_exact_reply(answers), answers)
        self.assertTrue(ok, result)
        self.assertEqual(result["scored_items"], {key: 1 for key in ai_manager.RAW_ANSWER_KEYS})
        self.assertEqual(result["stress_score"], 1.0)
        self.assertEqual(result["risk_category"], "Low")

        def generate_fn(prompt, api_key, model_name):
            return json.dumps(_exact_reply(answers))

        ok, enriched, error = ai_manager.analyse_student(
            answers, api_key="stub", max_attempts=1, retry_delay_sec=0, generate_fn=generate_fn,
        )
        self.assertTrue(ok, error)
        self.assertEqual(enriched["stress_score"], 1.0)
        self.assertEqual(enriched["scored_items"]["sleep_hours_avg"], 1)

    def test_off_by_one_scored_item_fails(self):
        answers = _minimum_stress()
        reply = _exact_reply(answers)
        reply["scored_items"] = dict(reply["scored_items"])
        reply["scored_items"]["pss_1"] = 2
        ok, message = ai_manager.validate_ai_response(reply, answers)
        self.assertFalse(ok)
        self.assertIn("scored_items", message)

        def generate_fn(prompt, api_key, model_name):
            return json.dumps(reply)

        ok, result, error = ai_manager.call_gemini(
            "check-in", api_key="stub", max_attempts=1, retry_delay_sec=0,
            generate_fn=generate_fn, answers=answers,
        )
        self.assertFalse(ok)
        self.assertIsNone(result)
        self.assertEqual(error["error_code"], "invalid_response")

        skipped, _ = ai_manager.validate_ai_response(reply)
        self.assertTrue(skipped)

    def test_stress_score_off_by_a_tenth_fails(self):
        answers = _minimum_stress()
        reply = _exact_reply(answers, stress_score=1.1)
        ok, message = ai_manager.validate_ai_response(reply, answers)
        self.assertFalse(ok)
        self.assertIn("stress_score", message)

        def generate_fn(prompt, api_key, model_name):
            return json.dumps(reply)

        ok, result, error = ai_manager.analyse_student(
            answers, api_key="stub", max_attempts=1, retry_delay_sec=0, generate_fn=generate_fn,
        )
        self.assertFalse(ok)
        self.assertEqual(error["error_code"], "invalid_response")

    def test_reverse_items_and_sleep_conversion(self):
        answers = _minimum_stress()
        scored, stress = ai_manager.expected_stress_score(answers)
        self.assertEqual(stress, 1.0)
        for key in ("pss_2", "pss_3", "mspss_friends", "mspss_family"):
            self.assertEqual(scored[key], 1)
            flipped = dict(answers, **{key: 1})
            converted, total = ai_manager.expected_stress_score(flipped)
            self.assertEqual(converted[key], 5)
            self.assertEqual(total, round(15 / 11, 2))

        for hours, band in (
            (14, 1), (8.5, 1), (8, 1), (7.5, 2), (7, 2), (6.5, 3), (6, 3),
            (5.5, 4), (5, 4), (4.5, 5), (0, 5),
        ):
            converted, _ = ai_manager.expected_stress_score(
                dict(answers, sleep_hours_avg=hours)
            )
            self.assertEqual(converted["sleep_hours_avg"], band, hours)

        short_sleep = dict(answers, sleep_hours_avg=4.5)
        reply = _exact_reply(short_sleep)
        ok, result = ai_manager.validate_ai_response(reply, short_sleep)
        self.assertTrue(ok, result)
        self.assertEqual(result["scored_items"]["sleep_hours_avg"], 5)
        self.assertEqual(result["stress_score"], round(15 / 11, 2))


class ApiFault(Exception):
    def __init__(self, message, code=None):
        super().__init__(message)
        self.code = code


def _ok_body():
    return json.dumps(_for_score(3.0))


class FallbackTests(unittest.TestCase):
    def _call(self, generate, **overrides):
        options = dict(
            api_key="stub-key",
            max_attempts=3,
            retry_delay_sec=0,
            generate_fn=generate,
        )
        options.update(overrides)
        return ai_manager.call_gemini("check-in", **options)

    def test_model_order_and_call_cap(self):
        self.assertEqual(
            ai_manager.MODEL_CHAIN,
            ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"),
        )
        self.assertNotIn("gemini-flash-latest", ai_manager.MODEL_CHAIN)
        self.assertEqual(ai_manager.MAX_TOTAL_CALLS, 4)

    def test_timeout_then_success_retries_the_same_model(self):
        calls = []

        def generate(prompt, api_key, model_name):
            calls.append(model_name)
            if len(calls) == 1:
                raise ApiFault("timed out")
            return _ok_body()

        ok, result, error = self._call(generate)
        self.assertTrue(ok, error)
        self.assertIsNone(error)
        self.assertEqual(result["source"], "gemini")
        self.assertEqual(calls, ["gemini-3.6-flash", "gemini-3.6-flash"])

    def test_503_on_first_model_falls_back(self):
        calls = []

        def generate(prompt, api_key, model_name):
            calls.append(model_name)
            if model_name == "gemini-3.6-flash":
                raise ApiFault("503 unavailable high demand", 503)
            return _ok_body()

        ok, result, error = self._call(generate)
        self.assertTrue(ok, error)
        self.assertEqual(calls, ["gemini-3.6-flash", "gemini-3.5-flash"])

    def test_404_falls_back_without_retrying_the_same_model(self):
        calls = []

        def generate(prompt, api_key, model_name):
            calls.append(model_name)
            if len(calls) == 1:
                raise ApiFault("404 not found", 404)
            return _ok_body()

        ok, _, error = self._call(generate)
        self.assertTrue(ok, error)
        self.assertEqual(calls, ["gemini-3.6-flash", "gemini-3.5-flash"])

    def test_429_moves_to_the_next_model_without_a_retry(self):
        calls = []

        def generate(prompt, api_key, model_name):
            calls.append(model_name)
            if len(calls) == 1:
                raise ApiFault("429 too many requests", 429)
            return _ok_body()

        ok, _, error = self._call(generate)
        self.assertTrue(ok, error)
        self.assertEqual(calls, ["gemini-3.6-flash", "gemini-3.5-flash"])

    def test_every_model_rate_limited(self):
        calls = []

        def generate(prompt, api_key, model_name):
            calls.append(model_name)
            raise ApiFault("resource exhausted quota", 429)

        ok, result, error = self._call(generate)
        self.assertFalse(ok)
        self.assertIsNone(result)
        self.assertEqual(error["error_code"], "rate_limited")
        self.assertEqual(calls, list(ai_manager.MODEL_CHAIN))
        copy = io_manager.format_ai_error("rate_limited")
        self.assertEqual(copy["error_code"], "rate_limited")
        self.assertEqual(
            copy["body"],
            "Our check-in assistant is busy right now. "
            "Your answers have been saved and will be reviewed soon.",
        )
        self.assertIsNone(copy["error"])

    def test_bad_json_is_invalid_after_the_call_cap(self):
        calls = []

        def generate(prompt, api_key, model_name):
            calls.append(model_name)
            return "not json"

        ok, result, error = self._call(generate)
        self.assertFalse(ok)
        self.assertIsNone(result)
        self.assertEqual(error["error_code"], "invalid_response")
        self.assertEqual(len(calls), ai_manager.MAX_TOTAL_CALLS)

    def test_missing_key_never_calls_the_generator(self):
        def generate(prompt, api_key, model_name):
            raise AssertionError("generator must not be called")

        with patch.object(ai_manager, "_default_generate", generate):
            ok, result, error = ai_manager.call_gemini("check-in", api_key="  ")
        self.assertFalse(ok)
        self.assertIsNone(result)
        self.assertEqual(error["error_code"], "missing_api_key")

    def test_total_calls_never_exceed_the_cap(self):
        calls = []

        def generate(prompt, api_key, model_name):
            calls.append(model_name)
            raise ApiFault("timed out")

        ok, _, error = self._call(generate)
        self.assertFalse(ok)
        self.assertEqual(error["error_code"], "timeout")
        self.assertLessEqual(len(calls), ai_manager.MAX_TOTAL_CALLS)
        self.assertEqual(len(calls), ai_manager.MAX_TOTAL_CALLS)
        self.assertLessEqual(max(calls.count(name) for name in calls), 2)

    def test_api_key_is_absent_from_logs_and_error_detail(self):
        secret = "sk-live-DO-NOT-PRINT-991122"
        calls = []

        def generate(prompt, api_key, model_name):
            calls.append(model_name)
            raise ApiFault(f"403 permission denied using {api_key}", 403)

        with self.assertLogs("ai_manager", level="DEBUG") as captured:
            ok, result, error = self._call(generate, api_key=secret)
        self.assertFalse(ok)
        self.assertIsNone(result)
        self.assertNotEqual(error["error_code"], "missing_api_key")
        blob = "\n".join(captured.output) + "\n" + error["detail"]
        self.assertNotIn(secret, blob)
        self.assertIn("[redacted]", error["detail"])
        self.assertLessEqual(len(calls), ai_manager.MAX_TOTAL_CALLS)

    def test_rate_limit_still_saves_a_pending_checkin(self):
        import tempfile
        from pathlib import Path

        from main import create_app

        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        path = Path(temp.name) / "records.json"

        def generate(prompt, api_key, model_name):
            raise ApiFault("429 quota", 429)

        app = create_app({
            "TESTING": True,
            "SECRET_KEY": "test-only",
            "AI_GENERATE_FN": generate,
            "AI_MAX_ATTEMPTS": 3,
            "AI_RETRY_DELAY_SEC": 0,
            "DATA_PATH": str(path),
        })
        client = app.test_client()
        client.get("/")
        with client.session_transaction() as session:
            token = session["csrf_token"]
        values = dict(
            student_id="2605581", pss_1=3, pss_2=3, pss_3=3, pss_4=3,
            sleep_hours_avg=6.5, sleep_quality=3, pas_workload=3, pas_catchup=3,
            fin_stress=3, mspss_friends=3, mspss_family=3,
            feelings_text="PRIVATE NOTE that must not be stored",
        )
        response = client.post("/", json=values, headers={"X-CSRF-Token": token})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["error_code"], "rate_limited")
        stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(stored[0]["status"], "pending")
        self.assertNotIn("feelings_text", stored[0])
        self.assertNotIn("PRIVATE NOTE", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
