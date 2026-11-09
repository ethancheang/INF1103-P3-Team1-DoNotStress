"""RecordStatus: whether a stored check-in was evaluated or is still pending."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, ClassVar


class RecordStatus:
    """One rule, used by the admin table and the cohort summary alike.

    A record is "Evaluated" when the AI processed it and it is not marked
    pending; otherwise it is "Pending" (the student's answers were saved but
    Gemini could not finish).
    """

    EVALUATED: ClassVar[str] = "Evaluated"
    PENDING: ClassVar[str] = "Pending"
    AI_SOURCES: ClassVar[frozenset[str]] = frozenset({"gemini", "ai", "ai_manager", "gemini+logic", "ai_logic"})

    @classmethod
    def of(cls, record: Mapping[str, Any]) -> str:
        source = str(record.get("source", "")).lower()
        processed = record.get("ai_ok") is True or source in cls.AI_SOURCES
        pending = str(record.get("status", "")).strip().lower() == "pending"
        return cls.PENDING if pending or not processed else cls.EVALUATED

    @classmethod
    def is_evaluated(cls, record: Mapping[str, Any]) -> bool:
        return cls.of(record) == cls.EVALUATED
