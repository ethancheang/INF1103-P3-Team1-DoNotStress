"""Check-in rows kept in one JSON file, with a lock around every access."""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import threading
from collections.abc import Callable
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

    def load(self) -> list[JSONObject]:
        """Every stored row. Raises OSError when the file cannot be used."""
        with self.__lock:
            rows, problem = self.__read(backup_corrupt=False)
        if problem:
            raise OSError(problem)
        return rows

    def append(self, row: JSONObject) -> None:
        """Add one row. A corrupt file is backed up once before starting fresh."""
        with self.__lock:
            rows, _ = self.__read(backup_corrupt=True)
            rows.append(row)
            self.__write(rows)

    def replace(self, record_id: str, row: JSONObject, *,
                only_if: Callable[[JSONObject], bool] | None = None,
                preserve: tuple[str, ...] = ()) -> JSONObject | None:
        """Replace the row with this record_id, or append when none has it.

        Returns a copy of the row as stored. When only_if is supplied and
        the matching row fails it, the file is left untouched and None is
        returned so the caller can append a fresh record instead. Fields
        named in preserve keep their non-empty stored values. The row
        passed in is never modified.
        """
        with self.__lock:
            rows, _ = self.__read(backup_corrupt=True)
            stored = dict(row)
            for index, existing in enumerate(rows):
                if str(existing.get("record_id") or "").strip() == record_id:
                    if only_if is not None and not only_if(existing):
                        return None
                    for field in preserve:
                        if existing.get(field):
                            stored[field] = existing[field]
                    rows[index] = stored
                    break
            else:
                rows.append(stored)
            self.__write(rows)
            return dict(stored)

    def __read(self, *, backup_corrupt: bool) -> tuple[list[JSONObject], str | None]:
        """The rows, plus a note when the file is corrupt.

        When backup_corrupt is True, a corrupt file is copied to
        records.corrupt-<time>.json before any write can overwrite it.
        Raises OSError when the file cannot be read or the backup fails.
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
            problem = f"Corrupted JSON in data file: {error}"
            return [], self.__back_up(problem) if backup_corrupt else problem
        if payload is None:
            return [], None
        if isinstance(payload, dict):
            # {} or {"other": 1} has no records list: treat it as corrupt
            # so a write backs it up rather than silently dropping it.
            payload = payload.get("records")
        if not isinstance(payload, list):
            problem = "Corrupted data file: expected a list of records."
            return [], self.__back_up(problem) if backup_corrupt else problem
        if any(not isinstance(row, dict) for row in payload):
            problem = "Corrupted data file: every record must be an object."
            return [], self.__back_up(problem) if backup_corrupt else problem
        return list(payload), None

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
