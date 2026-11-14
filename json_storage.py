"""Check-in rows kept in one JSON file, with a lock around every access."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from json_types import JSONObject


class JSONStorage:
    """A JSON list of rows in one file.

    A missing or empty file means no rows. A corrupt file, including a
    JSON object with no records list ({} or {"other": 1}), is copied to
    records.corrupt-<time>.json before anything can overwrite it. Writes
    go to a temp file in the same folder and then os.replace, so a crash
    never leaves a half-written file. One lock covers each read-modify-
    write, because background check-ins save from worker threads.

    load() on a corrupt file raises OSError and never pretends the file
    is empty. append() and replace() back the corrupt file up and start
    a fresh list; if the backup itself fails, they raise OSError and the
    original file is left untouched.
    """

    def __init__(self, path: Path | str) -> None:
        self.__path: Path = Path(path)
        self.__lock: threading.RLock = threading.RLock()
        self.__logger: logging.Logger = logging.getLogger(
            "data_manager.storage")

    @property
    def location(self) -> str:
        return str(self.__path)

    def load(self) -> list[JSONObject]:
        """Every stored row. Raises OSError when the file cannot be used."""
        with self.__lock:
            rows, problem = self.__read()
        if problem:
            raise OSError(problem)
        return rows

    def append(self, row: JSONObject) -> None:
        """Add one row. Raises OSError when it cannot be written."""
        with self.__lock:
            rows, _ = self.__read()
            rows.append(row)
            self.__write(rows)

    def replace(self, record_id: str, row: JSONObject) -> None:
        """Replace the row with this record_id, or append when none has it."""
        with self.__lock:
            rows, _ = self.__read()
            for index, existing in enumerate(rows):
                if str(existing.get("record_id") or "").strip() == record_id:
                    rows[index] = row
                    break
            else:
                rows.append(row)
            self.__write(rows)

    def __read(self) -> tuple[list[JSONObject], str | None]:
        """The rows, plus a note when a corrupt file had to be set aside.

        Raises OSError when the file cannot be read, or is corrupt
        and cannot be backed up, so nothing ever overwrites it.
        """
        if not self.__path.exists():
            return [], None
        try:
            text = self.__path.read_text(encoding="utf-8")
        except OSError as error:
            raise OSError(f"Could not read data file: {error}") from error
        if not text.strip():
            return [], None
        try:
            payload = json.loads(text)
        except json.JSONDecodeError as error:
            return [], self.__back_up(f"Corrupted JSON in data file: {error}")
        if payload is None:
            return [], None
        if isinstance(payload, dict):
            # {} or {"other": 1} has no records list: back it up like any
            # other corrupt file, so the next save cannot silently drop it.
            payload = payload.get("records")
        if not isinstance(payload, list):
            return [], self.__back_up(
                "Corrupted data file: expected a list of records.")
        return [row for row in payload if isinstance(row, dict)], None

    def __back_up(self, problem: str) -> str:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = self.__path.with_name(
            f"{self.__path.stem}.corrupt-{stamp}.json")
        try:
            shutil.copy2(self.__path, backup)
        except OSError as error:
            self.__logger.warning("Corrupt data file %s could not be backed "
                                  "up: %s", self.__path, error)
            raise OSError(f"{problem} Backup failed.") from error
        self.__logger.warning("Corrupt data file %s backed up to %s",
                              self.__path, backup)
        return problem

    def __write(self, rows: list[JSONObject]) -> None:
        text = json.dumps(rows, indent=2, ensure_ascii=False) + "\n"
        temporary: Path | None = None
        try:
            self.__path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                    "w", encoding="utf-8", dir=self.__path.parent,
                    prefix=f".{self.__path.name}.", suffix=".tmp",
                    delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.__path)
            temporary = None
        except OSError as error:
            raise OSError(f"Could not write data file: {error}") from error
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
