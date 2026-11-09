"""JsonRecordRepository: the Data Manager's JSON-file implementation of RecordRepository."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, ClassVar

from .ai_record_check import AIRecordCheck
from .data_store_error import DataStoreError
from .json_records_file import JsonRecordsFile
from .record_repository import RecordRepository


class JsonRecordRepository(RecordRepository):
    """Saves and loads check-in records in ``data/student_records.json``.

    Records persist across separate runs of the app: a new repository on the
    same path loads everything saved before. Every write re-reads the file
    first, so a corrupt file is reported (DataStoreError) instead of being
    overwritten.

    Relationships: the JsonRecordsFile and AIRecordCheck are created here and
    owned by this repository (composition).
    """

    DEFAULT_PATH: ClassVar[Path] = Path("data") / "student_records.json"
    PENDING_STATUS: ClassVar[str] = "pending"

    def __init__(self, path: str | Path | None = None) -> None:
        self.__file = JsonRecordsFile(Path(path) if path else self.DEFAULT_PATH)
        self.__ai_check = AIRecordCheck()

    @property
    def path(self) -> Path:
        return self.__file.path

    def load(self) -> list[dict[str, Any]]:
        return self.__file.read()

    def save(self, record: Mapping[str, Any]) -> dict[str, Any]:
        self.__require_ai_record(record)
        stored = self.__prepare(record)
        stored["save_opt_in"] = True
        self.__append(stored)
        return stored

    def save_pending(self, record: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(record, Mapping):
            raise DataStoreError("record must be a dict")
        stored = self.__prepare(record)
        stored["status"] = self.PENDING_STATUS
        stored["ai_ok"] = False
        stored["save_opt_in"] = True
        self.__append(stored)
        return stored

    def replace_pending(self, record_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(record_id, str) or not record_id.strip():
            raise DataStoreError("record_id is required")
        self.__require_ai_record(record)
        records = self.__file.read()
        stored = self._strip_private(record)
        stored["record_id"] = record_id.strip()
        stored.setdefault("saved_at", self.__now())
        stored.pop("status", None)
        stored["ai_ok"] = True
        stored["save_opt_in"] = True
        for index, existing in enumerate(records):
            if existing.get("record_id") == stored["record_id"]:
                records[index] = stored
                break
        else:
            records.append(stored)
        self.__file.write(records)
        return stored

    # -- private helpers ----------------------------------------------------

    def __require_ai_record(self, record: Any) -> None:
        if not isinstance(record, Mapping):
            raise DataStoreError("record must be a dict")
        problem = self.__ai_check.problem(record)
        if problem:
            raise DataStoreError(problem)

    def __prepare(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """Private copy with a record_id and saved_at, and no reflection text."""
        stored = self._strip_private(record)
        record_id = stored.get("record_id")
        stored["record_id"] = record_id.strip() if isinstance(record_id, str) and record_id.strip() else uuid.uuid4().hex
        stored.setdefault("saved_at", self.__now())
        return stored

    def __append(self, stored: dict[str, Any]) -> None:
        records = self.__file.read()  # raises on a corrupt file, so it is never overwritten
        records.append(stored)
        self.__file.write(records)

    @staticmethod
    def __now() -> str:
        return datetime.now(timezone.utc).isoformat()
