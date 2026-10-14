"""Gemini calculates the stress average from raw answers. These tests never call the API."""
import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import ai_manager
import io_manager
import survey
from plain_tests import capture_logs, function_suite


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


# --- Prompt ----------------------------------------------------------------

def test_prompt_has_raw_answers_and_wording_only():
    prompt = ai_manager.build_prompt(_checkin())
    payload = _input_payload(prompt)

    assert set(payload) == set(ai_manager.STUDENT_PROMPT_FIELDS)
    assert payload["pss_1"] == 4
    assert payload["pss_2"] == 2
    assert payload["sleep_hours_avg"] == 6.5
    assert payload["mspss_family"] == 5
    assert payload["survey_version"] == survey.VERSION
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
        assert banned not in payload

    assert survey.QUESTION_MAP["pss_1"]["prompt"] in prompt
    assert survey.QUESTION_MAP["fin_stress"]["prompt"] in prompt
    assert "1 = Never" in prompt
    assert "5 = Very often" in prompt
    assert "1 = No stress at all" in prompt
    assert "5 = Overwhelming stress" in prompt
    assert "half-hour" in prompt
    assert "positively worded" in prompt.lower()
    assert "Talk to someone" in prompt
    assert "SIT Counselling" in prompt

    assert "2605581" not in prompt
    assert "PRIVATE REFLECTION" not in prompt
    assert "student_id" not in prompt
    assert "feelings_text" not in prompt
    assert "context_flags" not in prompt
    assert "SENTINEL_FLAG" not in prompt
    assert "SENTINEL_CATEGORY" not in prompt
    assert "SENTINEL_SOFT_LABEL" not in prompt
    assert "SENTINEL_PROMINENCE" not in prompt
    assert "9.99" not in prompt
    assert "support_mean" not in prompt
    assert "risk_score" not in prompt
    assert "Speak to advisor" not in prompt
    assert "advisor dashboard" not in prompt
    assert "emotional_distress" not in prompt
    assert "feelings_check_in" not in prompt
    assert "6 - answer" in prompt
    assert "scored_items" in prompt
    assert "rounded to 2 decimal places" in prompt
    assert "8 or more hours -> 1" in prompt
    assert "otherwise 5" in prompt
    assert "estimate" not in prompt.lower()


def test_default_wording_matches_the_questionnaire():
    assert not hasattr(ai_manager, "survey")
    assert [item["key"] for item in ai_manager.DEFAULT_QUESTIONS] == [item["key"] for item in survey.QUESTIONS]
    for default, live in zip(ai_manager.DEFAULT_QUESTIONS, survey.QUESTIONS):
        assert default["prompt"] == live["prompt"]
        assert list(default.get("options") or []) == list(live.get("options") or [])


def test_caller_can_pass_question_wording():
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
    assert ok, error
    assert "UNIQUE WORDING XYZ" in seen["prompt"]
    assert "1 = No" in seen["prompt"]
    assert "2605581" not in seen["prompt"]
    scored, stress = ai_manager.expected_stress_score(_checkin())
    assert enriched["source"] == "gemini"
    assert enriched["stress_score"] == stress
    assert enriched["scored_items"] == scored
    assert round(enriched["risk_score"] - (stress - 1) / 4, 7) == 0


# --- Response Validation ---------------------------------------------------

def test_valid_response_computes_risk_score():
    supplied = _for_score(2.5)
    supplied["risk_score"] = 0.99
    supplied["recommended_support"] = "Speak to advisor"
    ok, result = ai_manager.validate_ai_response(json.dumps(supplied))
    assert ok, result
    assert result["stress_score"] == 2.5
    assert result["risk_score"] == (2.5 - 1) / 4
    assert result["risk_category"] == "Moderate"
    assert result["soft_label"] == "Worth a check-in"
    assert result["speak_prominence"] == "medium"
    assert "advisor" not in result["recommended_support"].lower()
    assert result["recommended_support"].strip()

    for score in (1.0, 3.0, 5.0):
        ok, result = ai_manager.validate_ai_response(_for_score(score))
        assert ok, result
        assert result["risk_score"] == (score - 1) / 4


def test_band_edges_and_stripped_category():
    for score in (1, 2.49, 2.5, 3.5, 3.51, 5):
        ok, result = ai_manager.validate_ai_response(_for_score(score))
        assert ok, (score, result)
        assert round(result["risk_score"] - (float(score) - 1) / 4, 7) == 0

    padded = _for_score(3.0, risk_category="  Moderate  ")
    ok, result = ai_manager.validate_ai_response(padded)
    assert ok, result
    assert result["risk_category"] == "Moderate"


def test_out_of_range_stress_score_fails():
    for bad in (0.9, 5.1, 0, 6, -1, True, False, None, "high", "",
                float("nan"), float("inf"), float("-inf")):
        ok, message = ai_manager.validate_ai_response(_for_score(3.0, stress_score=bad))
        assert not ok, bad
        assert "stress_score" in message


def test_tier_mismatch_fails():
    low_score_high_tier = _for_score(
        2.0,
        risk_category="High",
        soft_label="Please reach out",
        speak_prominence="high",
    )
    assert not ai_manager.validate_ai_response(low_score_high_tier)[0]

    label_mismatch = _for_score(
        4.0,
        risk_category="High",
        soft_label="You're doing ok",
        speak_prominence="high",
    )
    assert not ai_manager.validate_ai_response(label_mismatch)[0]

    prominence_mismatch = _for_score(
        4.0,
        risk_category="High",
        soft_label="Please reach out",
        speak_prominence="low",
    )
    assert not ai_manager.validate_ai_response(prominence_mismatch)[0]


def test_removed_ids_are_rejected():
    assert "emotional_distress" not in ai_manager.ALLOWED_PRIMARY_STRESSORS
    assert "feelings_check_in" not in ai_manager.ALLOWED_TIP_IDS
    assert not (ai_manager.validate_ai_response(
        _for_score(3.0, primary_stressors=["emotional_distress"])
    )[0])
    assert not (ai_manager.validate_ai_response(
        _for_score(3.0, primary_stressors=["academic_overload", "emotional_distress"])
    )[0])
    assert not (ai_manager.validate_ai_response(
        _for_score(3.0, tips=["feelings_check_in"])
    )[0])
    assert not (ai_manager.validate_ai_response(
        _for_score(3.0, tips=["short_breaks", "feelings_check_in"])
    )[0])


def test_remaining_tip_ids_still_format():
    assert ai_manager.ALLOWED_TIP_IDS <= set(io_manager.TIPS_ALLOWLIST)
    formatted = io_manager.format_tips(sorted(ai_manager.ALLOWED_TIP_IDS))
    assert {item["id"] for item in formatted["items"]} == set(ai_manager.ALLOWED_TIP_IDS)
    legacy = io_manager.format_tips(["feelings_check_in"])
    assert legacy["items"][0]["id"] == "feelings_check_in"


# --- Gemini Call -----------------------------------------------------------

def test_mismatch_is_an_invalid_response():
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
    assert not ok
    assert result is None
    assert error["error_code"] == "invalid_response"
    assert error["source"] == "gemini"


def test_missing_api_key_does_not_call_generator():
    def generate_fn(prompt, api_key, model_name):
        raise AssertionError("generator must not be called")

    with patch.object(ai_manager, "_default_generate", generate_fn):
        ok, result, error = ai_manager.call_gemini("check-in", api_key="  ")
    assert not ok
    assert result is None
    assert error["error_code"] == "missing_api_key"
    assert error["source"] == "gemini"

    with patch.dict(os.environ, {"GEMINI_API_KEY": ""}, clear=False):
        with patch.object(ai_manager, "_default_generate", generate_fn):
            ok, result, error = ai_manager.call_gemini("check-in")
    assert not ok
    assert error["error_code"] == "missing_api_key"


def test_structured_schema_is_sent_with_the_mime_type():
    captured = {}

    def fake_generate_content(*, model, contents, config):
        captured["model"] = model
        captured["contents"] = contents
        captured["config"] = config
        return SimpleNamespace(text="{}")

    def fake_client(*, api_key, http_options):
        captured["api_key"] = api_key
        return SimpleNamespace(models=SimpleNamespace(generate_content=fake_generate_content))

    with patch("google.genai.Client", fake_client):
        text = ai_manager._default_generate("prompt text", "secret-key", "gemini-3.6-flash")

    assert text == "{}"
    assert captured["api_key"] == "secret-key"
    assert captured["model"] == "gemini-3.6-flash"
    config = captured["config"]
    assert config["response_mime_type"] == "application/json"
    assert config["response_schema"] is ai_manager.RESPONSE_SCHEMA
    assert config["temperature"] == 0.2
    assert "risk_score" not in config["response_schema"]["properties"]

    properties = ai_manager.RESPONSE_SCHEMA["properties"]
    assert properties["risk_category"]["enum"] == ["Low", "Moderate", "High"]
    assert properties["soft_label"]["enum"] == list(ai_manager.SOFT_LABELS)
    assert properties["speak_prominence"]["enum"] == ["low", "medium", "high"]
    assert set(properties["primary_stressors"]["items"]["enum"]) == set(ai_manager.ALLOWED_PRIMARY_STRESSORS)
    assert set(properties["tips"]["items"]["enum"]) == set(ai_manager.ALLOWED_TIP_IDS)
    assert "emotional_distress" not in properties["primary_stressors"]["items"]["enum"]
    assert "feelings_check_in" not in properties["tips"]["items"]["enum"]
    scored_items = properties["scored_items"]
    assert scored_items["type"] == "OBJECT"
    assert set(scored_items["required"]) == set(ai_manager.RAW_ANSWER_KEYS)
    assert set(scored_items["properties"]) == set(ai_manager.RAW_ANSWER_KEYS)
    for spec in scored_items["properties"].values():
        assert spec == {"type": "INTEGER", "minimum": 1, "maximum": 5}
    assert "estimate" not in json.dumps(ai_manager.RESPONSE_SCHEMA).lower()

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


# --- Formula ---------------------------------------------------------------

def test_exact_response_passes():
    answers = _minimum_stress()
    ok, result = ai_manager.validate_ai_response(_exact_reply(answers), answers)
    assert ok, result
    assert result["scored_items"] == {key: 1 for key in ai_manager.RAW_ANSWER_KEYS}
    assert result["stress_score"] == 1.0
    assert result["risk_category"] == "Low"

    def generate_fn(prompt, api_key, model_name):
        return json.dumps(_exact_reply(answers))

    ok, enriched, error = ai_manager.analyse_student(
        answers, api_key="stub", max_attempts=1, retry_delay_sec=0, generate_fn=generate_fn,
    )
    assert ok, error
    assert enriched["stress_score"] == 1.0
    assert enriched["scored_items"]["sleep_hours_avg"] == 1


def test_off_by_one_scored_item_fails():
    answers = _minimum_stress()
    reply = _exact_reply(answers)
    reply["scored_items"] = dict(reply["scored_items"])
    reply["scored_items"]["pss_1"] = 2
    ok, message = ai_manager.validate_ai_response(reply, answers)
    assert not ok
    assert "scored_items" in message

    def generate_fn(prompt, api_key, model_name):
        return json.dumps(reply)

    ok, result, error = ai_manager.call_gemini(
        "check-in", api_key="stub", max_attempts=1, retry_delay_sec=0,
        generate_fn=generate_fn, answers=answers,
    )
    assert not ok
    assert result is None
    assert error["error_code"] == "invalid_response"

    skipped, _ = ai_manager.validate_ai_response(reply)
    assert skipped


def test_stress_score_off_by_a_tenth_fails():
    answers = _minimum_stress()
    reply = _exact_reply(answers, stress_score=1.1)
    ok, message = ai_manager.validate_ai_response(reply, answers)
    assert not ok
    assert "stress_score" in message

    def generate_fn(prompt, api_key, model_name):
        return json.dumps(reply)

    ok, result, error = ai_manager.analyse_student(
        answers, api_key="stub", max_attempts=1, retry_delay_sec=0, generate_fn=generate_fn,
    )
    assert not ok
    assert error["error_code"] == "invalid_response"


def test_reverse_items_and_sleep_conversion():
    answers = _minimum_stress()
    scored, stress = ai_manager.expected_stress_score(answers)
    assert stress == 1.0
    for key in ("pss_2", "pss_3", "mspss_friends", "mspss_family"):
        assert scored[key] == 1
        flipped = dict(answers, **{key: 1})
        converted, total = ai_manager.expected_stress_score(flipped)
        assert converted[key] == 5
        assert total == round(15 / 11, 2)

    for hours, band in (
        (14, 1), (8.5, 1), (8, 1), (7.5, 2), (7, 2), (6.5, 3), (6, 3),
        (5.5, 4), (5, 4), (4.5, 5), (0, 5),
    ):
        converted, _ = ai_manager.expected_stress_score(
            dict(answers, sleep_hours_avg=hours)
        )
        assert converted["sleep_hours_avg"] == band, hours

    short_sleep = dict(answers, sleep_hours_avg=4.5)
    reply = _exact_reply(short_sleep)
    ok, result = ai_manager.validate_ai_response(reply, short_sleep)
    assert ok, result
    assert result["scored_items"]["sleep_hours_avg"] == 5
    assert result["stress_score"] == round(15 / 11, 2)


def api_fault(message, code=None):
    """Build the error a fake Gemini raises, with an optional HTTP status code."""
    error = RuntimeError(message)
    error.code = code
    return error


def _ok_body():
    return json.dumps(_for_score(3.0))


# --- Fallback --------------------------------------------------------------

def _call(generate, **overrides):
    """Call call_gemini with the fake generator, a stub key and no retry delay."""
    options = dict(
        api_key="stub-key",
        max_attempts=3,
        retry_delay_sec=0,
        generate_fn=generate,
    )
    options.update(overrides)
    return ai_manager.call_gemini("check-in", **options)


def test_model_order_and_call_cap():
    assert ai_manager.MODEL_CHAIN == ("gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite")
    assert "gemini-flash-latest" not in ai_manager.MODEL_CHAIN
    assert ai_manager.MAX_TOTAL_CALLS == 4


def test_timeout_then_success_retries_the_same_model():
    calls = []

    def generate(prompt, api_key, model_name):
        calls.append(model_name)
        if len(calls) == 1:
            raise api_fault("timed out")
        return _ok_body()

    ok, result, error = _call(generate)
    assert ok, error
    assert error is None
    assert result["source"] == "gemini"
    assert calls == ["gemini-3.6-flash", "gemini-3.6-flash"]


def test_503_on_first_model_falls_back():
    calls = []

    def generate(prompt, api_key, model_name):
        calls.append(model_name)
        if model_name == "gemini-3.6-flash":
            raise api_fault("503 unavailable high demand", 503)
        return _ok_body()

    ok, result, error = _call(generate)
    assert ok, error
    assert calls == ["gemini-3.6-flash", "gemini-3.5-flash"]


def test_404_falls_back_without_retrying_the_same_model():
    calls = []

    def generate(prompt, api_key, model_name):
        calls.append(model_name)
        if len(calls) == 1:
            raise api_fault("404 not found", 404)
        return _ok_body()

    ok, _, error = _call(generate)
    assert ok, error
    assert calls == ["gemini-3.6-flash", "gemini-3.5-flash"]


def test_429_moves_to_the_next_model_without_a_retry():
    calls = []

    def generate(prompt, api_key, model_name):
        calls.append(model_name)
        if len(calls) == 1:
            raise api_fault("429 too many requests", 429)
        return _ok_body()

    ok, _, error = _call(generate)
    assert ok, error
    assert calls == ["gemini-3.6-flash", "gemini-3.5-flash"]


def test_every_model_rate_limited():
    calls = []

    def generate(prompt, api_key, model_name):
        calls.append(model_name)
        raise api_fault("resource exhausted quota", 429)

    ok, result, error = _call(generate)
    assert not ok
    assert result is None
    assert error["error_code"] == "rate_limited"
    assert calls == list(ai_manager.MODEL_CHAIN)
    copy = io_manager.format_ai_error("rate_limited")
    assert copy["error_code"] == "rate_limited"
    assert copy["body"] == ("Our check-in assistant is busy right now. "
        "Your answers have been saved and will be reviewed soon.")
    assert copy["error"] is None


def test_bad_json_is_invalid_after_the_call_cap():
    calls = []

    def generate(prompt, api_key, model_name):
        calls.append(model_name)
        return "not json"

    ok, result, error = _call(generate)
    assert not ok
    assert result is None
    assert error["error_code"] == "invalid_response"
    assert len(calls) == ai_manager.MAX_TOTAL_CALLS


def test_missing_key_never_calls_the_generator():
    def generate(prompt, api_key, model_name):
        raise AssertionError("generator must not be called")

    with patch.object(ai_manager, "_default_generate", generate):
        ok, result, error = ai_manager.call_gemini("check-in", api_key="  ")
    assert not ok
    assert result is None
    assert error["error_code"] == "missing_api_key"


def test_total_calls_never_exceed_the_cap():
    calls = []

    def generate(prompt, api_key, model_name):
        calls.append(model_name)
        raise api_fault("timed out")

    ok, _, error = _call(generate)
    assert not ok
    assert error["error_code"] == "timeout"
    assert len(calls) <= ai_manager.MAX_TOTAL_CALLS
    assert len(calls) == ai_manager.MAX_TOTAL_CALLS
    assert max(calls.count(name) for name in calls) <= 2


def test_api_key_is_absent_from_logs_and_error_detail():
    secret = "sk-live-DO-NOT-PRINT-991122"
    calls = []

    def generate(prompt, api_key, model_name):
        calls.append(model_name)
        raise api_fault(f"403 permission denied using {api_key}", 403)

    with capture_logs("ai_manager", level="DEBUG") as captured:
        ok, result, error = _call(generate, api_key=secret)
    assert not ok
    assert result is None
    assert error["error_code"] != "missing_api_key"
    blob = "\n".join(captured.output) + "\n" + error["detail"]
    assert secret not in blob
    assert "[redacted]" in error["detail"]
    assert len(calls) <= ai_manager.MAX_TOTAL_CALLS


def test_rate_limit_still_saves_a_pending_checkin():
    import tempfile
    from pathlib import Path

    from main import create_app

    with tempfile.TemporaryDirectory() as temp_dir:
        path = Path(temp_dir) / "records.json"

        def generate(prompt, api_key, model_name):
            raise api_fault("429 quota", 429)

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
        assert response.status_code == 503
        assert response.json["error_code"] == "rate_limited"
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored[0]["status"] == "pending"
        assert "feelings_text" not in stored[0]
        assert "PRIVATE NOTE" not in path.read_text(encoding="utf-8")


def load_tests(loader, tests, pattern):
    """Let `python -m unittest discover -s tests` run this file's test_ functions."""
    return function_suite(globals())


if __name__ == "__main__":
    unittest.main()
