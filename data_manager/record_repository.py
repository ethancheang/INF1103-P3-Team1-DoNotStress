"""RecordRepository: the contract every record store follows."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from typing import Any


class RecordRepository(ABC):
    """INTERFACE for the Data Manager.

    The web app and the desktop app only depend on this type, so the JSON
    file store and the in-memory test double can replace each other (Liskov
    Substitution), and a database store could be added as a new subclass
    without changing any caller (Open/Closed).

    Shared contract:
      * reflection text (``feelings_text``) is never stored;
      * every stored record gets a ``record_id`` and a ``saved_at`` time;
      * failures raise ``DataStoreError``.
    """

    PRIVATE_FIELDS: tuple[str, ...] = ("feelings_text", "reflection")

    @abstractmethod
    def load(self) -> list[dict[str, Any]]:
        """Every stored record, oldest first. Raises DataStoreError if they cannot be read."""

    @abstractmethod
    def save(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Store one AI-evaluated record and return the stored copy."""

    @abstractmethod
    def save_pending(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Store the answers of a check-in the AI could not finish (status "pending")."""

    @abstractmethod
    def replace_pending(self, record_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
        """Upgrade a pending row to its evaluated record (appends if the id is not found)."""

    def query(self, predicate: Callable[[dict[str, Any]], bool]) -> list[dict[str, Any]]:
        """The stored records for which ``predicate(record)`` is true."""
        return [record for record in self.load() if predicate(record)]

    def _strip_private(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """A copy of ``record`` without any reflection text."""
        cleaned = dict(record)
        for key in self.PRIVATE_FIELDS:
            cleaned.pop(key, None)
        return cleaned
