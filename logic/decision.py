"""The outcome Logic builds up while its business rules run."""

from __future__ import annotations

import copy

from json_types import JSONObject, JSONValue

# Same private fields Record strips: a rule must never read the reflection.
PRIVATE_FIELDS: tuple[str, ...] = ("feelings_text", "reflection")
TIERS: dict[str, tuple[str, str]] = {
    "Low": ("You're doing ok", "low"),
    "Moderate": ("Worth a check-in", "medium"),
    "High": ("Please reach out", "high"),
}


class Decision:
    """Gemini's tier and tips, adjusted rule by rule.

    It starts as exactly what Gemini returned, with the reflection
    already removed. Rules may raise the tier via raise_tier(), mark
    support priority, lead with a tip, suggest extra tips and add notes.
    They cannot overwrite the tip list directly: LogicManager calls
    finalise_tips() after the rule loop.
    """

    MAX_TIPS: int = 4

    def __init__(self, record: JSONObject,
                 context_flags: dict[str, bool]) -> None:
        self.__record: JSONObject = {
            key: copy.deepcopy(value) for key, value in record.items()
            if key not in PRIVATE_FIELDS}
        self.__context_flags: dict[str, bool] = dict(context_flags)
        self.__risk_category: str = str(record.get("risk_category", ""))
        self.__soft_label: str = str(record.get("soft_label", ""))
        self.__speak_prominence: str = str(
            record.get("speak_prominence", ""))
        self.__gemini_tips: list[str] = self.__strings(record.get("tips"))
        self.__lead_tips: list[str] = []
        self.__extra_tips: list[str] = []
        self.__tips: list[str] = list(self.__gemini_tips)
        self.__notes: list[str] = []
        self.__support_priority: bool = False

    def field(self, name: str) -> JSONValue:
        """A copy of one field of the AI-enriched check-in."""
        return copy.deepcopy(self.__record.get(name))

    @property
    def context_flags(self) -> dict[str, bool]:
        return dict(self.__context_flags)

    @property
    def risk_category(self) -> str:
        return self.__risk_category

    @property
    def soft_label(self) -> str:
        return self.__soft_label

    @property
    def speak_prominence(self) -> str:
        return self.__speak_prominence

    @property
    def support_priority(self) -> bool:
        return self.__support_priority

    @property
    def gemini_tips(self) -> list[str]:
        return list(self.__gemini_tips)

    @property
    def lead_tips(self) -> list[str]:
        return list(self.__lead_tips)

    @property
    def extra_tips(self) -> list[str]:
        return list(self.__extra_tips)

    @property
    def tips(self) -> list[str]:
        """The final tip IDs, in the order the student sees them."""
        return list(self.__tips)

    @property
    def notes(self) -> list[str]:
        return list(self.__notes)

    def raise_tier(self, category: str) -> None:
        """Raise the tier (never lower it); label and prominence follow."""
        if category not in TIERS:
            raise ValueError(f"Unknown risk category: {category!r}")
        order = list(TIERS)
        current = (order.index(self.__risk_category)
                   if self.__risk_category in TIERS else -1)
        if order.index(category) > current:
            self.__risk_category = category
            self.__soft_label, self.__speak_prominence = TIERS[category]

    def mark_support_priority(self) -> None:
        """Flag that high stress with low social support triggered."""
        self.__support_priority = True

    def lead_with(self, tip_id: str) -> None:
        """Show this tip before all others; the first caller keeps first place."""
        if not self.__lead_tips:
            self.__lead_tips = [tip_id]
        elif tip_id not in self.__lead_tips:
            self.suggest(tip_id)

    def suggest(self, tip_id: str) -> None:
        """Add a tip after Gemini's, if there is room."""
        if tip_id not in self.__extra_tips:
            self.__extra_tips.append(tip_id)

    def note(self, text: str) -> None:
        """Record why a rule changed the outcome (for staff, not students)."""
        self.__notes.append(text)

    def finalise_tips(self, max_tips: int = MAX_TIPS) -> None:
        """Lead tip first, then Gemini's tips, then extras while there is room.

        Called by LogicManager after the rule loop. Gemini gives at most
        three tips and at most one tip leads, so Gemini's own tips are
        never pushed out by the cap.
        """
        ordered: list[str] = []
        for tip_id in self.lead_tips + self.gemini_tips:
            if tip_id not in ordered:
                ordered.append(tip_id)
        for tip_id in self.extra_tips:
            if len(ordered) >= max_tips:
                break
            if tip_id not in ordered:
                ordered.append(tip_id)
        self.__tips = ordered[:max_tips]

    def __strings(self, value: JSONValue) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]
