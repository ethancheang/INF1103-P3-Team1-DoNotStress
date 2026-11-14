"""The check-in: its questions, chapters, answer checks and safety patterns."""

from __future__ import annotations

import math
import re
from json_types import JSONObject


class Questionnaire:
    """A versioned set of questions grouped into chapters.

    Questions and chapters are passed in as data (dictionaries) and can
    be shared. Validation, option labels and the safety check live here
    so this object is more than a wrapper around those dictionaries.
    The same instance is handed to I/O and AI (aggregation).
    Build the evidence survey with from_survey().
    """

    def __init__(self, version: str, questions: list[JSONObject],
                 sections: list[JSONObject],
                 safety_patterns: tuple[str, ...]) -> None:
        self.__version: str = version
        self.__questions: tuple[JSONObject, ...] = tuple(
            self.__frozen_question(item) for item in questions)
        self.__sections: tuple[JSONObject, ...] = tuple(
            self.__frozen_section(item) for item in sections)
        self.__by_key: dict[str, JSONObject] = {
            str(item["key"]): item for item in self.__questions}
        self.__safety_patterns: tuple[str, ...] = tuple(safety_patterns)
        self.__compiled: tuple[re.Pattern[str], ...] = tuple(
            re.compile(pattern) for pattern in safety_patterns)

    @classmethod
    def from_survey(cls) -> "Questionnaire":
        """A new evidence-v3 questionnaire built from the survey module's data.

        Callers own the instance they get. There is no module-level
        questionnaire singleton.
        """
        import survey
        return cls(
            survey.VERSION,
            list(survey.QUESTIONS),
            list(survey.SECTIONS),
            survey.SAFETY_PATTERNS,
        )

    @property
    def version(self) -> str:
        return self.__version

    @property
    def questions(self) -> list[JSONObject]:
        """A copy of each question dict, so callers cannot mutate ours."""
        return [self.__public_question(item) for item in self.__questions]

    @property
    def sections(self) -> list[JSONObject]:
        return [self.__public_section(item) for item in self.__sections]

    def keys(self) -> tuple[str, ...]:
        return tuple(self.__by_key)

    def reversed_keys(self) -> tuple[str, ...]:
        """Positively worded items, scored as 6 - answer."""
        return tuple(str(item["key"]) for item in self.__questions
                     if item.get("reverse") is True)

    def question(self, key: str) -> JSONObject:
        """A copy of the question with this key. Raises KeyError if unknown."""
        return self.__public_question(self.__by_key[key])

    def validate_answer(self, key: str,
                        raw: object) -> tuple[bool, int | float | str]:
        """(True, the answer as a number) or (False, a message to show)."""
        item = self.__by_key.get(key)
        if item is None:
            return False, "Unknown question."
        if raw is None or str(raw).strip() == "":
            return False, "Please answer this question."
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            return False, "Choose one of the available answers."
        try:
            value = float(raw)
        except (ValueError, OverflowError):
            return False, "Choose a number in the available range."
        minimum = int(item["min"])  # type: ignore[arg-type]
        maximum = int(item["max"])  # type: ignore[arg-type]
        step = float(item["step"])  # type: ignore[arg-type]
        in_range = minimum <= value <= maximum
        steps = value / step
        on_step = abs(steps - round(steps)) <= 1e-9
        if not math.isfinite(value) or not in_range or not on_step:
            return False, (f"Choose {minimum} to {maximum} "
                           f"in steps of {step:g}.")
        return True, int(round(value)) if float(step).is_integer() else value

    def option_label(self, key: str, value: int) -> str:
        """The word label for a choice answer, e.g. 3 -> "Sometimes"."""
        item = self.__by_key[key]
        options = item.get("options") or ()
        minimum = int(item["min"])  # type: ignore[arg-type]
        index = int(value) - minimum
        if index < 0 or index >= len(options):
            raise ValueError(f"Value {value} out of option range for {key}.")
        return str(options[index])

    def safety_fired(self, text: object) -> bool:
        """True when the reflection matches any crisis pattern."""
        normalised = str(text or "").lower().replace("’", "'")
        return any(pattern.search(normalised) for pattern in self.__compiled)

    def public_config(self) -> JSONObject:
        """Everything the browser needs to draw the check-in."""
        return {
            "version": self.__version,
            "questions": self.questions,
            "sections": self.sections,
            "safetyPatterns": list(self.__safety_patterns),
        }

    def __frozen_question(self, item: JSONObject) -> JSONObject:
        stored = dict(item)
        options = stored.get("options") or ()
        stored["options"] = tuple(options) if options else ()
        return stored

    def __frozen_section(self, item: JSONObject) -> JSONObject:
        stored = dict(item)
        stored["keys"] = tuple(stored.get("keys") or ())
        return stored

    def __public_question(self, item: JSONObject) -> JSONObject:
        public = dict(item)
        options = public.get("options") or ()
        public["options"] = list(options) if options else None
        return public

    def __public_section(self, item: JSONObject) -> JSONObject:
        public = dict(item)
        public["keys"] = list(public.get("keys") or ())
        return public
