"""InMemoryRecordRepository: test double that keeps records in a list instead of a file."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from data_manager import DataStoreError, RecordRepository


class InMemoryRecordRepository(RecordRepository):
    """TEST DOUBLE for RecordRepository (same contract, no file)."""

    def __init__(self) -> None:
        self.__records: list[dict[str, Any]] = []

    def load(self) -> list[dict[str, Any]]:
        return [dict(record) for record in self.__records]

    def save(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return self.__add(record, {})

    def save_pending(self, record: Mapping[str, Any]) -> dict[str, Any]:
        return self.__add(record, {"status": "pending", "ai_ok": False})

    def replace_pending(self, record_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
        if not record_id:
            raise DataStoreError("record_id is required")
        stored = {**self._strip_private(record), "record_id": record_id, "ai_ok": True}
        stored.pop("status", None)
        stored.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        for index, existing in enumerate(self.__records):
            if existing.get("record_id") == record_id:
                self.__records[index] = stored
                return dict(stored)
        self.__records.append(stored)
        return dict(stored)

    def __add(self, record: Mapping[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
        stored = {**self._strip_private(record), **extra}
        stored.setdefault("record_id", f"mem-{len(self.__records) + 1}")
        stored.setdefault("saved_at", datetime.now(timezone.utc).isoformat())
        self.__records.append(stored)
        return dict(stored)
