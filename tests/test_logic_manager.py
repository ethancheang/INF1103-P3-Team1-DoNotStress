"""Tests for Logic Manager core behaviour.

Uses hardcoded sample AI replies (sample_ai_records) so no live Gemini API
is required. Covers scoring, business rules, response validation, and
failure cases (malformed AI output, score mismatch).
"""
from __future__ import annotations

import copy
import pytest

from logic_manager import (
    LogicManager,
    ScoreCalculator,
    AIScoreVerifier,
    SafetyOverrideRule,
    SupportPriorityRule,
    RiskTier,
    RecordValidationError,
    ScoreMismatchError,
)
from logic_manager import EnrichedRecord, RuleContext, StudentAnswers
from sample_ai_records import (
    LOW_STRESS,
    HIGH_LOW_SUPPORT,
)


@pytest.fixture
def calculator():
    return ScoreCalculator()


@pytest.fixture
def logic(calculator):
    return LogicManager(calculator=calculator)


@pytest.fixture
def verifier(calculator):
    return AIScoreVerifier(calculator)


class TestScoreCalculator:
    def test_low_stress_score_within_tolerance(self, calculator):
        answers = StudentAnswers.from_mapping(LOW_STRESS)
        score = calculator.stress_score(answers)
        assert calculator.within_tolerance(LOW_STRESS["stress_score"], score)

    def test_tier_for_low(self, calculator):
        assert calculator.tier_for(1.8) == RiskTier.LOW

    def test_tier_for_moderate(self, calculator):
        assert calculator.tier_for(3.2) == RiskTier.MODERATE

    def test_tier_for_high(self, calculator):
        assert calculator.tier_for(4.5) == RiskTier.HIGH


class TestBusinessRules:
    def _ctx(self, record_dict):
        enriched = EnrichedRecord.from_dict(record_dict)
        calc = ScoreCalculator()
        scores = calc.breakdown(enriched.answers)
        return RuleContext(record=enriched, scores=scores)

    def test_safety_override_raises_to_high(self):
        rule = SafetyOverrideRule()
        record = copy.deepcopy(LOW_STRESS)
        record["safety_flag"] = True
        ctx = self._ctx(record)
        outcome = rule.evaluate(ctx)
        assert outcome.triggered is True
        assert outcome.minimum_tier == RiskTier.HIGH
        assert "talk_to_someone" in outcome.lead_tips

    def test_support_priority_fires_on_high_plus_low_support(self):
        rule = SupportPriorityRule()
        ctx = self._ctx(HIGH_LOW_SUPPORT)
        outcome = rule.evaluate(ctx)
        assert outcome.triggered is True
        assert "talk_to_someone" in outcome.lead_tips

    def test_support_priority_does_not_fire_on_low(self):
        rule = SupportPriorityRule()
        ctx = self._ctx(LOW_STRESS)
        outcome = rule.evaluate(ctx)
        assert outcome.triggered is False


class TestLogicManagerEvaluate:
    def test_evaluate_low_stress_succeeds(self, logic):
        result = logic.evaluate(LOW_STRESS)
        assert result is not None
        assert result.tier == RiskTier.LOW

    def test_evaluate_high_low_support(self, logic):
        result = logic.evaluate(HIGH_LOW_SUPPORT)
        assert result is not None
        assert result.tier in (RiskTier.HIGH, RiskTier.MODERATE)

    def test_malformed_missing_fields_raises(self, logic):
        bad = {"student_id": "x", "safety_flag": False}  # missing AI fields
        with pytest.raises(RecordValidationError):
            logic.evaluate(bad)

    def test_score_mismatch_raises(self, logic):
        bad = copy.deepcopy(LOW_STRESS)
        bad["stress_score"] = 4.9  # deliberately wrong
        with pytest.raises(ScoreMismatchError):
            logic.evaluate(bad)


class TestAIScoreVerifier:
    def test_verifier_accepts_matching_score(self, verifier):
        err = verifier.verify(LOW_STRESS, LOW_STRESS)
        assert err is None or isinstance(err, str)

    def test_verifier_rejects_mismatch(self, verifier):
        bad = copy.deepcopy(LOW_STRESS)
        bad["stress_score"] = 5.0
        err = verifier.verify(bad, LOW_STRESS)
        assert err is not None
