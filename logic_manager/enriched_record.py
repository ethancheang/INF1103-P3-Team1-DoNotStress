"""EnrichedRecord: the input contract for the Logic Manager."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .ai_assessment import AIAssessment
from .field_reader import FieldReader
from .record_validation_error import RecordValidationError
from .student_answers import StudentAnswers


@dataclass(frozen=True)
class EnrichedRecord:
    """INPUT CONTRACT: one check-in after ai_manager and before Logic.

    ai_manager hands Logic a plain dict shaped like this (see
    tests/sample_ai_records.py for complete examples)::

        {
          "student_id": "2605581",           # str, optional; stored, never used by rules
          "survey_version": "evidence-v3",   # str, optional
          "safety_flag": False,              # bool from the reflection check (the text is never sent)
          "pss_1": 3, ..., "mspss_family": 4,  # the 11 answers: 10 whole numbers 1-5,
                                             #   sleep_hours_avg 0-14 hours
          "scored_items": {...},             # Gemini's 11 converted values (optional, kept for audit)
          "stress_score": 3.18,              # Gemini, 1.0-5.0
          "risk_category": "Moderate",       # Gemini: "Low" | "Moderate" | "High"
          "soft_label": "Worth a check-in",  # must match risk_category
          "speak_prominence": "medium",      # must match risk_category
          "primary_stressors": ["sleep_deprivation"],
          "tips": ["sleep_routine"],         # tip IDs; io_manager owns the wording
          "reasoning": "...",                # warm sentences written to the student
          "confidence": 0.8,                 # 0.0-1.0
          "source": "gemini"                 # ignored by Logic
        }

    Any other key, such as a reflection, is ignored and never stored.
    """

    answers: StudentAnswers
    assessment: AIAssessment
    student_id: str | None = None
    survey_version: str | None = None
    safety_flag: bool = False

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EnrichedRecord:
        """Check and convert ai_manager's dict.

        Raises RecordValidationError listing every missing or unusable field
        at once, so one failed check-in shows all of its problems.
        """
        if not isinstance(data, Mapping):
            raise RecordValidationError(invalid=("record",))
        reader = FieldReader(data)
        answer_values = StudentAnswers._read(reader)
        ai_values = AIAssessment._read(reader)
        reader.raise_if_problems()
        student_id = data.get("student_id")
        survey_version = data.get("survey_version")
        return cls(
            answers=StudentAnswers(**answer_values),
            assessment=AIAssessment(**ai_values),
            student_id=None if student_id is None else str(student_id),
            survey_version=None if survey_version is None else str(survey_version),
            safety_flag=data.get("safety_flag") is True,
        )
