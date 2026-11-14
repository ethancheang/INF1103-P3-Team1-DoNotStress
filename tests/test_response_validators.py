"""Each field check in ai_manager.validate_ai_response: good values, bad values, schema."""
import unittest

import ai_manager
from plain_tests import case, function_suite

KEYS = ai_manager.RAW_ANSWER_KEYS
SCHEMA = ai_manager.RESPONSE_SCHEMA["properties"]


def _reply(**overrides):
    """A schema-valid Gemini reply; tests change one field at a time."""
    reply = {
        "scored_items": {key: 3 for key in KEYS},
        "stress_score": 3.0,
        "risk_category": "Moderate",
        "primary_stressors": ["academic_overload"],
        "confidence": 0.8,
        "reasoning": "You have a lot on right now.",
        "soft_label": "Worth a check-in",
        "tips": ["short_breaks"],
        "speak_prominence": "medium",
    }
    reply.update(overrides)
    return reply


def _check(field, value):
    """(ok, cleaned value or error message) for one field of a reply."""
    ok, result = ai_manager.validate_ai_response(_reply(**{field: value}))
    return (ok, result[field]) if ok else (ok, result)


def test_every_field_check_rejects_junk_and_names_its_field():
    fields = ("scored_items", "stress_score", "soft_label", "risk_category",
              "primary_stressors", "tips", "confidence", "reasoning")
    for field in fields:
        with case(field=field):
            assert "type" in SCHEMA[field]
            ok, message = _check(field, object())
            assert ok is False
            assert field.split("_")[0] in message


def test_scored_items():
    good = {key: 1 for key in KEYS}
    assert _check("scored_items", good) == (True, good)
    missing = {key: 1 for key in KEYS[1:]}
    for bad in (missing, {**good, KEYS[0]: 6}, {**good, KEYS[0]: True},
                {**good, KEYS[0]: 2.0}, {**good, "extra": 3}, [1, 2]):
        with case(bad=bad):
            assert _check("scored_items", bad)[0] is False
    assert SCHEMA["scored_items"]["required"] == list(KEYS)


def test_score_and_confidence_share_the_range_check():
    assert _check("stress_score", "2.5") == (True, 2.5)
    assert _check("confidence", 0) == (True, 0.0)
    for bad in (0.99, 5.01, True, None, float("nan")):
        with case(bad=bad):
            assert _check("stress_score", bad)[0] is False
    for bad in (-0.1, 1.1, False, "high", float("inf")):
        with case(bad=bad):
            assert _check("confidence", bad)[0] is False
    assert _check("stress_score", 9)[1] == (
        "stress_score must be a float between 1.0 and 5.0.")
    assert (SCHEMA["stress_score"]["minimum"],
            SCHEMA["stress_score"]["maximum"]) == (1.0, 5.0)


def test_choices_strip_spaces_and_soft_label_accepts_curly_quotes():
    assert _check("risk_category", "  High ") == (True, "High")
    assert _check("risk_category", "Critical") == (
        False, 'risk_category must be "Low", "Moderate", or "High".')
    assert _check("soft_label", "You’re doing ok") == (True, "You're doing ok")
    assert _check("soft_label", "Please reach out") == (True, "Please reach out")
    assert _check("soft_label", "Doing great")[0] is False
    assert SCHEMA["soft_label"]["enum"] == list(ai_manager.SOFT_LABELS)


def test_id_lists_drop_repeats_and_respect_their_limits():
    assert _check("primary_stressors", []) == (True, [])
    assert _check("primary_stressors",
                  [" academic_overload", "academic_overload"]) == (
        True, ["academic_overload"])
    assert _check("primary_stressors", ["made_up"])[0] is False
    assert "emotional_distress" not in ai_manager.ALLOWED_PRIMARY_STRESSORS
    assert _check("tips", ["short_breaks", "short_breaks"]) == (
        True, ["short_breaks"])
    for bad in ([], ["a", "b", "c", "d"], ["short_breaks", 3],
                ["feelings_check_in"]):
        with case(bad=bad):
            assert _check("tips", bad)[0] is False
    assert SCHEMA["tips"]["minItems"] == 1
    assert SCHEMA["tips"]["maxItems"] == 3
    assert "minItems" not in SCHEMA["primary_stressors"]


def test_reasoning_must_be_real_text():
    assert _check("reasoning", "  Kind. ") == (True, "Kind.")
    assert _check("reasoning", "   ")[0] is False


def load_tests(loader, tests, pattern):
    """Let `python -m unittest discover -s tests` run this file's tests."""
    return function_suite(globals())


if __name__ == "__main__":
    unittest.main()
