"""DoNotStress — Data Layer (data_manager).

DataManager is the only class that saves, loads and queries check-in
records. It constructs and owns a JSONStorage (composition), so the file
path, the lock, the corrupt-file backup and the atomic write all live on
the storage object. There is no other code that writes the records file.

A finished check-in is saved as a CheckInRecord; one the AI step could
not finish is saved as a PendingRecord, and replace_pending_record()
later upgrades that same row. Reflection text is never stored. Each row
gets a record_id (uuid4 hex) and a UTC saved_at time.

history_for() loads the whole file and filters in memory; only that
student's rows are returned. It does not read only those rows from disk.

No terminal I/O (print / input), no AI calls, no business-tier rules.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType

from base_manager import BaseManager
from json_storage import JSONStorage
from json_types import JSONObject
from records.check_in_record import CheckInRecord
from records.pending_record import PendingRecord
from records.record import Record


class DataManager(BaseManager):
    """Saves and queries records through a JSONStorage it constructs."""

    DEFAULT_PATH: Path = (Path(__file__).resolve().parent / "data"
                          / "student_records.json")
    TIER_TO_CATEGORY: Mapping[str, str] = MappingProxyType({
        "You're doing ok": "Low",
        "Worth a check-in": "Moderate",
        "Please reach out": "High",
    })
    CONSENT_REQUIRED: str = ("Save refused: student opt-in required "
                             "(pass opt_in=True).")

    def __init__(self, path: Path | str | None = None) -> None:
        super().__init__("data_manager")
        resolved = (Path(path) if path is not None and str(path).strip()
                    else self.DEFAULT_PATH)
        self.__storage: JSONStorage = JSONStorage(resolved)

    def describe(self) -> JSONObject:
        """The storage type only; its path stays out of health checks."""
        return {"storage": type(self.__storage).__name__}

    def save(self, record: Record, *, opt_in: bool) -> JSONObject:
        """Append one record. Any kind of Record is saved the same way.

        Returns {"ok": True, "record_id": ..., "row": ...} or
        {"ok": False, "error": "..."}.
        """
        if opt_in is not True:
            return {"ok": False, "error": self.CONSENT_REQUIRED}
        problem = record.problem()
        if problem:
            return {"ok": False, "error": problem}
        row = self.__stamped(record, record.record_id or uuid.uuid4().hex)
        return self.__write(row, lambda: self.__storage.append(row))

    def replace_pending_record(self, record_id: str, record: CheckInRecord,
                               *, opt_in: bool) -> JSONObject:
        """Upgrade a pending row to its finished result, keeping its id.

        When no row has that id yet, the finished record is appended. If
        the stored row for record_id is already evaluated (for instance
        a stale session replay after restart or job TTL expiry), a new
        record_id is assigned and appended instead of overwriting it.
        """
        clean_id = record_id.strip()
        if not clean_id:
            return {"ok": False, "error": "record_id is required"}
        return self.__replace_if_pending(clean_id, record, opt_in=opt_in)

    def save_checkin(self, fields: JSONObject, *, opt_in: bool = True,
                     replace_id: str = "") -> JSONObject:
        """Build and save a finished CheckInRecord (replacing pending if set)."""
        record = CheckInRecord(fields)
        clean_id = replace_id.strip()
        if clean_id:
            return self.replace_pending_record(clean_id, record, opt_in=opt_in)
        return self.save(record, opt_in=opt_in)

    def save_pending(self, fields: JSONObject, *,
                     opt_in: bool = True,
                     replace_id: str = "") -> JSONObject:
        """Build and save a PendingRecord (updating an existing pending row if set)."""
        clean_id = replace_id.strip()
        if clean_id:
            pending = PendingRecord({**fields, "record_id": clean_id})
            return self.__replace_if_pending(clean_id, pending, opt_in=opt_in)
        pending = PendingRecord({**fields, "record_id": uuid.uuid4().hex})
        return self.save(pending, opt_in=opt_in)

    def __replace_if_pending(self, clean_id: str, record: Record, *,
                             opt_in: bool) -> JSONObject:
        """Replace clean_id only if pending on disk; otherwise append a fresh row.

        saved_at keeps the first attempt's time, also when a pending row is
        upgraded to a finished check-in. It records when the student
        answered, which is the date history and trends should show.
        """
        if opt_in is not True:
            return {"ok": False, "error": self.CONSENT_REQUIRED}
        problem = record.problem()
        if problem:
            return {"ok": False, "error": problem}
        row = self.__stamped(record, clean_id)
        try:
            stored = self.__storage.replace(
                clean_id, row, only_if=self.__is_pending,
                preserve=("saved_at",))
        except OSError as error:
            self.logger.warning("Saving a record failed: %s", error)
            return {"ok": False, "error": str(error)}
        if stored is not None:
            return {"ok": True, "record_id": clean_id, "row": stored}
        fresh_row = self.__stamped(record, uuid.uuid4().hex)
        return self.__write(
            fresh_row, lambda: self.__storage.append(fresh_row))

    def load(self) -> list[Record]:
        """Every saved record. [] when nothing has been saved yet.

        Raises OSError when the store is corrupt or unreadable, so a
        broken file is never mistaken for an empty history.
        """
        return [self.__to_record(row) for row in self.__storage.load()]

    def history_for(self, student_id: str,
                    survey_version: str | None = None,
                    visible: Callable[[str], bool] | None = None) -> JSONObject:
        """One student's check-ins, oldest first, as a dict.

        The whole file is loaded and then filtered in memory. Only an
        exact Student ID match (and matching visible predicate, when
        given) is returned. Finished check-ins are listed with their
        scores; pending ones are only counted. When survey_version is
        given, other questionnaire versions are skipped. Raises OSError
        when the store cannot be read.
        """
        wanted = student_id.strip()
        finished: list[Record] = []
        pending = 0
        for record in self.load():
            if not record.belongs_to(wanted):
                continue
            if (survey_version is not None
                    and record.get("survey_version") != survey_version):
                continue
            if visible is not None and not visible(record.record_id):
                continue
            if record.status == "pending":
                pending += 1
                continue
            finished.append(record)
        finished.sort(key=lambda record: record.saved_at)
        return {
            "student_id": wanted,
            "records": [record.to_row() for record in finished],
            "scores": [record.score for record in finished
                       if record.score is not None],
            "pending_count": pending,
            "count": len(finished),
        }

    def filter_records(self, records: list[Record], tier: str = "",
                       cohort_year: str = "",
                       id_contains: str = "") -> list[Record]:
        """Admin filters: tier label, cohort year and part of an ID."""
        category = self.TIER_TO_CATEGORY.get(tier)
        prefix = cohort_year.zfill(2)[-2:] if cohort_year else ""
        kept: list[Record] = []
        for record in records:
            in_tier = (record.get("soft_label") == tier
                       or record.get("risk_category") == category)
            if tier and not in_tier:
                continue
            if prefix and record.student_id[:2] != prefix:
                continue
            if id_contains not in record.student_id:
                continue
            kept.append(record)
        return kept

    def cohorts(self, records: list[Record]) -> list[str]:
        """Two-digit cohort years (first two ID digits), newest first."""
        years = {record.student_id[:2] for record in records}
        return sorted((year for year in years
                       if len(year) == 2 and year.isascii()
                       and year.isdigit()), reverse=True)

    def __stamped(self, record: Record, record_id: str) -> JSONObject:
        row = record.to_row()
        row["record_id"] = record_id
        row["save_opt_in"] = True
        if not row.get("saved_at"):
            row["saved_at"] = datetime.now(timezone.utc).isoformat()
        return row

    def __write(self, row: JSONObject,
                action: Callable[[], None]) -> JSONObject:
        try:
            action()
        except OSError as error:
            self.logger.warning("Saving a record failed: %s", error)
            return {"ok": False, "error": str(error)}
        return {"ok": True, "record_id": str(row.get("record_id") or ""),
                "row": row}

    def __to_record(self, row: JSONObject) -> Record:
        """Rebuild the right kind of Record from a stored row."""
        if self.__is_pending(row):
            return PendingRecord(row)
        return CheckInRecord(row)

    def __is_pending(self, row: JSONObject) -> bool:
        """Marked pending, or never successfully processed by the AI."""
        pending = str(row.get("status") or "").strip().lower() == "pending"
        source = str(row.get("source") or "").strip().lower()
        processed = (row.get("ai_ok") is True
                     or source in CheckInRecord.AI_SUCCESS_SOURCES)
        return pending or not processed
