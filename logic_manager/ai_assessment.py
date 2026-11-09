"""AIAssessment: Gemini's validated analysis of one check-in."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, ClassVar

from .field_reader import FieldReader
from .record_validation_error import RecordValidationError
from .risk_tier import RiskTier


@dataclass(frozen=True)
class AIAssessment:
    """Gemini's validated analysis of one check-in.

    ai_manager has already checked the reply's schema and arithmetic. This
    class keeps what Logic needs with tidy types, and it refuses values that
    disagree with each other (for example a High tier with the "You're doing
    ok" label). The label and prominence are read from ``tier``, so they can
    never drift apart afterwards.
    """

    stress_score: float
    tier: RiskTier
    primary_stressors: tuple[str, ...]
    tips: tuple[str, ...]
    reasoning: str
    confidence: float
    scored_items: Mapping[str, int] | None = None

    REQUIRED_KEYS: ClassVar[tuple[str, ...]] = (
        "stress_score",
        "risk_category",
        "soft_label",
        "speak_prominence",
        "primary_stressors",
        "tips",
        "reasoning",
        "confidence",
    )
    SCORE_MIN: ClassVar[float] = 1.0
    SCORE_MAX: ClassVar[float] = 5.0

    @property
    def risk_category(self) -> str:
        return self.tier.category

    @property
    def soft_label(self) -> str:
        return self.tier.soft_label

    @property
    def speak_prominence(self) -> str:
        return self.tier.speak_prominence

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> AIAssessment:
        """Build from Gemini's validated fields. Raises RecordValidationError."""
        if not isinstance(data, Mapping):
            raise RecordValidationError(invalid=("ai_fields",))
        reader = FieldReader(data)
        values = cls._read(reader)
        reader.raise_if_problems()
        return cls(**values)

    @classmethod
    def _read(cls, reader: FieldReader) -> dict[str, Any]:
        """Read Gemini's fields through ``reader`` (None where a value is unusable)."""
        scored_items = reader.optional_mapping("scored_items")
        return {
            "stress_score": reader.number("stress_score", cls.SCORE_MIN, cls.SCORE_MAX),
            "tier": cls._read_tier(reader),
            "primary_stressors": reader.text_list("primary_stressors"),
            "tips": reader.text_list("tips"),
            "reasoning": reader.text("reasoning"),
            "confidence": reader.number("confidence", 0.0, 1.0),
            "scored_items": None if scored_items is None else MappingProxyType(scored_items),
        }

    @staticmethod
    def _read_tier(reader: FieldReader) -> RiskTier | None:
        """risk_category as a RiskTier; soft_label and speak_prominence must agree with it."""
        category = reader.text("risk_category")
        soft_label = reader.text("soft_label")
        prominence = reader.text("speak_prominence")
        if category is None:
            return None
        try:
            tier = RiskTier.from_category(category)
        except ValueError:
            reader.mark_invalid("risk_category")
            return None
        if soft_label is not None and soft_label != tier.soft_label:
            reader.mark_invalid("soft_label")
        if prominence is not None and prominence != tier.speak_prominence:
            reader.mark_invalid("speak_prominence")
        return tier
