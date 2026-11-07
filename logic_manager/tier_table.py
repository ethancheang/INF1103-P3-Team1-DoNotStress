"Checked by Qing Kai"
"Date: 7/11/2026"
"Time: 6.10pm"

"""The three stress tiers and how each one is shown to the student."""

from __future__ import annotations

from json_types import JSONValue


class TierTable:
    """Where each tier starts, and its soft label and prominence.

    Low below 2.5, Moderate 2.5 to 3.5 inclusive, High above 3.5. These
    bands are team heuristics, not clinical cut-offs. Every other Logic
    class uses these names instead of writing "High" and so on itself.
    """

    LOW: str = "Low"
    MODERATE: str = "Moderate"
    HIGH: str = "High"
    CHECK_IN_FROM: float = 2.5
    REACH_OUT_ABOVE: float = 3.5
    LABELS: dict[str, str] = {
        LOW: "You're doing ok",
        MODERATE: "Worth a check-in",
        HIGH: "Please reach out",
    }
    PROMINENCE: dict[str, str] = {
        LOW: "low", MODERATE: "medium", HIGH: "high"}

    def is_tier(self, value: JSONValue) -> bool:
        """True for "Low", "Moderate" or "High" and nothing else."""
        return isinstance(value, str) and value in self.LABELS

    def category_for(self, stress_score: float) -> str:
        """The tier for a 1-5 stress score."""
        if stress_score > self.REACH_OUT_ABOVE:
            return self.HIGH
        if stress_score >= self.CHECK_IN_FROM:
            return self.MODERATE
        return self.LOW

    def label_for(self, category: str) -> str:
        """The soft label for a tier. Raises KeyError for an unknown tier."""
        return self.LABELS[category]

    def prominence_for(self, category: str) -> str:
        """How prominent the advisor panel is for a tier."""
        return self.PROMINENCE[category]

    def label_matches(self, category: str, label: JSONValue) -> bool:
        """True when category is a known tier and label is its soft label."""
        expected = self.LABELS.get(category)
        return expected is not None and label == expected
