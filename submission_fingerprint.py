"""SubmissionFingerprint: the identity of one set of survey answers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from survey import Questionnaire


class SubmissionFingerprint:
    """sha256 of the student ID, the 11 answers and the survey version.

    The same answers are one submission (a refresh or double-click does not
    add a second row). A changed answer is a new submission.
    """

    def of(self, record: Mapping[str, Any]) -> str:
        answers = [record.get(question["key"]) for question in Questionnaire.QUESTIONS]
        payload = json.dumps(
            [record.get("student_id"), answers, record.get("survey_version")],
            separators=(",", ":"),
            ensure_ascii=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()
