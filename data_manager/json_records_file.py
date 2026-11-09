"""JsonRecordsFile: safe reading and writing of the JSON records file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .data_store_error import DataStoreError


class JsonRecordsFile:
    """One JSON file holding a list of record objects.

    * A missing or empty file reads as an empty list.
    * A corrupt file (bad JSON, not a list, unreadable bytes) raises
      DataStoreError and is never overwritten, so earlier records survive.
    * Writes go to a temporary file first and then replace the real file
      in one step, so a crash mid-write cannot leave half a file.
    """

    CORRUPT_MESSAGE = "Corrupted records file"

    def __init__(self, path: str | Path) -> None:
        self.__path = Path(path)

    @property
    def path(self) -> Path:
        return self.__path

    def read(self) -> list[dict[str, Any]]:
        """Every record object in the file (non-object entries are skipped)."""
        if not self.__path.exists():
            return []
        try:
            text = self.__path.read_text(encoding="utf-8")
            if not text.strip():
                return []
            data = json.loads(text)
        except (OSError, ValueError) as exc:  # ValueError covers bad JSON and bad UTF-8
            raise DataStoreError(self.CORRUPT_MESSAGE) from exc
        if not isinstance(data, list):
            raise DataStoreError(self.CORRUPT_MESSAGE)
        return [item for item in data if isinstance(item, dict)]

    def write(self, records: list[dict[str, Any]]) -> None:
        """Replace the file's contents with ``records``."""
        temporary = self.__path.with_suffix(self.__path.suffix + ".tmp")
        try:
            self.__path.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, self.__path)
        except (OSError, TypeError, ValueError) as exc:
            self.__remove_quietly(temporary)
            raise DataStoreError(f"write failed: {type(exc).__name__}") from exc

    @staticmethod
    def __remove_quietly(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass  # nothing more can be done; the real file is untouched
