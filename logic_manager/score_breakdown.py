"""ScoreBreakdown: Logic's own scores for one set of answers."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .risk_tier import RiskTier


@dataclass(frozen=True)
class ScoreBreakdown:
    """Logic's own scores for one set of answers (kept as an audit of Gemini)."""

    scored_items: Mapping[str, int]
    stress_score: float
    support_mean: float
    support_item_count: int
    tier: RiskTier
