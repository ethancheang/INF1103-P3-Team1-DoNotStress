"""The shared shape of every saved check-in row."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod

from json_types import JSONObject, JSONValue


class Record(ABC):
    """One check-in row as it is stored. Reflection text never gets in.

    Subclasses say what status the row has, whether it carries a verified
    score, and whether it may be saved. DataManager relies only on this
    contract, never on which subclass it holds.
    """

    PRIVATE_FIELDS: tuple[str, ...] = ("feelings_text", "reflection")

    def __init__(self, data: JSONObject) -> None:
        self.__data: JSONObject = {
            key: copy.deepcopy(value) for key, value in data.items()
            if key not in self.PRIVATE_FIELDS}

    @property
    def record_id(self) -> str:
        return str(self.__data.get("record_id") or "").strip()

    @property
    def student_id(self) -> str:
        return str(self.__data.get("student_id") or "").strip()

    @property
    def saved_at(self) -> str:
        """ISO 8601 time of saving in UTC, or "" before it is saved."""
        return str(self.__data.get("saved_at") or "")

    @property
    def survey_version(self) -> str:
        return str(self.__data.get("survey_version") or "")

    @property
    @abstractmethod
    def status(self) -> str:
        """"evaluated" or "pending"."""

    @property
    @abstractmethod
    def score(self) -> float | None:
        """The verified stress score, or None while no score exists."""

    def problem(self) -> str | None:
        """Checks every record must pass; subclasses call super() first."""
        if not self.student_id:
            return "Save refused: student_id is missing."
        if not self.survey_version:
            return "Save refused: survey_version is missing."
        return None

    def get(self, key: str) -> JSONValue:
        value = self.__data.get(key)
        if isinstance(value, (dict, list)):
            return copy.deepcopy(value)
        return value

    def belongs_to(self, student_id: str) -> bool:
        """True only for an exact Student ID match."""
        wanted = student_id.strip()
        return bool(wanted) and self.student_id == wanted

    def to_row(self) -> JSONObject:
        """The row to store, with this record type's status fields set."""
        row = copy.deepcopy(self.__data)
        self._mark(row)
        return row

    @abstractmethod
    def _mark(self, row: JSONObject) -> None:
        """Set the status fields that belong to this kind of record."""
