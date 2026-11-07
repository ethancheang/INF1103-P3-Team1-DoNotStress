"""Reads raw check-in answers as numbers Logic can score."""

from __future__ import annotations

import math

from json_types import JSONObject, JSONValue


class AnswerReader:
    """Turns JSON answers into finite numbers and checks their range.

    Sleep hours run from 0 to 14 in any step. Every other answer is on the
    1-5 scale. This class only reads answers; it does not know the scoring
    formula, the tiers or the context flags.
    """

    SCALE_MIN: int = 1
    SCALE_MAX: int = 5
    SLEEP_KEY: str = "sleep_hours_avg"
    SLEEP_HOURS_MIN: int = 0
    SLEEP_HOURS_MAX: int = 14

    def number(self, value: JSONValue) -> float | None:
        """value as a finite float, or None for text, bools, NaN or inf."""
        if isinstance(value, bool) or not isinstance(
                value, (int, float, str)):
            return None
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return None
        return number if math.isfinite(number) else None

    def in_range(self, key: str, value: JSONValue) -> bool:
        """A number Logic can score: sleep hours 0-14, anything else 1-5."""
        number = self.number(value)
        if number is None:
            return False
        if key == self.SLEEP_KEY:
            return self.SLEEP_HOURS_MIN <= number <= self.SLEEP_HOURS_MAX
        return self.SCALE_MIN <= number <= self.SCALE_MAX

    def scorable(self, key: str, value: JSONValue) -> bool:
        """In range and, except for sleep hours, a whole number."""
        number = self.number(value)
        if number is None or not self.in_range(key, value):
            return False
        return key == self.SLEEP_KEY or number.is_integer()

    def read(self, answers: JSONObject, key: str) -> float:
        """The answer as a number. Raises ValueError if it is unusable."""
        number = self.number(answers.get(key))
        if number is None:
            raise ValueError(f"{key} is not a usable answer.")
        return number
