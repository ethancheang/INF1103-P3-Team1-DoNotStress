"""DoNotStress Data Manager (Phase 2, object-oriented).

Saves and loads check-in records, supports querying and filtering, and
handles missing or corrupt files without crashing or losing data.

    RecordRepository (interface)
      '- JsonRecordRepository   the JSON-file store used by the app
           |- JsonRecordsFile   atomic read/write of the file
           '- AIRecordCheck     only AI-processed records are saved as evaluated
    RecordFilter                search criteria (student ID, tier, cohort)
    RecordStatus                "Evaluated" or "Pending" for a stored record
    DataStoreError              every failure the callers need to handle

Reflection text is never stored. Each class lives in its own .py file.
"""

from .ai_record_check import AIRecordCheck
from .data_store_error import DataStoreError
from .json_record_repository import JsonRecordRepository
from .json_records_file import JsonRecordsFile
from .record_filter import RecordFilter
from .record_repository import RecordRepository
from .record_status import RecordStatus

__all__ = [
    "AIRecordCheck",
    "DataStoreError",
    "JsonRecordRepository",
    "JsonRecordsFile",
    "RecordFilter",
    "RecordRepository",
    "RecordStatus",
]
