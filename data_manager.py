"""
DoNotStress — Data Layer (data_manager)

Sole owner of flat-file persistence for evaluated student check-in records.

Pure procedural Python: functions only — no classes.
No terminal I/O (print / input), no AI calls, no business-tier rules.

The AI result must contain:
    risk_score
    risk_category
    primary_stressors
    recommended_support
    confidence
    reasoning

save_record stores a successful AI-processed result when the caller
asks it to (opt_in=True). save_pending_record stores the same check-in
when AI could not finish, with status "pending". Reflection text is
removed before either write.

Every stored row has a record_id (uuid4 hex). replace_pending_record
upgrades that pending row in place when a later attempt succeeds.
Writes go to a temp file, then os.replace, so a crash cannot leave
a half-written JSON file.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
_PACKAGE_ROOT = Path(__file__).resolve().parent
_DEFAULT_DATA_PATH = _PACKAGE_ROOT / "data" / "student_records.json"


def get_default_data_path() -> str:
    """Return the absolute path to the default JSON store."""
    return str(_DEFAULT_DATA_PATH)


def _resolve_path(data_path: str | None) -> Path:
    """Resolve the supplied data path or use the default path."""
    if data_path is None or str(data_path).strip() == "":
        return Path(get_default_data_path())
    return Path(data_path)


_BLOCKED_SOURCES = frozenset(
    {
        "logic_fallback",
        "fallback",
        "logic_only",
        "logic",
    }
)


_AI_SUCCESS_SOURCES = frozenset(
    {
        "gemini",
        "ai",
        "ai_manager",
        "gemini+logic",
        "ai_logic",
    }
)


TIER_TO_CATEGORY = {
    "You're doing ok": "Low",
    "Worth a check-in": "Moderate",
    "Please reach out": "High",
}


_REQUIRED_AI_FIELDS = (
    "risk_score",
    "risk_category",
    "primary_stressors",
    "recommended_support",
    "confidence",
    "reasoning",
)


def _is_opted_in(opt_in: Any) -> bool:
    """Return True only for explicit consent."""
    if opt_in is True:
        return True

    if isinstance(opt_in, str):
        return opt_in.strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

    return False


def _is_valid_probability(value: Any) -> bool:
    """Return True when value is numeric and between 0.0 and 1.0."""
    if isinstance(value, bool):
        return False

    try:
        number = float(value)
    except (TypeError, ValueError):
        return False

    return 0.0 <= number <= 1.0


def _validate_ai_fields(record: dict[str, Any]) -> str | None:
    """Validate the required Gemini JSON fields."""

    missing = [
        field
        for field in _REQUIRED_AI_FIELDS
        if field not in record
    ]

    if missing:
        return (
            "Save refused: AI fields missing: "
            + ", ".join(missing)
            + "."
        )

    if not _is_valid_probability(record["risk_score"]):
        return (
            "Save refused: risk_score must be a float "
            "between 0.0 and 1.0."
        )

    if not _is_valid_probability(record["confidence"]):
        return (
            "Save refused: confidence must be a float "
            "between 0.0 and 1.0."
        )

    risk_category = record["risk_category"]

    if not isinstance(risk_category, str):
        return "Save refused: risk_category must be a string."

    if risk_category not in {"Low", "Moderate", "High"}:
        return (
            "Save refused: risk_category must be "
            "'Low', 'Moderate', or 'High'."
        )

    primary_stressors = record["primary_stressors"]

    if not isinstance(primary_stressors, list):
        return (
            "Save refused: primary_stressors must be "
            "a list of strings."
        )

    if not all(isinstance(item, str) for item in primary_stressors):
        return (
            "Save refused: every primary_stressors item "
            "must be a string."
        )

    if not isinstance(record["recommended_support"], str):
        return (
            "Save refused: recommended_support must be a string."
        )

    if not isinstance(record["reasoning"], str):
        return "Save refused: reasoning must be a string."

    return None


def _ai_success_error(record: dict[str, Any]) -> str | None:
    """Validate that the record is a successful AI result."""

    if not isinstance(record, dict):
        return "record must be a dict"

    source = str(record.get("source", "")).strip().lower()

    if source in _BLOCKED_SOURCES:
        return (
            "Save refused: record is not AI-processed "
            f"(source={record.get('source')!r})."
        )

    explicit_ok = record.get("ai_ok") is True
    source_ok = source in _AI_SUCCESS_SOURCES

    if not explicit_ok and not source_ok:
        return (
            "Save refused: successful Gemini processing required "
            "(set source to 'gemini' or ai_ok=True)."
        )

    return _validate_ai_fields(record)


def _ensure_parent_dir(path: Path) -> None:
    """Create the parent directory if necessary."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _ensure_record_id(stored: dict[str, Any]) -> str:
    """Return the row's record_id, assigning a uuid4 hex when it has none."""
    record_id = stored.get("record_id")
    if isinstance(record_id, str):
        record_id = record_id.strip()
        if record_id:
            stored["record_id"] = record_id
            return record_id
    record_id = uuid.uuid4().hex
    stored["record_id"] = record_id
    return record_id


def _read_records_file(
    path: Path,
) -> tuple[bool, list[dict[str, Any]], str | None]:
    """
    Load records from JSON.

    Missing / empty / corrupt files are handled gracefully.
    """

    if not path.exists():
        return True, [], None

    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return True, [], f"Could not read data file: {exc}"

    if raw.strip() == "":
        return True, [], None

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        backup = path.with_name(f"{path.stem}.corrupt-{stamp}.json")
        try:
            shutil.copy2(path, backup)
        except OSError as copy_exc:
            logger.warning("Corrupt data file %s could not be backed up: %s", path, copy_exc)
            return False, [], f"Corrupted JSON in data file and backup failed: {exc}"
        logger.warning("Corrupt data file %s backed up to %s", path, backup)
        return True, [], f"Corrupted JSON in data file: {exc}"

    if payload is None:
        return True, [], None

    if isinstance(payload, list):
        records = [
            record
            for record in payload
            if isinstance(record, dict)
        ]
        return True, records, None

    if (
        isinstance(payload, dict)
        and isinstance(payload.get("records"), list)
    ):
        records = [
            record
            for record in payload["records"]
            if isinstance(record, dict)
        ]
        return True, records, None

    return (
        True,
        [],
        "Data file JSON must be a list of records "
        "or an object with a 'records' list.",
    )


def _write_records_file(
    path: Path,
    records: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    """Write all records atomically: temp file in the same directory, then os.replace."""

    temporary: Path | None = None

    try:
        _ensure_parent_dir(path)

        text = (
            json.dumps(
                records,
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )

        handle = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=str(path.parent),
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary = Path(handle.name)

        try:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        finally:
            handle.close()

        os.replace(temporary, path)
        temporary = None
        return True, None

    except OSError as exc:
        return False, f"Could not write data file: {exc}"

    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def load_all_records(
    data_path: str | None = None,
) -> dict[str, Any]:
    """
    Load all historical records.

    Returns:
        {
            "ok": bool,
            "records": list,
            "error": str | None,
            "path": str
        }
    """

    path = _resolve_path(data_path)
    ok, records, error = _read_records_file(path)

    return {
        "ok": ok,
        "records": records,
        "error": error,
        "path": str(path),
    }


def save_record(
    record: dict[str, Any],
    data_path: str | None = None,
    *,
    opt_in: Any = False,
) -> dict[str, Any]:
    """
    Append one evaluated student record.

    A record is saved only when:
        1. opt_in is explicit student consent
        2. the record was successfully AI processed
    """

    path = _resolve_path(data_path)

    if not _is_opted_in(opt_in):
        return {
            "ok": False,
            "error": (
                "Save refused: student opt-in required "
                "(pass opt_in=True)."
            ),
            "path": str(path),
            "record": None,
        }

    if not isinstance(record, dict):
        return {
            "ok": False,
            "error": "record must be a dict",
            "path": str(path),
            "record": None,
        }

    ai_error = _ai_success_error(record)

    if ai_error is not None:
        return {
            "ok": False,
            "error": ai_error,
            "path": str(path),
            "record": None,
        }

    ok, records, load_error = _read_records_file(path)

    if not ok:
        return {
            "ok": False,
            "error": load_error,
            "path": str(path),
            "record": None,
        }

    if load_error and "Corrupted" in load_error:
        records = []

    stored = dict(record)
    stored.pop("feelings_text", None)
    stored.pop("reflection", None)
    stored["save_opt_in"] = True

    if not stored.get("saved_at"):
        stored["saved_at"] = datetime.now(timezone.utc).isoformat()

    _ensure_record_id(stored)
    records.append(stored)

    write_ok, write_error = _write_records_file(path, records)

    if not write_ok:
        return {
            "ok": False,
            "error": write_error,
            "path": str(path),
            "record": None,
        }

    return {
        "ok": True,
        "error": None,
        "path": str(path),
        "record": stored,
    }


def save_pending_record(
    record: dict[str, Any],
    data_path: str | None = None,
    *,
    opt_in: Any = False,
) -> dict[str, Any]:
    """Append a check-in that could not be evaluated because AI was unavailable.

    The answers are kept for admin follow-up and marked pending.
    Reflection text is never stored.
    """

    path = _resolve_path(data_path)

    if not _is_opted_in(opt_in):
        return {
            "ok": False,
            "error": (
                "Save refused: student opt-in required "
                "(pass opt_in=True)."
            ),
            "path": str(path),
            "record": None,
        }

    if not isinstance(record, dict):
        return {
            "ok": False,
            "error": "record must be a dict",
            "path": str(path),
            "record": None,
        }

    ok, records, load_error = _read_records_file(path)

    if not ok:
        return {
            "ok": False,
            "error": load_error,
            "path": str(path),
            "record": None,
        }

    if load_error and "Corrupted" in load_error:
        records = []

    stored = dict(record)
    stored.pop("feelings_text", None)
    stored.pop("reflection", None)
    stored["status"] = "pending"
    stored["ai_ok"] = False
    stored["save_opt_in"] = True

    if not stored.get("saved_at"):
        stored["saved_at"] = datetime.now(timezone.utc).isoformat()

    _ensure_record_id(stored)
    records.append(stored)

    write_ok, write_error = _write_records_file(path, records)

    if not write_ok:
        return {
            "ok": False,
            "error": write_error,
            "path": str(path),
            "record": None,
        }

    return {
        "ok": True,
        "error": None,
        "path": str(path),
        "record": stored,
    }


def replace_pending_record(
    record_id: str,
    new_record: dict[str, Any],
    data_path: str | None = None,
    *,
    opt_in: Any = False,
) -> dict[str, Any]:
    """Upgrade one pending check-in to its evaluated result.

    The row keeps ``record_id``. When that id is not in the file yet,
    the evaluated record is appended once. Reflection text is never
    stored. The write is atomic (temp file, then os.replace).
    """

    path = _resolve_path(data_path)
    clean_id = record_id.strip() if isinstance(record_id, str) else ""

    if not clean_id:
        return {
            "ok": False,
            "error": "record_id is required",
            "path": str(path),
            "record": None,
        }

    if not _is_opted_in(opt_in):
        return {
            "ok": False,
            "error": (
                "Save refused: student opt-in required "
                "(pass opt_in=True)."
            ),
            "path": str(path),
            "record": None,
        }

    if not isinstance(new_record, dict):
        return {
            "ok": False,
            "error": "record must be a dict",
            "path": str(path),
            "record": None,
        }

    ai_error = _ai_success_error(new_record)

    if ai_error is not None:
        return {
            "ok": False,
            "error": ai_error,
            "path": str(path),
            "record": None,
        }

    ok, records, load_error = _read_records_file(path)

    if not ok:
        return {
            "ok": False,
            "error": load_error,
            "path": str(path),
            "record": None,
        }

    if load_error and "Corrupted" in load_error:
        records = []

    stored = dict(new_record)
    stored.pop("feelings_text", None)
    stored.pop("reflection", None)
    stored.pop("status", None)
    stored["record_id"] = clean_id
    stored["save_opt_in"] = True

    if not stored.get("saved_at"):
        stored["saved_at"] = datetime.now(timezone.utc).isoformat()

    replaced = False

    for index, existing in enumerate(records):
        if str(existing.get("record_id", "")).strip() == clean_id:
            records[index] = stored
            replaced = True
            break

    if not replaced:
        records.append(stored)

    write_ok, write_error = _write_records_file(path, records)

    if not write_ok:
        return {
            "ok": False,
            "error": write_error,
            "path": str(path),
            "record": None,
        }

    return {
        "ok": True,
        "error": None,
        "path": str(path),
        "record": stored,
    }


def filter_records(
    records: list[dict[str, Any]],
    **filters: Any,
) -> list[dict[str, Any]]:
    """
    Filter records in memory.

    Supported filters:
        student_id
        risk_category
        tier            You're doing ok / Worth a check-in / Please reach out
        cohort_year
    """

    if not isinstance(records, list):
        return []

    student_id = filters.get("student_id")
    risk_category = filters.get("risk_category")
    tier = filters.get("tier")
    cohort_year = filters.get("cohort_year")

    out: list[dict[str, Any]] = []

    for record in records:
        if not isinstance(record, dict):
            continue

        if student_id is not None:
            if str(record.get("student_id", "")) != str(student_id):
                continue

        if risk_category is not None:
            if (
                str(record.get("risk_category", "")).lower()
                != str(risk_category).lower()
            ):
                continue

        if tier is not None:
            label = str(record.get("soft_label") or "")
            category = str(record.get("risk_category") or "")
            if label != str(tier) and category != TIER_TO_CATEGORY.get(str(tier)):
                continue

        if cohort_year is not None:
            prefix = str(cohort_year).zfill(2)[-2:]
            sid = str(record.get("student_id", ""))

            if len(sid) < 2 or sid[:2] != prefix:
                continue

        out.append(record)

    return out

    loaded = load_all_records(data_path)

    return filter_records(
        loaded["records"],
        student_id=student_id,
    )