"""Extra tests for logic_manager."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import logic_manager as lm


OK_LABEL = "You're doing ok"


def _enriched(**overrides):
    """A calm, valid AI-enriched record; each test overrides only what it needs."""
    record = {
        "student_id": "2605581",
        "sleep_hours": 8.0,
        "stress_level": 3,
        "academic_workload": 4,
        "financial_stress": 2,
        "social_support": 8,
        "risk_score": 0.22,
        "risk_category": "Low",
        "primary_stressors": ["high_stress"],
        "confidence": 0.80,
        "reasoning": "Signals look steady overall.",
        "soft_label": OK_LABEL,
        "tips": ["sleep_routine", "short_breaks"],
        "speak_prominence": "low",
    }
    record.update(overrides)
    return record


# ---------------------------------------------------------------------------
# Safe handling of the caller's data
# ---------------------------------------------------------------------------

def test_huge_numbers_are_handled_without_a_crash():
    bad_score = lm.apply_logic(_enriched(risk_score=10 ** 400))
    assert bad_score["ok"] is False
    assert "risk_score" in bad_score["invalid"]

    huge_stress = lm.apply_logic(_enriched(stress_level=10 ** 400))
    assert huge_stress["ok"] is True
    assert huge_stress["logic_rule"] == "ai_clamped"
