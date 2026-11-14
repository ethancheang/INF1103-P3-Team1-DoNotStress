"""JSONStorage on its own, plus the dict a save returns."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from plain_tests import capture_logs, case, function_suite
import data_manager
from json_storage import JSONStorage


def test_save_reports_the_stored_row_or_the_error():
    """A save returns a dict: the stored row, or the reason nothing was stored."""
    with tempfile.TemporaryDirectory() as temp:
        path = str(Path(temp) / "records.json")
        saved = data_manager.save_pending_record(
            {"record_id": "abc123", "student_id": "2600001"}, path, opt_in=True)
        assert saved["ok"] and saved["error"] is None
        assert saved["record"]["record_id"] == "abc123"
        assert saved["record"]["student_id"] == "2600001"
        refused = data_manager.save_pending_record(
            {"student_id": "2600001"}, path, opt_in=False)
        assert not refused["ok"] and refused["record"] is None
        assert "opt-in" in refused["error"]


def test_a_missing_or_empty_file_is_no_records():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "records.json"
        storage = JSONStorage(path)
        assert storage.location == str(path)
        assert storage.load() == []
        path.write_text("  \n", encoding="utf-8")
        assert storage.load() == []
        path.write_text('{"records": [{"student_id": "2000001"}, 3]}',
                        encoding="utf-8")
        assert [row["student_id"] for row in storage.load()] == ["2000001"]


def test_json_storage_appends_and_replaces_rows():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "records.json"
        storage = JSONStorage(path)
        storage.append({"record_id": "a", "student_id": "2600001"})
        storage.append({"record_id": "b", "student_id": "2600002"})
        storage.replace("a", {"record_id": "a", "student_id": "2700001"})
        storage.replace("c", {"record_id": "c", "student_id": "2700003"})
        rows = json.loads(path.read_text(encoding="utf-8"))
        assert [row["record_id"] for row in rows] == ["a", "b", "c"]
        assert rows[0]["student_id"] == "2700001"
        storage.load().clear()
        assert len(storage.load()) == 3


def test_a_corrupt_file_is_backed_up_and_never_read_as_empty():
    for corrupt in ('[{"student_id": "2603503"', '"just text"'):
        with case(corrupt=corrupt), tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "records.json"
            storage = JSONStorage(path)
            path.write_text(corrupt, encoding="utf-8")
            with capture_logs("data_manager", level="WARNING"):
                try:
                    storage.load()
                except OSError as error:
                    assert "Corrupted" in str(error)
                else:
                    raise AssertionError("corrupt data must raise")
            with capture_logs("data_manager", level="WARNING"):
                storage.append({"student_id": "2000123"})
            backups = sorted(Path(temp).glob("records.corrupt-*.json"))
            assert len(backups) == 2
            assert backups[0].read_text(encoding="utf-8") == corrupt
            assert len(storage.load()) == 1


def test_an_object_without_a_records_list_is_backed_up():
    for corrupt in ('{}', '{"other": 1}'):
        with case(corrupt=corrupt), tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "records.json"
            storage = JSONStorage(path)
            path.write_text(corrupt, encoding="utf-8")
            with capture_logs("data_manager", level="WARNING"):
                try:
                    storage.load()
                except OSError as error:
                    assert "expected a list" in str(error)
                else:
                    raise AssertionError("an object with no records must raise")
                storage.append({"student_id": "2000123"})
            backups = sorted(Path(temp).glob("records.corrupt-*.json"))
            assert len(backups) == 2
            assert backups[-1].read_text(encoding="utf-8") == corrupt
            assert [row["student_id"] for row in storage.load()] == ["2000123"]


def test_nothing_is_overwritten_when_the_backup_fails():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "records.json"
        storage = JSONStorage(path)
        path.write_text("{broken", encoding="utf-8")
        with patch("json_storage.shutil.copy2",
                   side_effect=OSError("disk full")), \
                capture_logs("data_manager", level="WARNING"):
            try:
                storage.append({"student_id": "2000123"})
            except OSError as error:
                assert "Backup failed" in str(error)
            else:
                raise AssertionError("a failed backup must raise")
        assert path.read_text(encoding="utf-8") == "{broken"


def test_a_failed_write_reports_an_error_and_leaves_no_temp_file():
    with tempfile.TemporaryDirectory() as temp:
        path = Path(temp) / "records.json"
        storage = JSONStorage(path)
        try:
            with patch("json_storage.os.replace",
                       side_effect=OSError("read-only")):
                storage.append({"student_id": "2600001"})
        except OSError as error:
            assert "Could not write" in str(error)
        else:
            raise AssertionError("a failed write must raise")
        assert list(Path(temp).iterdir()) == []


def load_tests(loader, tests, pattern):
    """Let `python -m unittest discover -s tests` run this file's tests."""
    return function_suite(globals())


if __name__ == "__main__":
    unittest.main()
