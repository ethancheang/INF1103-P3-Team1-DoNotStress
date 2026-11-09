"""AIRecordCheck: refuses to store an "evaluated" record that did not come through the AI."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar


class AIRecordCheck:
    """The Data Manager's last line of defence for the "every record through AI" rule.

    A record may only be saved as evaluated when it was processed by the AI
    and carries the AI fields with sensible values. Logic-only fallbacks are
    refused outright.
    """

    AI_SOURCES: ClassVar[frozenset[str]] = frozenset({"ai_manager", "ai", "gemini", "gemini+logic", "ai_logic"})
    FORBIDDEN_SOURCES: ClassVar[frozenset[str]] = frozenset({"logic_fallback", "fallback", "logic", "logic_only"})
    REQUIRED_FIELDS: ClassVar[tuple[str, ...]] = (
        "risk_score", "risk_category", "primary_stressors",
        "recommended_support", "confidence", "reasoning",
    )
    RISK_CATEGORIES: ClassVar[frozenset[str]] = frozenset({"Low", "Moderate", "High"})

    def problem(self, record: Mapping[str, Any]) -> str | None:
        """Why ``record`` cannot be saved as evaluated, or None when it can."""
        source = str(record.get("source", "")).lower()
        if source in self.FORBIDDEN_SOURCES:
            return "logic-only fallback is not allowed"
        if record.get("ai_ok") is not True and source not in self.AI_SOURCES:
            return "record was not successfully processed by AI"
        for key in self.REQUIRED_FIELDS:
            if key not in record:
                return f"missing AI field: {key}"
        if not self._is_probability(record.get("confidence")):
            return "confidence must be between 0 and 1"
        if not self._is_probability(record.get("risk_score")):
            return "risk_score must be between 0 and 1"
        category = record.get("risk_category")
        if not isinstance(category, str) or category not in self.RISK_CATEGORIES:
            return "risk_category invalid"
        stressors = record.get("primary_stressors")
        if not isinstance(stressors, (list, tuple)) or not all(isinstance(item, str) for item in stressors):
            return "primary_stressors must be a list of strings"
        if not isinstance(record.get("reasoning"), str):
            return "reasoning must be a string"
        if not isinstance(record.get("recommended_support"), str):
            return "recommended_support must be a string"
        return None

    @staticmethod
    def _is_probability(value: Any) -> bool:
        try:
            number = float(value)
        except (TypeError, ValueError, OverflowError):
            return False
        return 0.0 <= number <= 1.0
