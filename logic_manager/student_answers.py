"""StudentAnswers: the 11 scored answers from one check-in."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, ClassVar

from .field_reader import FieldReader
from .record_validation_error import RecordValidationError


@dataclass(frozen=True)
class StudentAnswers:
    """The 11 scored answers exactly as the student gave them (not converted).

    Ten answers are whole numbers from 1 to 5. ``sleep_hours_avg`` is hours
    from 0 to 14. The student ID and the reflection are not part of this.
    """

    pss_1: int
    pss_2: int
    pss_3: int
    pss_4: int
    sleep_hours_avg: float
    sleep_quality: int
    pas_workload: int
    pas_catchup: int
    fin_stress: int
    mspss_friends: int
    mspss_family: int

    KEYS: ClassVar[tuple[str, ...]] = (
        "pss_1",
        "pss_2",
        "pss_3",
        "pss_4",
        "sleep_hours_avg",
        "sleep_quality",
        "pas_workload",
        "pas_catchup",
        "fin_stress",
        "mspss_friends",
        "mspss_family",
    )
    SLEEP_KEY: ClassVar[str] = "sleep_hours_avg"
    LIKERT_MIN: ClassVar[int] = 1
    LIKERT_MAX: ClassVar[int] = 5
    SLEEP_HOURS_MIN: ClassVar[int] = 0
    SLEEP_HOURS_MAX: ClassVar[int] = 14

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> StudentAnswers:
        """Build from any dict holding the 11 answers. Raises RecordValidationError."""
        if not isinstance(data, Mapping):
            raise RecordValidationError(invalid=("answers",))
        reader = FieldReader(data)
        values = cls._read(reader)
        reader.raise_if_problems()
        return cls(**values)

    @classmethod
    def _read(cls, reader: FieldReader) -> dict[str, Any]:
        """Read the 11 answers through ``reader`` (None where a value is unusable)."""
        values: dict[str, Any] = {}
        for key in cls.KEYS:
            if key == cls.SLEEP_KEY:
                values[key] = reader.number(key, cls.SLEEP_HOURS_MIN, cls.SLEEP_HOURS_MAX)
            else:
                number = reader.number(key, cls.LIKERT_MIN, cls.LIKERT_MAX, whole=True)
                values[key] = None if number is None else int(number)
        return values

    def value(self, key: str) -> int | float:
        """One answer by its key, for example ``answers.value("pss_1")``."""
        if key not in self.KEYS:
            raise KeyError(key)
        return getattr(self, key)

    def to_dict(self) -> dict[str, int | float]:
        """The 11 answers as a plain dict, in survey order."""
        return {key: getattr(self, key) for key in self.KEYS}
