"""SubmissionFingerprint: identity of one set of survey answers.

The same answers are one submission. A changed answer is a new one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import survey


class SubmissionFingerprint:
    """sha256 of student_id, the 11 answers, and survey_version."""

    def of(self, record: Mapping[str, Any]) -> str:
        answers = [record.get(question["key"]) for question in survey.QUESTIONS]
        payload = json.dumps(
            [record.get("student_id"), answers, record.get("survey_version")],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
