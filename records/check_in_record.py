"""A finished check-in with a verified score, tier and tips."""

from __future__ import annotations

import math

from json_types import JSONObject, JSONValue
from records.record import Record


class CheckInRecord(Record):
    """A finished check-in with a verified score, tier and tips.

    It may only be saved when it really passed AI processing and carries
    every AI field the admin table and history rely on.
    """

    AI_SUCCESS_SOURCES: frozenset[str] = frozenset(
        {"gemini", "ai", "ai_manager", "gemini+logic", "ai_logic"})
    BLOCKED_SOURCES: frozenset[str] = frozenset(
        {"logic_fallback", "fallback", "logic_only", "logic"})
    REQUIRED_AI_FIELDS: tuple[str, ...] = (
        "stress_score", "risk_score", "risk_category", "primary_stressors",
        "recommended_support", "confidence", "reasoning",
    )
    CATEGORIES: tuple[str, ...] = ("Low", "Moderate", "High")

    @property
    def status(self) -> str:
        return "evaluated"

    @property
    def score(self) -> float | None:
        value = self.get("stress_score")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    @property
    def risk_category(self) -> str:
        return str(self.get("risk_category") or "")

    @property
    def soft_label(self) -> str:
        return str(self.get("soft_label") or "")

    def problem(self) -> str | None:
        return super().problem() or self.__ai_problem()

    def _mark(self, row: JSONObject) -> None:
        row.pop("status", None)

    def __ai_problem(self) -> str | None:
        source = str(self.get("source") or "").strip().lower()
        if source in self.BLOCKED_SOURCES:
            return ("Save refused: record is not AI-processed "
                    f"(source={self.get('source')!r}).")
        if (self.get("ai_ok") is not True
                and source not in self.AI_SUCCESS_SOURCES):
            return ("Save refused: successful Gemini processing required "
                    "(set source to 'gemini' or ai_ok=True).")
        missing = [field for field in self.REQUIRED_AI_FIELDS
                   if self.get(field) is None]
        if missing:
            return f"Save refused: AI fields missing: {', '.join(missing)}."
        return self.__field_problem()

    def __field_problem(self) -> str | None:
        if not self.__in_range(self.get("stress_score"), 1.0, 5.0):
            return ("Save refused: stress_score must be a number between "
                    "1.0 and 5.0.")
        for field in ("risk_score", "confidence"):
            if not self.__in_range(self.get(field), 0.0, 1.0):
                return (f"Save refused: {field} must be a float between "
                        "0.0 and 1.0.")
        if self.risk_category not in self.CATEGORIES:
            return ("Save refused: risk_category must be 'Low', "
                    "'Moderate', or 'High'.")
        stressors = self.get("primary_stressors")
        if not isinstance(stressors, list) or not all(
                isinstance(item, str) for item in stressors):
            return "Save refused: primary_stressors must be a list of strings."
        for field in ("recommended_support", "reasoning"):
            if not isinstance(self.get(field), str):
                return f"Save refused: {field} must be a string."
        return None

    def __in_range(self, value: JSONValue, low: float, high: float) -> bool:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return False
        number = float(value)
        return math.isfinite(number) and low <= number <= high
