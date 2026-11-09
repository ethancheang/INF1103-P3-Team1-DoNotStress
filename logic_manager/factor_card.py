"""FactorCard: one card on the student result page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FactorCard:
    """One card on the student result page (rest, study, money or support)."""

    title: str
    flagged: bool
    value: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"title": self.title, "flagged": self.flagged, "value": self.value, "text": self.text}
