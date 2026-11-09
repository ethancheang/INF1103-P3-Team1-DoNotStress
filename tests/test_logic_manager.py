"""Tests for Logic Manager core behaviour.

Uses hardcoded sample AI replies (sample_ai_records) so no live Gemini API
is required. Covers scoring, business rules, response validation, and
failure cases (malformed AI output, score mismatch).

Written with unittest, so it runs with either test runner:
    python -m unittest discover -s tests -v
    python -m pytest -v
"""

from __future__ import annotations

import copy
import unittest

from logic_manager import (
    AIScoreVerifier,
    EnrichedRecord,
    LogicManager,
    RecordValidationError,
    RiskTier,
    RuleContext,
    SafetyOverrideRule,
    ScoreCalculator,
    ScoreMismatchError,
    StudentAnswers,
    SupportPriorityRule,
)
from sample_ai_records import HIGH_LOW_SUPPORT, LOW_STRESS


class ScoreCalculatorTests(unittest.TestCase):
    def setUp(self):
        self.calculator = ScoreCalculator()

    def test_low_stress_score_within_tolerance(self):
        answers = StudentAnswers.from_mapping(LOW_STRESS)
        score = self.calculator.stress_score(answers)
        self.assertTrue(self.calculator.within_tolerance(LOW_STRESS["stress_score"], score))

    def test_tier_for_low(self):
        self.assertIs(self.calculator.tier_for(1.8), RiskTier.LOW)

    def test_tier_for_moderate(self):
        self.assertIs(self.calculator.tier_for(3.2), RiskTier.MODERATE)

    def test_tier_for_high(self):
        self.assertIs(self.calculator.tier_for(4.5), RiskTier.HIGH)


class BusinessRuleTests(unittest.TestCase):
    @staticmethod
    def context(record_dict):
        enriched = EnrichedRecord.from_dict(record_dict)
        scores = ScoreCalculator().breakdown(enriched.answers)
        return RuleContext(record=enriched, scores=scores)

    def test_safety_override_raises_to_high(self):
        record = copy.deepcopy(LOW_STRESS)
        record["safety_flag"] = True
        outcome = SafetyOverrideRule().evaluate(self.context(record))
        self.assertTrue(outcome.triggered)
        self.assertIs(outcome.minimum_tier, RiskTier.HIGH)
        self.assertIn("talk_to_someone", outcome.lead_tips)

    def test_support_priority_fires_on_high_plus_low_support(self):
        outcome = SupportPriorityRule().evaluate(self.context(HIGH_LOW_SUPPORT))
        self.assertTrue(outcome.triggered)
        self.assertIn("talk_to_someone", outcome.lead_tips)

    def test_support_priority_does_not_fire_on_low(self):
        outcome = SupportPriorityRule().evaluate(self.context(LOW_STRESS))
        self.assertFalse(outcome.triggered)


class LogicManagerEvaluateTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager(calculator=ScoreCalculator())

    def test_evaluate_low_stress_succeeds(self):
        result = self.logic.evaluate(LOW_STRESS)
        self.assertIs(result.tier, RiskTier.LOW)

    def test_evaluate_high_low_support(self):
        result = self.logic.evaluate(HIGH_LOW_SUPPORT)
        self.assertIs(result.tier, RiskTier.HIGH)
        self.assertTrue(result.support_priority)

    def test_malformed_missing_fields_raises(self):
        bad = {"student_id": "x", "safety_flag": False}  # missing AI fields
        with self.assertRaises(RecordValidationError):
            self.logic.evaluate(bad)

    def test_score_mismatch_raises(self):
        bad = copy.deepcopy(LOW_STRESS)
        bad["stress_score"] = 4.9  # deliberately wrong
        with self.assertRaises(ScoreMismatchError):
            self.logic.evaluate(bad)


class AIScoreVerifierTests(unittest.TestCase):
    def setUp(self):
        self.verifier = AIScoreVerifier(ScoreCalculator())

    def test_verifier_accepts_matching_score(self):
        self.assertIsNone(self.verifier.verify(LOW_STRESS, LOW_STRESS))

    def test_verifier_rejects_mismatch(self):
        bad = copy.deepcopy(LOW_STRESS)
        bad["stress_score"] = 5.0
        self.assertIsNotNone(self.verifier.verify(bad, LOW_STRESS))


if __name__ == "__main__":
    unittest.main()
