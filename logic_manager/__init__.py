"""DoNotStress Logic Manager (Phase 2, object-oriented).

Applies the team's domain rules to a check-in that Gemini has already
analysed: it re-checks Gemini's score, runs the business rules, classifies
the outcome, and prepares the result for storage and for display.

Wiring in campus_app.py::

    from logic_manager import AIScoreVerifier, LogicManager, ScoreCalculator

    calculator = ScoreCalculator()                  # one set of scoring numbers,
    logic = LogicManager(calculator=calculator)
    verifier = AIScoreVerifier(calculator)          # shared with the AI Manager

    enriched = ai.analyse(student)                  # dict from ai_manager
    result = logic.evaluate(enriched)               # EvaluationResult, or LogicManagerError
    store.save(result.to_record())                  # data_manager
    display.display_result(result.to_display())     # io_manager (ResultDisplay)

Plain Python only: no printing, no network and no files. Every method gives
the same answer for the same input, so tests can use hardcoded sample AI
replies instead of the live API.

Each class lives in its own .py file (Coding Requirements).
"""

from __future__ import annotations

from .ai_assessment import AIAssessment
from .ai_score_verifier import AIScoreVerifier
from .base_evaluator import BaseEvaluator
from .context_flag_rule import ContextFlagRule
from .enriched_record import EnrichedRecord
from .evaluation_result import EvaluationResult
from .factor_card import FactorCard
from .factor_card_builder import FactorCardBuilder
from .finance_flag_rule import FinanceFlagRule
from .logic_manager_error import LogicManagerError
from .logic_manager import LogicManager
from .record_validation_error import RecordValidationError
from .risk_tier import RiskTier
from .rule_context import RuleContext
from .rule_outcome import RuleOutcome
from .rule_report import RuleReport
from .safety_override_rule import SafetyOverrideRule
from .score_breakdown import ScoreBreakdown
from .score_calculator import ScoreCalculator
from .score_mismatch_error import ScoreMismatchError
from .scoring_policy import ScoringPolicy
from .sleep_flag_rule import SleepFlagRule
from .student_answers import StudentAnswers
from .support_flag_rule import SupportFlagRule
from .support_priority_rule import SupportPriorityRule
from .tip_planner import TipPlanner
from .workload_flag_rule import WorkloadFlagRule

__all__ = [
    "AIAssessment",
    "AIScoreVerifier",
    "BaseEvaluator",
    "ContextFlagRule",
    "EnrichedRecord",
    "EvaluationResult",
    "FactorCard",
    "FactorCardBuilder",
    "FinanceFlagRule",
    "LogicManager",
    "LogicManagerError",
    "RecordValidationError",
    "RiskTier",
    "RuleContext",
    "RuleOutcome",
    "RuleReport",
    "SafetyOverrideRule",
    "ScoreBreakdown",
    "ScoreCalculator",
    "ScoreMismatchError",
    "ScoringPolicy",
    "SleepFlagRule",
    "StudentAnswers",
    "SupportFlagRule",
    "SupportPriorityRule",
    "TipPlanner",
    "WorkloadFlagRule",
]
