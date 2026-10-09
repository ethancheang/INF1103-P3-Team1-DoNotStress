from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ============================================================
# FILE PATH
# ============================================================

_PACKAGE_ROOT = Path(__file__).resolve().parent

_DEFAULT_DATA_PATH = _PACKAGE_ROOT / "data" / "student_record.json"


def get_default_data_path() -> str:
    """Return the default JSON file path."""
    return str(_DEFAULT_DATA_PATH)


def _resolve_path(data_path: str | None = None) -> Path:
    """Use the default path unless another path is provided."""
    if data_path is None or str(data_path).strip() == "":
        return _DEFAULT_DATA_PATH

    return Path(data_path)


# ============================================================
# VALIDATION
# ============================================================

_REQUIRED_AI_FIELDS = (
    "risk_score",
    "risk_category",
    "primary_stressors",
    "recommended_support",
    "confidence",
    "reasoning",
)

_AI_SUCCESS_SOURCES = {
    "gemini",
    "ai",
    "ai_manager",
    "gemini+logic",
    "ai_logic",
}

_BLOCKED_SOURCES = {
    "logic_fallback",
    "fallback",
    "logic_only",
    "logic",
}


def _is_opted_in(opt_in: Any) -> bool:
    """Check whether the student explicitly consented."""

    if opt_in is True:
        return True

    if isinstance(opt_in, str):
        return opt_in.strip().lower() in {
            "true",
            "yes",
            "1",
            "on",
        }

    return False


def _is_valid_probability(value: Any) -> bool:
    """Check whether a value is between 0 and 1."""

    if isinstance(value, bool):
        return False

    try:
        number = float(value)
    except (TypeError, ValueError):
        return False

    return 0.0 <= number <= 1.0


def _validate_ai_fields(record: dict[str, Any]) -> str | None:
    """Validate required AI result fields."""

    missing = [
        field
        for field in _REQUIRED_AI_FIELDS
        if field not in record
    ]

    if missing:
        return "Missing AI fields: " + ", ".join(missing)

    if not _is_valid_probability(record["risk_score"]):
        return "risk_score must be between 0 and 1."

    if not _is_valid_probability(record["confidence"]):
        return "confidence must be between 0 and 1."

    if record["risk_category"] not in {
        "Low",
        "Moderate",
        "High",
    }:
        return "Invalid risk_category."

    if not isinstance(record["primary_stressors"], list):
        return "primary_stressors must be a list."

    if not all(
        isinstance(item, str)
        for item in record["primary_stressors"]
    ):
        return "primary_stressors must contain strings."

    if not isinstance(record["recommended_support"], str):
        return "recommended_support must be a string."

    if not isinstance(record["reasoning"], str):
        return "reasoning must be a string."

    return None


def _ai_success_error(record: dict[str, Any]) -> str | None:
    """Check whether the record came from successful AI processing."""

    if not isinstance(record, dict):
        return "Record must be a dictionary."

    source = str(record.get("source", "")).strip().lower()

    if source in _BLOCKED_SOURCES:
        return "Record was not successfully AI processed."

    if (
        record.get("ai_ok") is not True
        and source not in _AI_SUCCESS_SOURCES
    ):
        return "Successful AI processing is required."

    return _validate_ai_fields(record)


# ============================================================
# FILE HANDLING
# ============================================================

def _ensure_parent_dir(path: Path) -> None:
    """Create the data folder if it does not exist."""
    path.parent.mkdir(parents=True, exist_ok=True)


def _read_records_file(
    path: Path,
) -> tuple[bool, list[dict[str, Any]], str | None]:
    """
    Read student records from JSON.

    Handles:
    - Missing files
    - Empty files
    - Corrupted JSON
    - File permission errors
    """

    if not path.exists():
        return True, [], None

    try:
        raw = path.read_text(encoding="utf-8")

    except OSError as exc:
        return False, [], f"Unable to read file: {exc}"

    if raw.strip() == "":
        return True, [], None

    try:
        payload = json.loads(raw)

    except json.JSONDecodeError as exc:
        return False, [], f"Corrupted JSON file: {exc}"

    if isinstance(payload, list):
        if not all(isinstance(item, dict) for item in payload):
            return False, [], "JSON records must be dictionaries."

        return True, payload, None

    if isinstance(payload, dict):
        records = payload.get("records")

        if isinstance(records, list) and all(
            isinstance(item, dict) for item in records
        ):
            return True, records, None

    return False, [], "Invalid JSON records format."


def _write_records_file(
    path: Path,
    records: list[dict[str, Any]],
) -> tuple[bool, str | None]:
    """Write records to JSON and create the folder if needed."""

    try:
        _ensure_parent_dir(path)

        content = json.dumps(
            records,
            indent=2,
            ensure_ascii=False,
        )

        path.write_text(
            content + "\n",
            encoding="utf-8",
        )

        return True, None

    except (OSError, TypeError, ValueError) as exc:
        return False, f"Unable to save records: {exc}"


# ============================================================
# LOAD RECORDS
# ============================================================

def load_all_records(
    data_path: str | None = None,
) -> dict[str, Any]:
    """Load all previously saved student records."""

    path = _resolve_path(data_path)

    ok, records, error = _read_records_file(path)

    return {
        "ok": ok,
        "records": records,
        "error": error,
        "path": str(path),
    }


# ============================================================
# SAVE STUDENT INPUTS
# WORKS EVEN WHEN GEMINI API FAILS
# ============================================================

def save_student_input(
    student_input: dict[str, Any],
    data_path: str | None = None,
    *,
    opt_in: Any = False,
    ai_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Save student check-in inputs regardless of Gemini API status.

    The student must give consent.

    If Gemini fails:
        ai_status = "failed"
        ai_result = None

    If Gemini succeeds:
        ai_status = "success"
        ai_result = AI response
    """

    path = _resolve_path(data_path)

    if not _is_opted_in(opt_in):
        return {
            "ok": False,
            "error": "Student consent is required.",
            "path": str(path),
            "record": None,
        }

    if not isinstance(student_input, dict):
        return {
            "ok": False,
            "error": "Student input must be a dictionary.",
            "path": str(path),
            "record": None,
        }

    ok, records, error = _read_records_file(path)

    if not ok:
        return {
            "ok": False,
            "error": error,
            "path": str(path),
            "record": None,
        }

    record = dict(student_input)

    record["ai_status"] = (
        "success"
        if ai_result is not None
        else "failed"
    )

    record["ai_result"] = ai_result

    record["source"] = (
        "gemini"
        if ai_result is not None
        else "user_input"
    )

    record["save_opt_in"] = True

    record["saved_at"] = datetime.now(
        timezone.utc
    ).isoformat()

    records.append(record)

    write_ok, write_error = _write_records_file(
        path,
        records,
    )

    return {
        "ok": write_ok,
        "error": write_error,
        "path": str(path),
        "record": record if write_ok else None,
    }


# ============================================================
# SAVE SUCCESSFUL AI RECORDS
# ORIGINAL FUNCTION
# ============================================================

def save_record(
    record: dict[str, Any],
    data_path: str | None = None,
    *,
    opt_in: Any = False,
) -> dict[str, Any]:
    """
    Save a successfully AI-processed student record.

    Requires:
    - Student consent
    - Successful AI processing
    - All required AI fields
    """

    path = _resolve_path(data_path)

    if not _is_opted_in(opt_in):
        return {
            "ok": False,
            "error": "Student consent is required.",
            "path": str(path),
            "record": None,
        }

    if not isinstance(record, dict):
        return {
            "ok": False,
            "error": "Record must be a dictionary.",
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

    ok, records, error = _read_records_file(path)

    if not ok:
        return {
            "ok": False,
            "error": error,
            "path": str(path),
            "record": None,
        }

    stored = dict(record)

    stored["save_opt_in"] = True

    if not stored.get("saved_at"):
        stored["saved_at"] = datetime.now(
            timezone.utc
        ).isoformat()

    records.append(stored)

    write_ok, write_error = _write_records_file(
        path,
        records,
    )

    return {
        "ok": write_ok,
        "error": write_error,
        "path": str(path),
        "record": stored if write_ok else None,
    }


# ============================================================
# FILTER RECORDS
# ============================================================

def filter_records(
    records: list[dict[str, Any]],
    **filters: Any,
) -> list[dict[str, Any]]:
    """
    Filter student records by:
    - student_id
    - risk_category
    - cohort_year
    """

    if not isinstance(records, list):
        return []

    student_id = filters.get("student_id")
    risk_category = filters.get("risk_category")
    cohort_year = filters.get("cohort_year")

    filtered = []

    for record in records:

        if not isinstance(record, dict):
            continue

        if student_id is not None:
            if str(record.get("student_id", "")) != str(student_id):
                continue

        if risk_category is not None:
            category = record.get("risk_category")

            if category is None and isinstance(
                record.get("ai_result"), dict
            ):
                category = record["ai_result"].get("risk_category")

            if str(category or "").lower() != str(
                risk_category
            ).lower():
                continue

        if cohort_year is not None:
            prefix = str(cohort_year).zfill(2)[-2:]

            sid = str(record.get("student_id", ""))

            if len(sid) < 2 or sid[:2] != prefix:
                continue

        filtered.append(record)

    return filtered


# ============================================================
# QUERY FUNCTIONS
# ============================================================

def get_record_by_student_id(
    student_id: str,
    data_path: str | None = None,
) -> list[dict[str, Any]]:
    """Get all records belonging to a student."""

    loaded = load_all_records(data_path)

    return filter_records(
        loaded["records"],
        student_id=student_id,
    )


def get_records_by_risk_category(
    category: str,
    data_path: str | None = None,
) -> list[dict[str, Any]]:
    """Get all records with a matching risk category."""

    loaded = load_all_records(data_path)

    return filter_records(
        loaded["records"],
        risk_category=category,
    )


def get_records_by_cohort_year(
    year_prefix: str,
    data_path: str | None = None,
) -> list[dict[str, Any]]:
    """Get records using the first two digits of student ID."""

    loaded = load_all_records(data_path)

    return filter_records(
        loaded["records"],
        cohort_year=year_prefix,
    )