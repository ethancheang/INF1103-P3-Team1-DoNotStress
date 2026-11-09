"""End-to-end tests of the web app through Flask's test client.

The live Gemini client is replaced by ScriptedTextGenerator and records go to
a temporary file, so the full pipeline (I/O -> AI -> Logic -> Data) runs
without a network connection or an API key.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from campus_app import CampusApp
from doubles import ScriptedTextGenerator
from sample_ai_records import HIGH_REPLY, HIGH_STUDENT, LOW_STRESS_REPLY, LOW_STRESS_STUDENT

ADMIN = {"username": "admin", "password": "DoNotStress2026!"}


def form_for(student, **changes):
    """The browser's JSON body for one sample student."""
    keys = ("student_id", "pss_1", "pss_2", "pss_3", "pss_4", "sleep_hours_avg", "sleep_quality",
            "pas_workload", "pas_catchup", "fin_stress", "mspss_friends", "mspss_family")
    return {**{key: student[key] for key in keys}, "feelings_text": "", **changes}


class CampusAppTestCase(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.data_path = Path(self.folder.name) / "student_records.json"
        self.generator = ScriptedTextGenerator()
        campus = CampusApp(
            {"TESTING": True, "SECRET_KEY": "test", "DATA_PATH": str(self.data_path), "AI_RETRY_DELAY_SEC": 0},
            text_generator=self.generator,
        )
        self.client = campus.flask_app.test_client()

    def tearDown(self):
        self.folder.cleanup()

    def csrf(self):
        self.client.get("/")
        with self.client.session_transaction() as session:
            return session["csrf_token"]

    def submit(self, form):
        return self.client.post("/", json=form, headers={"X-CSRF-Token": self.csrf()})

    def login(self):
        return self.client.post("/admin/login", data={**ADMIN, "csrf_token": self.csrf()})

    def saved(self):
        return json.loads(self.data_path.read_text(encoding="utf-8")) if self.data_path.exists() else []


class CheckinFlowTests(CampusAppTestCase):
    def test_home_page_renders(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"campus-config", response.data)

    def test_post_without_csrf_token_is_refused(self):
        self.assertEqual(self.client.post("/", json=form_for(LOW_STRESS_STUDENT)).status_code, 403)

    def test_successful_checkin_is_evaluated_saved_and_shown(self):
        self.generator.queue(json.dumps(LOW_STRESS_REPLY))
        response = self.submit(form_for(LOW_STRESS_STUDENT, feelings_text="private reflection"))
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["result"]["soft"]["heading"], "You're doing ok")
        records = self.saved()
        self.assertEqual(len(records), 1)
        self.assertEqual((records[0]["source"], records[0]["ai_ok"]), ("ai_logic", True))
        self.assertNotIn("private reflection", self.data_path.read_text(encoding="utf-8"))
        self.assertNotIn(LOW_STRESS_STUDENT["student_id"], self.generator.prompts[0])
        self.assertEqual(self.client.get("/result").status_code, 200)

    def test_ai_failure_saves_pending_then_a_retry_upgrades_the_same_row(self):
        response = self.submit(form_for(LOW_STRESS_STUDENT))  # the scripted AI only returns "not json"
        self.assertEqual(response.status_code, 503)
        self.assertIn(response.get_json()["error_code"], ("invalid_response", "retries_exhausted"))
        self.assertEqual([r["status"] for r in self.saved()], ["pending"])

        self.generator.queue(json.dumps(LOW_STRESS_REPLY))
        self.assertEqual(self.submit(form_for(LOW_STRESS_STUDENT)).status_code, 200)
        records = self.saved()
        self.assertEqual(len(records), 1)
        self.assertNotIn("status", records[0])

    def test_missing_api_key_is_reported_without_crashing(self):
        unconfigured = CampusApp(
            {"TESTING": True, "SECRET_KEY": "t", "DATA_PATH": str(self.data_path), "AI_RETRY_DELAY_SEC": 0},
            text_generator=ScriptedTextGenerator(configured=False),
        )
        self.client = unconfigured.flask_app.test_client()
        response = self.submit(form_for(LOW_STRESS_STUDENT))
        self.assertEqual((response.status_code, response.get_json()["error_code"]), (503, "missing_api_key"))

    def test_invalid_input_lists_every_problem(self):
        response = self.submit(form_for(LOW_STRESS_STUDENT, student_id="123", pss_1=9))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(set(response.get_json()["errors"]), {"student_id", "pss_1"})
        self.assertEqual(self.saved(), [])

    def test_corrupt_records_file_does_not_crash_or_get_overwritten(self):
        self.data_path.write_text("{ corrupt", encoding="utf-8")
        self.generator.queue(json.dumps(LOW_STRESS_REPLY))
        self.assertEqual(self.submit(form_for(LOW_STRESS_STUDENT)).status_code, 500)
        self.assertEqual(self.data_path.read_text(encoding="utf-8"), "{ corrupt")
        self.login()
        self.assertEqual(self.client.get("/api/records").status_code, 500)


class AdminTests(CampusAppTestCase):
    def test_records_need_admin_sign_in(self):
        self.assertEqual(self.client.get("/api/records").status_code, 401)
        self.assertEqual(self.client.get("/records").status_code, 302)

    def test_wrong_password_is_refused(self):
        response = self.client.post("/admin/login", data={**ADMIN, "password": "nope", "csrf_token": self.csrf()})
        self.assertEqual(response.status_code, 401)

    def test_records_filters_and_cohort_summary(self):
        self.generator.queue(json.dumps(LOW_STRESS_REPLY))
        self.submit(form_for(LOW_STRESS_STUDENT))
        self.generator.queue(json.dumps(HIGH_REPLY))
        self.submit(form_for(HIGH_STUDENT))
        self.assertEqual(self.login().status_code, 302)

        body = self.client.get("/api/records").get_json()
        self.assertEqual((body["total"], body["matching"]), (2, 2))
        self.assertEqual(body["cohorts"], ["26", "24"])
        self.assertEqual(body["summary"]["checkins"], {"total": 2, "evaluated": 2, "pending": 0})
        self.assertEqual(body["summary"]["stress"]["support_priority"], 1)
        self.assertTrue(all("reasoning" not in row and "feelings_text" not in row for row in body["records"]))

        high = self.client.get("/api/records", query_string={"tier": "Please reach out"}).get_json()
        self.assertEqual([row["student_id"] for row in high["records"]], ["2400001"])
        self.assertEqual(high["summary"]["tiers"]["items"][2]["label"], "Please reach out")

        self.assertEqual(self.client.get("/api/records", query_string={"tier": "Bogus"}).status_code, 400)
        self.assertEqual(self.client.get("/api/records", query_string={"cohort_year": "abc"}).status_code, 400)

    def test_logout_revokes_access(self):
        self.login()
        self.assertEqual(self.client.get("/api/records").status_code, 200)
        self.client.post("/admin/logout", data={"csrf_token": self.csrf()})
        self.assertEqual(self.client.get("/api/records").status_code, 401)


if __name__ == "__main__":
    unittest.main()
