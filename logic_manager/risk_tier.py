"""RiskTier: the three outcome tiers and their wording."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum


class RiskTier(Enum):
    """The three outcome tiers and the wording that goes with each one.

    These bands are team guidance, not clinical cut-offs or a diagnosis.
    """

    #         category    soft label           prominence  severity
    LOW = ("Low", "You're doing ok", "low", 1)
    MODERATE = ("Moderate", "Worth a check-in", "medium", 2)
    HIGH = ("High", "Please reach out", "high", 3)

    def __init__(self, category: str, soft_label: str, speak_prominence: str, severity: int) -> None:
        self._category = category
        self._soft_label = soft_label
        self._speak_prominence = speak_prominence
        self._severity = severity

    @property
    def category(self) -> str:
        """The risk_category value: "Low", "Moderate" or "High"."""
        return self._category

    @property
    def soft_label(self) -> str:
        """The student-facing tier name, e.g. "Worth a check-in"."""
        return self._soft_label

    @property
    def speak_prominence(self) -> str:
        """How strongly the UI highlights "Talk to someone": low, medium or high."""
        return self._speak_prominence

    @property
    def severity(self) -> int:
        """1 (Low) to 3 (High). Used to pick the more serious of two tiers."""
        return self._severity

    @property
    def recommended_support(self) -> str:
        """Short internal note stored with each record (data_manager requires it)."""
        return f"Internal: {self._category.lower()} stress. The UI shows tips, not this field."

    @classmethod
    def from_category(cls, category: object) -> RiskTier:
        """The tier whose risk_category equals ``category``. Raises ValueError."""
        for tier in cls:
            if tier.category == category:
                return tier
        raise ValueError(f"Unknown risk_category: {category!r}")

    @classmethod
    def most_severe(cls, tiers: Iterable[RiskTier]) -> RiskTier:
        """The most serious tier in ``tiers``. Rules can raise a tier, never lower it."""
        return max(tiers, key=lambda tier: tier.severity)
