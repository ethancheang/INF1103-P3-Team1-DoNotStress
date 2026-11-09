"""PromptBuilder: the Gemini prompt for one check-in."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any

from .ai_response_schema import AIResponseSchema


class PromptBuilder:
    """Builds the prompt from the 11 answers and the survey version only.

    Privacy rule: the student ID and the reflection text are never placed in
    the prompt. Only the keys in ``AIResponseSchema.RAW_ANSWER_KEYS`` and
    ``survey_version`` are copied from the check-in.
    """

    def __init__(
        self,
        questions: Sequence[Mapping[str, Any]] = (),
        schema: type[AIResponseSchema] = AIResponseSchema,
    ) -> None:
        self.__questions = tuple(questions)
        self.__schema = schema

    def build(self, student: Mapping[str, Any], instructions: str | None = None) -> str:
        """The full prompt text. ``instructions`` are the Logic Manager's scoring rules."""
        schema = self.__schema
        lines = [
            "You are a supportive student-wellbeing assistant for DoNotStress, a local check-in used by students.",
            "Calculate stress_score from the 11 answers with the formula below. You are not given a score, "
            "a tier, or a written reflection. Do not diagnose, and do not invent contacts.",
            "",
        ]
        if instructions:
            lines.append(instructions.strip())
            lines.append("")
        lines.append("Question wording and answer labels:")
        lines.extend(self._format_question(question) for question in self.__questions)
        lines.append("")
        lines.append(
            "Speak to the student with warmth. Return ONLY a single JSON object (no markdown fences, "
            "no commentary) with exactly these keys:"
        )
        lines.append(
            '- "scored_items": object of the 11 converted values. Keys are '
            + ", ".join(schema.RAW_ANSWER_KEYS)
            + f". Each value is an integer from {schema.ITEM_MIN} to {schema.ITEM_MAX}."
        )
        lines.append(
            f'- "stress_score": the mean of those 11 converted values, from {schema.STRESS_SCORE_MIN:g} '
            f"to {schema.STRESS_SCORE_MAX:g}, rounded to 2 decimal places"
        )
        lines.append('- "risk_category": "Low", "Moderate", or "High", matching stress_score')
        lines.append(
            '- "primary_stressors": list of snake_case strings chosen ONLY from: '
            + ", ".join(sorted(schema.PRIMARY_STRESSORS))
        )
        lines.append('- "confidence": number from 0.0 to 1.0')
        lines.append(
            '- "reasoning": 2 or 3 warm, plain sentences written to the student. '
            "No numbers, no jargon, no diagnosis, and no contacts"
        )
        lines.append(
            f'- "soft_label": exactly one of {", ".join(schema.SOFT_LABELS)}, matching risk_category. '
            "Use a straight apostrophe in You're doing ok"
        )
        lines.append(
            f'- "tips": list of {schema.MIN_TIPS} to {schema.MAX_TIPS} tip IDs only, each one of: '
            f'{", ".join(sorted(schema.TIP_IDS))}. Do not invent tip text'
        )
        lines.append(
            '- "speak_prominence": "low", "medium", or "high", matching risk_category. '
            "This is how strongly the UI highlights Talk to someone. SIT Counselling stays available "
            "and is shown more prominently when stress is higher"
        )
        lines.append(
            "Do not add other keys. Never invent phone numbers, emails, or offices. "
            "SIT Counselling contacts are shown by the UI, not by you."
        )
        lines.append("")
        lines.append("Student check-in:")
        lines.append(json.dumps(self.answer_payload(student), ensure_ascii=False))
        return "\n".join(lines)

    def answer_payload(self, student: Mapping[str, Any]) -> dict[str, Any]:
        """Exactly what is sent about the student: the 11 answers and survey_version."""
        payload = {key: student.get(key) for key in self.__schema.RAW_ANSWER_KEYS}
        payload["survey_version"] = student.get("survey_version")
        return payload

    @staticmethod
    def _format_question(question: Mapping[str, Any]) -> str:
        key = question.get("key", "?")
        prompt = question.get("prompt", "")
        options = question.get("options")
        if options:
            labels = ", ".join(f"{index + 1}={label}" for index, label in enumerate(options))
            return f"- {key}: {prompt} ({labels})"
        return f"- {key}: {prompt} ({question.get('low', '')} → {question.get('high', '')})"
