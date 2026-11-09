"""StudentFormValidator: checks one submitted check-in form."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any, ClassVar

from survey import Questionnaire, SafetyCheck


class StudentFormValidator:
    """Validates the student ID, the reflection and the 11 answers.

    ``validate`` collects every problem at once, so the page can mark all
    invalid fields together. A valid form becomes a clean record holding the
    answers, ``survey_version`` and the True/False ``safety_flag``. The
    reflection text is kept only so the AI Manager can strip it; it is never
    sent to the AI or stored.
    """

    STUDENT_ID_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"2[0-9]{6}")
    STUDENT_ID_MESSAGE: ClassVar[str] = "Enter a 7-digit student ID starting with 2."
    REFLECTION_MAX_LENGTH: ClassVar[int] = 2000
    REFLECTION_MESSAGE: ClassVar[str] = "Reflection must be 2,000 characters or fewer."
    FORM_MESSAGE: ClassVar[str] = "Please submit a check-in form."

    def __init__(self, safety_check: SafetyCheck | None = None) -> None:
        self.__safety_check = safety_check if safety_check is not None else SafetyCheck()

    def validate(self, values: Any) -> tuple[bool, dict[str, Any]]:
        """``(True, clean_record)`` or ``(False, {field: message})``."""
        if not isinstance(values, Mapping):
            return False, {"form": self.FORM_MESSAGE}
        errors: dict[str, str] = {}
        clean: dict[str, Any] = {}

        ok, student_id = self.validate_student_id(values.get("student_id"))
        if ok:
            clean["student_id"] = student_id
        else:
            errors["student_id"] = student_id

        ok, reflection = self.validate_reflection(values.get("feelings_text", ""))
        if ok:
            clean["feelings_text"] = reflection
        else:
            errors["feelings_text"] = reflection

        for key, question in Questionnaire.QUESTION_MAP.items():
            valid, value_or_message = Questionnaire.validate_answer(values.get(key), question)
            if valid:
                clean[key] = value_or_message
            else:
                errors[key] = value_or_message or "Please answer this question."

        if errors:
            return False, errors
        clean["survey_version"] = Questionnaire.VERSION
        clean["safety_flag"] = self.__safety_check.is_flagged(clean.get("feelings_text", ""))
        return True, clean

    def validate_student_id(self, raw: Any) -> tuple[bool, str]:
        """Seven ASCII digits starting with 2. ``(ok, id_or_message)``."""
        text = self._as_text(raw)
        if not self.STUDENT_ID_PATTERN.fullmatch(text):
            return False, self.STUDENT_ID_MESSAGE
        return True, text

    def validate_reflection(self, raw: Any) -> tuple[bool, str]:
        """Optional text up to 2,000 characters. ``(ok, text_or_message)``."""
        text = self._as_text(raw)
        if len(text) > self.REFLECTION_MAX_LENGTH:
            return False, self.REFLECTION_MESSAGE
        return True, text

    @staticmethod
    def _as_text(value: Any) -> str:
        return "" if value is None else str(value).strip()
