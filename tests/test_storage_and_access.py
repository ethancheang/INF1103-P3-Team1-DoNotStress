"""Storage failure paths, input rejection before AI, and browser access rules.

Ported from main's test_storage.py, test_frontend.py and
test_admin_access.py, which were dropped in the 19-class refactor.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from werkzeug.security import generate_password_hash

from json_storage import JSONStorage
from web_controller import WebController

try:
    from tests.fake_provider import FakeProvider
    from tests.test_trimmed_app import sample_answers, wired_app
except ModuleNotFoundError:
    from fake_provider import FakeProvider
    from test_trimmed_app import sample_answers, wired_app


class TestStorageFailures(unittest.TestCase):
    """JSONStorage never loses or half-writes rows when the disk misbehaves."""

    def test_missing_and_blank_files_mean_no_rows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            self.assertEqual(JSONStorage(path).load(), [])
            path.write_text("  \n", encoding="utf-8")
            self.assertEqual(JSONStorage(path).load(), [])

    def test_failed_backup_leaves_the_corrupt_file_untouched(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            path.write_text("{corrupt", encoding="utf-8")
            storage = JSONStorage(path)
            with patch("json_storage.shutil.copy2",
                       side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    storage.append({"record_id": "a"})
            self.assertEqual(path.read_text(encoding="utf-8"), "{corrupt")
            self.assertEqual(list(Path(tmp).glob("*.corrupt-*.json")), [])

    def test_failed_write_keeps_old_rows_and_leaves_no_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            storage = JSONStorage(path)
            storage.append({"record_id": "a"})
            with patch("json_storage.os.replace",
                       side_effect=OSError("file locked")):
                with self.assertRaises(OSError):
                    storage.append({"record_id": "b"})
            self.assertEqual([row["record_id"] for row in storage.load()],
                             ["a"])
            self.assertEqual(list(Path(tmp).glob(".records.json.*.tmp")), [])

    def test_replace_returns_the_stored_row_and_never_edits_its_input(
            self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            storage = JSONStorage(Path(tmp) / "records.json")
            storage.append({"record_id": "a", "saved_at": "first"})
            row = {"record_id": "a", "saved_at": "second"}
            stored = storage.replace("a", row, preserve=("saved_at",))
            self.assertEqual(row["saved_at"], "second")
            self.assertIsNotNone(stored)
            self.assertEqual(stored["saved_at"], "first")
            refused = storage.replace("a", row,
                                      only_if=lambda existing: False)
            self.assertIsNone(refused)
            self.assertEqual(storage.load()[0]["saved_at"], "first")


class TestBrowserAccess(unittest.TestCase):
    """What a browser can and cannot reach through WebController."""

    PASSWORD: str = "correct horse battery staple"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.provider = FakeProvider()
        self.admin_hash = generate_password_hash(self.PASSWORD)
        self.app, self.web = wired_app(
            test_config={"TESTING": True, "SECRET_KEY": "test-secret",
                         "ADMIN_PASSWORD_HASH": self.admin_hash},
            provider=self.provider,
            data_path=Path(self.tmp.name) / "records.json",
            testing=True,
        )
        self.client = self.web.flask.test_client()

    def tearDown(self) -> None:
        self.app.close()
        self.tmp.cleanup()

    def csrf(self) -> str:
        with self.client.session_transaction() as sess:
            return str(sess["csrf_token"])

    def sign_in(self) -> None:
        self.client.get("/admin/login")
        self.client.post("/admin/login", data={
            "username": WebController.ADMIN_USERNAME,
            "password": self.PASSWORD,
            "csrf_token": self.csrf(),
        })

    def test_invalid_form_is_rejected_before_any_ai_call(self) -> None:
        self.client.get("/")
        bad = {**sample_answers(), "student_id": "1234567", "pss_1": "9"}
        response = self.client.post("/", json=bad,
                                    headers={"X-CSRF-Token": self.csrf()})
        self.assertEqual(response.status_code, 400)
        errors = response.get_json()["errors"]
        self.assertIn("student_id", errors)
        self.assertIn("pss_1", errors)
        self.assertEqual(self.provider.calls, [])

    def test_logout_revokes_the_admin_token_on_the_server(self) -> None:
        self.sign_in()
        with self.client.session_transaction() as sess:
            old_token = sess["admin_token"]
        self.assertEqual(self.client.get("/records").status_code, 200)
        self.client.post("/admin/logout",
                         headers={"X-CSRF-Token": self.csrf()})
        with self.client.session_transaction() as sess:
            sess["admin_token"] = old_token
        replay = self.client.get("/records")
        self.assertEqual(replay.status_code, 302)
        self.assertIn("/admin/login", replay.headers["Location"])

    def test_admin_hash_never_reaches_the_browser(self) -> None:
        for url in ("/", "/admin/login", "/history", "/static/campus.js"):
            body = self.client.get(url).data
            self.assertNotIn(self.admin_hash.encode("utf-8"), body, url)

    def test_forget_this_device_deletes_the_history_cookie(self) -> None:
        self.client.get("/history")
        self.client.set_cookie(WebController.HISTORY_COOKIE_NAME, "a" * 32)
        response = self.client.post("/api/history/forget",
                                    headers={"X-CSRF-Token": self.csrf()})
        self.assertEqual(response.status_code, 200)
        cookie = response.headers.get("Set-Cookie", "")
        self.assertIn(f"{WebController.HISTORY_COOKIE_NAME}=;", cookie)
        self.assertIn("Max-Age=0", cookie)

    def test_forget_this_device_requires_csrf(self) -> None:
        self.client.get("/history")
        response = self.client.post("/api/history/forget")
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
