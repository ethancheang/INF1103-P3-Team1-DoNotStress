"""ResponseValidator: schema validation for one parsed Gemini reply."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .ai_response_schema import AIResponseSchema


class ResponseValidator:
    """Checks every field of a parsed reply before any of it is used.

    ``validate`` returns ``(True, cleaned_fields)`` or ``(False, message)``.
    It never raises, whatever the reply contains, so a strange reply is
    simply retried as an invalid response.
    """

    def __init__(self, schema: type[AIResponseSchema] = AIResponseSchema) -> None:
        self.__schema = schema

    def validate(self, payload: Any) -> tuple[bool, Any]:
        """Schema validation. Returns (ok, cleaned_fields_or_error_message)."""
        if not isinstance(payload, Mapping):
            return False, "response is not a JSON object"
        missing = [key for key in self.__schema.REQUIRED_FIELDS if key not in payload]
        if missing:
            return False, f"missing fields: {', '.join(missing)}"

        checks = (
            ("scored_items", self._scored_items),
            ("stress_score", self._stress_score),
            ("risk_category", self._risk_category),
            ("primary_stressors", self._stressors),
            ("confidence", self._confidence),
            ("reasoning", self._reasoning),
            ("soft_label", self._soft_label),
            ("tips", self._tips),
            ("speak_prominence", self._speak_prominence),
        )
        cleaned: dict[str, Any] = {}
        for field, check in checks:
            ok, value = check(payload.get(field))
            if not ok:
                return False, f"{field} invalid"
            cleaned[field] = value
        return True, cleaned

    # -- one check per field: (ok, cleaned value) -------------------------

    def _scored_items(self, value: Any) -> tuple[bool, Any]:
        if not isinstance(value, Mapping):
            return False, None
        items: dict[str, int] = {}
        for key in self.__schema.RAW_ANSWER_KEYS:
            if key not in value:
                return False, None
            try:
                number = int(value[key])
            except (TypeError, ValueError, OverflowError):
                return False, None
            if not self.__schema.ITEM_MIN <= number <= self.__schema.ITEM_MAX:
                return False, None
            items[key] = number
        return True, items

    def _stress_score(self, value: Any) -> tuple[bool, Any]:
        number = self._as_float(value)
        if number is None or not self.__schema.STRESS_SCORE_MIN <= number <= self.__schema.STRESS_SCORE_MAX:
            return False, None
        return True, round(number, 2)

    def _risk_category(self, value: Any) -> tuple[bool, Any]:
        ok = isinstance(value, str) and value in self.__schema.RISK_CATEGORIES
        return ok, value if ok else None

    def _stressors(self, value: Any) -> tuple[bool, Any]:
        cleaned = self._clean_list(value)
        if cleaned is None or any(item not in self.__schema.PRIMARY_STRESSORS for item in cleaned):
            return False, None
        return True, cleaned

    def _confidence(self, value: Any) -> tuple[bool, Any]:
        number = self._as_float(value)
        if number is None or not 0.0 <= number <= 1.0:
            return False, None
        return True, number

    def _reasoning(self, value: Any) -> tuple[bool, Any]:
        if not isinstance(value, str) or not value.strip():
            return False, None
        return True, value.strip()

    def _soft_label(self, value: Any) -> tuple[bool, Any]:
        if not isinstance(value, str) or value.strip() not in self.__schema.SOFT_LABELS:
            return False, None
        return True, value.strip()

    def _tips(self, value: Any) -> tuple[bool, Any]:
        cleaned = self._clean_list(value)
        if cleaned is None or not self.__schema.MIN_TIPS <= len(cleaned) <= self.__schema.MAX_TIPS:
            return False, None
        if any(item not in self.__schema.TIP_IDS for item in cleaned):
            return False, None
        return True, cleaned

    def _speak_prominence(self, value: Any) -> tuple[bool, Any]:
        ok = isinstance(value, str) and value in self.__schema.SPEAK_PROMINENCE
        return ok, value if ok else None

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _as_float(value: Any) -> float | None:
        try:
            return float(value)
        except (TypeError, ValueError, OverflowError):
            return None

    @staticmethod
    def _clean_list(value: Any) -> list[str] | None:
        """A list or tuple as stripped, non-empty strings; None for anything else."""
        if not isinstance(value, (list, tuple)):
            return None
        return [str(item).strip() for item in value if str(item).strip()]
