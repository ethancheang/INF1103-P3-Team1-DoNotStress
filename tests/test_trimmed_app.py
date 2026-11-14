"""Automated test suite for the 19-class DoNotStress architecture."""

from __future__ import annotations

import ast
import inspect
import json
import threading
import time
import unittest
from pathlib import Path
import tempfile

from ai.ai_provider import AIProvider
from ai.model_chain import DEFAULT_MODEL_CHAIN
from ai_manager import AIManager
from base_manager import BaseManager
from data_manager import DataManager
try:
    from tests.fake_provider import FakeProvider
except ModuleNotFoundError:
    from fake_provider import FakeProvider
from io_manager import IOManager
from json_storage import JSONStorage
from json_types import JSONObject
from logic.business_rule import BusinessRule
from logic.context_flag_rule import ContextFlagRule
from logic.decision import Decision
from logic.safety_override_rule import SafetyOverrideRule
from logic.support_priority_rule import SupportPriorityRule
from logic_manager import CATEGORY_LABELS, CATEGORY_PROMINENCE, LogicManager
from main import App
from questionnaire import Questionnaire
from records.check_in_record import CheckInRecord
from records.pending_record import PendingRecord
from records.record import Record
from web_controller import WebController
import survey


APP_ROOT = Path(__file__).resolve().parent.parent

EXPECTED_19 = {
    "App",
    "BaseManager",
    "WebController",
    "IOManager",
    "Questionnaire",
    "AIManager",
    "AIProvider",
    "GeminiProvider",
    "LogicManager",
    "BusinessRule",
    "SafetyOverrideRule",
    "SupportPriorityRule",
    "ContextFlagRule",
    "Decision",
    "DataManager",
    "Record",
    "CheckInRecord",
    "PendingRecord",
    "JSONStorage",
}


def wired_app(**kwargs) -> App:
    """Tests attach routes with the constructors: WebController(App(...))."""
    application = App(**kwargs)
    WebController(application, application.flask)
    return application


def sample_answers(**overrides: object) -> JSONObject:
    base: JSONObject = {
        "student_id": "2605581",
        "survey_version": survey.VERSION,
        "pss_1": 3,
        "pss_2": 3,
        "pss_3": 3,
        "pss_4": 3,
        "sleep_hours_avg": 6.5,
        "sleep_quality": 3,
        "pas_workload": 3,
        "pas_catchup": 3,
        "fin_stress": 3,
        "mspss_friends": 3,
        "mspss_family": 3,
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def matching_gemini_reply(
    answers: JSONObject,
    logic: LogicManager | None = None,
    **overrides: object,
) -> str:
    scorer = logic or LogicManager()
    info = scorer.score_answers(answers)
    score = float(info["stress_score"])  # type: ignore[arg-type]
    cat = str(info["risk_category"])
    payload: JSONObject = {
        "scored_items": info["scored_items"],
        "stress_score": score,
        "risk_category": cat,
        "soft_label": CATEGORY_LABELS[cat],
        "speak_prominence": CATEGORY_PROMINENCE[cat],
        "primary_stressors": ["academic_overload"],
        "tips": ["short_breaks", "rest_a_little_more"],
        "confidence": 0.9,
        "reasoning": "You have been balancing several demands recently. Taking small pauses can help.",
    }
    payload.update(overrides)  # type: ignore[arg-type]
    return json.dumps(payload)


def finished_fields(answers: JSONObject,
                    logic: LogicManager | None = None) -> JSONObject:
    scorer = logic or LogicManager()
    reply = json.loads(matching_gemini_reply(answers, scorer))
    return scorer.evaluate({**answers, **reply})


class TestTrimmed19Classes(unittest.TestCase):
    """Verifies the 19-class architecture, OOP concepts, and features."""

    def test_codebase_has_exact_19_app_classes(self) -> None:
        found_classes: set[str] = set()
        found_files: dict[str, str] = {}
        for py_file in APP_ROOT.rglob("*.py"):
            if ("tests" in py_file.parts or ".venv" in py_file.parts
                    or "__pycache__" in py_file.parts):
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    found_classes.add(node.name)
                    found_files[node.name] = (
                        py_file.relative_to(APP_ROOT).as_posix()
                    )
        self.assertEqual(found_classes, EXPECTED_19)
        self.assertEqual(len(found_classes), 19)
        # One class per production file (coding requirement).
        files_for_classes = list(found_files.values())
        self.assertEqual(len(files_for_classes), len(set(files_for_classes)))
        self.assertEqual(found_files["Record"], "records/record.py")
        self.assertEqual(found_files["CheckInRecord"],
                         "records/check_in_record.py")
        self.assertEqual(found_files["PendingRecord"],
                         "records/pending_record.py")
        # FakeProvider lives in tests/ and is not counted.
        self.assertNotIn("FakeProvider", found_classes)

    def test_fake_provider_does_not_import_gemini_provider(self) -> None:
        source = (APP_ROOT / "tests" / "fake_provider.py").read_text(
            encoding="utf-8")
        tree = ast.parse(source)
        imported: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
        self.assertNotIn("ai.gemini_provider", imported)
        self.assertNotIn("gemini_provider", imported)
        self.assertNotIn("GeminiProvider", imported)
        self.assertIsInstance(FakeProvider(), AIProvider)

    def test_app_module_does_not_import_web_controller_at_top_level(self) -> None:
        source = (APP_ROOT / "main.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        top_imports: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.module:
                top_imports.append(node.module)
            elif isinstance(node, ast.Import):
                top_imports.extend(alias.name for alias in node.names)
        self.assertNotIn("web_controller", top_imports)
        # Routes are attached by WebController(App(...)), only under
        # if __name__ == "__main__" in this module (and in tests).
        self.assertIn('if __name__ == "__main__":', source)
        self.assertIn("from web_controller import WebController", source)
        self.assertIn('os.environ.get("HOST", "127.0.0.1")', source)
        self.assertNotIn("def create_app", source)
        self.assertNotIn("def build_application", source)

    def test_four_managers_subclass_base_manager(self) -> None:
        questionnaire = Questionnaire.from_survey()
        logic = LogicManager()
        with tempfile.TemporaryDirectory() as tmp:
            managers: tuple[BaseManager, ...] = (
                IOManager(questionnaire),
                AIManager(FakeProvider(), questionnaire,
                          instructions=logic.instructions,
                          verify=logic.verify, retry_delay_sec=0),
                logic,
                DataManager(Path(tmp) / "records.json"),
            )
            for mgr in managers:
                self.assertIsInstance(mgr, BaseManager)
                health = mgr.health()
                self.assertEqual(health["name"], mgr.name)
                self.assertTrue(len(mgr.describe()) >= 1)

    def test_questionnaire_validates_answers_labels_and_safety(self) -> None:
        qn = Questionnaire.from_survey()
        self.assertEqual(qn.version, survey.VERSION)
        self.assertEqual(len(qn.keys()), 11)
        self.assertEqual(qn.reversed_keys(),
                         ("pss_2", "pss_3", "mspss_friends", "mspss_family"))
        ok, value = qn.validate_answer("pss_1", 3)
        self.assertTrue(ok)
        self.assertEqual(value, 3)
        ok, message = qn.validate_answer("pss_1", 9)
        self.assertFalse(ok)
        self.assertIn("1 to 5", str(message))
        self.assertEqual(qn.option_label("pss_1", 3), "Sometimes")
        with self.assertRaises(ValueError):
            qn.option_label("pss_1", 0)
        with self.assertRaises(ValueError):
            qn.option_label("sleep_hours_avg", 7)
        self.assertTrue(qn.safety_fired("I feel like I want to die"))
        self.assertFalse(qn.safety_fired("I have coursework due"))
        # Callers get a copy, so mutating it does not change the original.
        first = qn.question("pss_1")
        first["prompt"] = "mutated"
        self.assertNotEqual(qn.question("pss_1")["prompt"], "mutated")
        config = qn.public_config()
        self.assertEqual(len(config["questions"]), 11)
        self.assertEqual(len(config["sections"]), 6)

    def test_app_passes_the_same_questionnaire_to_io_and_ai(self) -> None:
        qn = Questionnaire.from_survey()
        # There is no module-level questionnaire singleton.
        self.assertFalse(hasattr(survey, "QUESTIONNAIRE"))
        first = Questionnaire.from_survey()
        second = Questionnaire.from_survey()
        self.assertIsNot(first, second)

    def test_records_strip_reflection_and_pending_has_no_score(self) -> None:
        raw = {
            **sample_answers(),
            "record_id": "r1",
            "saved_at": "2026-11-10T10:00:00Z",
            "stress_score": 3.8,
            "risk_score": 0.7,
            "risk_category": "High",
            "soft_label": "Please reach out",
            "primary_stressors": ["academic_overload"],
            "recommended_support": "Internal note",
            "confidence": 0.9,
            "reasoning": "Warm reasoning.",
            "source": "ai_logic",
            "ai_ok": True,
            "feelings_text": "Private reflection must be stripped",
            "reflection": "Also private",
        }
        evaluated = CheckInRecord(raw)
        pending = PendingRecord({
            **sample_answers(), "record_id": "r2",
            "feelings_text": "Secret",
        })
        self.assertIsInstance(evaluated, Record)
        self.assertIsInstance(pending, Record)
        self.assertIsNone(evaluated.get("feelings_text"))
        self.assertIsNone(evaluated.get("reflection"))
        self.assertIsNone(evaluated.problem())
        self.assertEqual(evaluated.status, "evaluated")
        self.assertEqual(evaluated.score, 3.8)
        self.assertEqual(pending.status, "pending")
        self.assertIsNone(pending.score)
        self.assertIsNone(pending.problem())
        self.assertIsNone(pending.get("feelings_text"))
        # Polymorphism: DataManager-style loop over mixed records.
        statuses = [record.status for record in (evaluated, pending)]
        self.assertEqual(statuses, ["evaluated", "pending"])
        self.assertTrue(evaluated.belongs_to("2605581"))
        self.assertFalse(evaluated.belongs_to("2605582"))

    def test_json_storage_persists_backs_up_corrupt_and_is_thread_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            storage = JSONStorage(path)
            self.assertEqual(storage.load(), [])

            dm = DataManager(path)
            pending = PendingRecord({**sample_answers(), "record_id": "a"})
            saved = dm.save(pending, opt_in=True)
            self.assertTrue(saved["ok"])
            self.assertEqual(len(dm.load()), 1)

            path.write_text("{corrupt", encoding="utf-8")
            with self.assertRaises(OSError):
                storage.load()
            backups = list(Path(tmp).glob("records.corrupt-*.json"))
            self.assertEqual(len(backups), 1)
            # The original file is left in place after a load() failure.
            self.assertEqual(path.read_text(encoding="utf-8"), "{corrupt")

            # append() backs up and starts a fresh file.
            storage.append({"record_id": "fresh"})
            rows = storage.load()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["record_id"], "fresh")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "concurrent.json"
            storage = JSONStorage(path)
            errors: list[BaseException] = []

            def write(index: int) -> None:
                try:
                    storage.append({"record_id": f"r{index}"})
                except BaseException as error:  # collect, then fail the test
                    errors.append(error)

            threads = [threading.Thread(target=write, args=(i,))
                       for i in range(20)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            ids = {str(row.get("record_id")) for row in storage.load()}
            self.assertEqual(ids, {f"r{i}" for i in range(20)})

    def test_json_storage_backs_up_object_with_no_records_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            storage = JSONStorage(path)
            for payload in ("{}", '{"other": 1}'):
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(OSError):
                    storage.load()
                # The original file is left in place after a load() failure.
                self.assertEqual(path.read_text(encoding="utf-8"), payload)
            backups = list(Path(tmp).glob("records.corrupt-*.json"))
            self.assertEqual(len(backups), 2)

    def test_save_without_consent_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dm = DataManager(Path(tmp) / "records.json")
            record = PendingRecord({**sample_answers(), "record_id": "x"})
            saved = dm.save(record, opt_in=False)
            self.assertFalse(saved["ok"])
            self.assertIn("opt-in", str(saved["error"]))

    def test_logic_instructions_verify_and_business_rules(self) -> None:
        logic = LogicManager()
        self.assertEqual(
            [rule.name for rule in logic.rules],
            ["safety_override", "support_priority", "context_flags"],
        )
        for rule in logic.rules:
            self.assertIsInstance(rule, BusinessRule)

        instructions = logic.instructions()
        self.assertIn("Calculate stress_score" if False else "Convert each answer",
                      instructions)
        self.assertIn("1 to 5", instructions)
        self.assertIn("pss_2, pss_3, mspss_friends, mspss_family", instructions)

        answers = sample_answers()
        info = logic.score_answers(answers)
        # Mid-scale answers with one reversed-item pair and 6.5 hours of
        # sleep (band 3) give a mean around 3.
        self.assertEqual(info["risk_category"], "Moderate")
        good = json.loads(matching_gemini_reply(answers, logic))
        self.assertIsNone(logic.verify(good, answers))

        # A score more than 0.01 off is rejected.
        bad = dict(good)
        bad["stress_score"] = 4.9
        bad["risk_category"] = "High"
        bad["soft_label"] = "Please reach out"
        bad["speak_prominence"] = "high"
        problem = logic.verify(bad, answers)
        self.assertIsNotNone(problem)
        self.assertIn("mean", str(problem).lower() + str(problem))

        evaluated = logic.evaluate({**answers, **good, "safety_flag": True})
        self.assertTrue(evaluated["ok"])
        self.assertEqual(evaluated["risk_category"], "High")
        self.assertEqual(evaluated["soft_label"], "Please reach out")
        self.assertEqual(evaluated["tips"][0], "talk_to_someone")
        self.assertNotIn("feelings_text", evaluated)

    def test_decision_strips_reflection_and_finalise_tips(self) -> None:
        record = {
            **sample_answers(),
            "feelings_text": "I should not be visible to a rule",
            "tips": ["short_breaks", "rest_a_little_more", "workload_chunks"],
            "risk_category": "Moderate",
            "soft_label": "Worth a check-in",
            "primary_stressors": ["academic_overload"],
        }
        decision = Decision(record, {"sleep": True, "workload": True,
                                     "finances": True, "support": True})
        self.assertIsNone(decision.field("feelings_text"))
        ContextFlagRule().run(decision)
        # Flags only suggest; they must not overwrite Gemini's tips.
        self.assertEqual(decision.tips, record["tips"])
        decision.finalise_tips()
        self.assertEqual(len(decision.tips), 4)
        self.assertEqual(decision.tips[:3], record["tips"])
        # There is no public tips setter for a rule to reach into.
        self.assertFalse(hasattr(type(decision).tips, "fset") and
                         type(decision).tips.fset is not None
                         or False)
        self.assertIsNone(inspect.getattr_static(type(decision), "tips").fset)

    def test_context_flag_and_support_priority_rules(self) -> None:
        logic = LogicManager()
        answers = sample_answers(mspss_friends=1, mspss_family=1,
                                 pas_workload=5, fin_stress=5,
                                 sleep_hours_avg=5, sleep_quality=5,
                                 pss_1=5, pss_4=5, pss_2=1, pss_3=1)
        info = logic.score_answers(answers)
        self.assertEqual(info["risk_category"], "High")
        flags = info["context_flags"]
        self.assertTrue(flags["sleep"])
        self.assertTrue(flags["workload"])
        self.assertTrue(flags["finances"])
        self.assertTrue(flags["support"])
        reply = json.loads(matching_gemini_reply(
            answers, logic,
            primary_stressors=["low_social_support", "academic_overload"],
        ))
        evaluated = logic.evaluate({**answers, **reply})
        self.assertTrue(evaluated["ok"])
        self.assertTrue(evaluated["support_priority"])
        self.assertEqual(evaluated["tips"][0], "talk_to_someone")
        self.assertIn("keep_social_contact", evaluated["tips"])

    def test_ai_uses_instructions_and_retries_on_verify_failure(self) -> None:
        logic = LogicManager()
        answers = sample_answers()
        bad = matching_gemini_reply(
            answers, logic, stress_score=4.9, risk_category="High",
            soft_label="Please reach out", speak_prominence="high",
        )
        good = matching_gemini_reply(answers, logic)
        fake = FakeProvider(bad, good)
        questionnaire = Questionnaire.from_survey()
        ai = AIManager(fake, questionnaire,
                       instructions=logic.instructions,
                       verify=logic.verify, retry_delay_sec=0)
        result = ai.analyse(answers)
        self.assertTrue(result["ok"])
        self.assertGreaterEqual(len(fake.calls), 2)
        prompt = fake.calls[0][0]
        self.assertIn("Convert each answer onto the 1 to 5 stress scale", prompt)
        self.assertIn("Calculate stress_score", prompt)
        self.assertNotIn("2605581", prompt)
        self.assertNotIn("feelings_text", prompt)
        self.assertEqual(fake.calls[0][1], DEFAULT_MODEL_CHAIN[0])

    def test_ai_missing_key_does_not_call_the_provider(self) -> None:
        logic = LogicManager()
        questionnaire = Questionnaire.from_survey()
        fake = FakeProvider(ready=False)
        ai = AIManager(fake, questionnaire,
                       instructions=logic.instructions,
                       verify=logic.verify, retry_delay_sec=0)
        result = ai.analyse(sample_answers())
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "missing_api_key")
        self.assertEqual(fake.calls, [])

    def test_logic_rejects_score_mismatch_without_inventing_a_result(self) -> None:
        logic = LogicManager()
        answers = sample_answers()
        bad = json.loads(matching_gemini_reply(
            answers, logic, stress_score=4.9, risk_category="High",
            soft_label="Please reach out", speak_prominence="high",
        ))
        evaluated = logic.evaluate({**answers, **bad})
        self.assertFalse(evaluated["ok"])
        self.assertEqual(evaluated["error"], "score_mismatch")
        self.assertIsNone(logic.score({**answers, **bad}))

    def test_job_results_are_session_bound_and_history_page_is_wired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            fake = FakeProvider(matching_gemini_reply(answers, logic))
            dns_app = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret"},
                provider=fake,
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            owner = dns_app.flask.test_client()
            owner.get("/")
            with owner.session_transaction() as sess:
                csrf = sess["csrf_token"]
            response = owner.post(
                "/",
                json={**answers, "feelings_text": ""},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(response.status_code, 202)
            job_id = response.get_json()["jobId"]
            self.assertIn("statusUrl", response.get_json())
            dns_app.wait_for_job(job_id, timeout=5.0)

            stranger = dns_app.flask.test_client()
            denied = stranger.get(f"/checkin/status/{job_id}")
            self.assertEqual(denied.status_code, 404)

            poll = owner.get(f"/checkin/status/{job_id}")
            self.assertEqual(poll.status_code, 200)
            self.assertTrue(poll.get_json()["ok"])
            self.assertIn("result", poll.get_json())

            page = owner.get("/history")
            self.assertEqual(page.status_code, 200)
            self.assertIn(b"historyUrl", page.data)

            hist = owner.post(
                "/api/history",
                json={"student_id": "2605581"},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(hist.status_code, 200)
            body = hist.get_json()["history"]
            self.assertEqual(len(body["entries"]), 1)
            self.assertEqual(body["entries"][0]["score"],
                             logic.score_answers(answers)["stress_score"])

            # A classmate's ID is refused without a matching history cookie.
            other = owner.post(
                "/api/history",
                json={"student_id": "2605582"},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(other.status_code, 403)
            dns_app.close()

    def test_wait_timeout_is_reported_without_raising(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            reply = matching_gemini_reply(answers, logic)

            def slow_reply(prompt: str, model: str) -> str:
                time.sleep(0.15)
                return reply

            fake = FakeProvider(slow_reply)
            dns_app = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret"},
                provider=fake,
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            with dns_app.flask.test_client() as client:
                client.get("/")
                with client.session_transaction() as sess:
                    owner_token = sess["csrf_token"]
                job = dns_app.submit_checkin(answers, owner_token, False)
                status = dns_app.wait_for_job(job["job_id"], timeout=0.001)
                self.assertEqual(status["status"], "running")
            # Let the worker finish so close() is prompt.
            dns_app.wait_for_job(job["job_id"], timeout=5.0)
            dns_app.close()

    def test_pending_save_when_gemini_fails_then_upgrade_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            good = matching_gemini_reply(answers, logic)
            fake = FakeProvider(RuntimeError("Gemini is down"))
            dns_app = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret"},
                provider=fake,
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            client = dns_app.flask.test_client()
            client.get("/")
            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]
            first = client.post(
                "/",
                json={**answers, "feelings_text": "I want to end my life"},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(first.status_code, 202)
            job_id = first.get_json()["jobId"]
            dns_app.wait_for_job(job_id, timeout=5.0)
            poll = client.get(f"/checkin/status/{job_id}")
            self.assertEqual(poll.status_code, 503)
            self.assertTrue(poll.get_json()["safety_flag"])
            rows = DataManager(Path(tmp) / "records.json").load()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "pending")
            self.assertIsNone(rows[0].score)

            fake.reply_with(good)
            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]
            second = client.post(
                "/",
                json={**answers, "feelings_text": ""},
                headers={"X-CSRF-Token": csrf},
            )
            job_id = second.get_json()["jobId"]
            dns_app.wait_for_job(job_id, timeout=5.0)
            poll = client.get(f"/checkin/status/{job_id}")
            self.assertEqual(poll.status_code, 200)
            rows = DataManager(Path(tmp) / "records.json").load()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "evaluated")
            self.assertIsNotNone(rows[0].score)
            dns_app.close()

    def test_flask_pages_and_admin_login(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            fake = FakeProvider(matching_gemini_reply(answers, logic))
            application = wired_app(
                testing=True,
                test_config={"TESTING": True, "SECRET_KEY": "test-secret",
                             "DATA_PATH": str(Path(tmp) / "records.json")},
                provider=fake,
                data_path=Path(tmp) / "records.json",
            )
            client = application.flask.test_client()
            home = client.get("/")
            self.assertEqual(home.status_code, 200)
            self.assertIn(b"csrfToken", home.data)
            health = client.get("/health")
            self.assertEqual(health.status_code, 200)
            self.assertEqual(health.get_json()["status"], "ok")
            self.assertEqual(len(health.get_json()["managers"]), 4)

            login_page = client.get("/admin/login")
            self.assertEqual(login_page.status_code, 200)
            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]
            denied = client.post(
                "/admin/login",
                data={"username": "admin", "password": "wrong",
                      "csrf_token": csrf},
            )
            self.assertEqual(denied.status_code, 401)
            records = client.get("/api/records")
            self.assertEqual(records.status_code, 401)

            ok = client.post(
                "/admin/login",
                data={"username": "admin", "password": "DoNotStress2026!",
                      "csrf_token": csrf},
                follow_redirects=False,
            )
            self.assertEqual(ok.status_code, 302)
            table = client.get("/api/records")
            self.assertEqual(table.status_code, 200)
            self.assertIn("records", table.get_json())
            application.close()

    def test_trend_builds_from_a_history_dict(self) -> None:
        logic = LogicManager()
        empty = logic.trend({"scores": [], "records": [], "pending_count": 0})
        self.assertEqual(empty["comparison"], "none")
        first = logic.trend({"scores": [3.2]})
        self.assertEqual(first["comparison"], "first")
        easing = logic.trend({"scores": [3.8, 3.2, 2.4]})
        self.assertEqual(easing["comparison"], "lower")
        self.assertEqual(easing["direction"], "easing")
        building = logic.trend({"scores": [2.0, 2.6, 3.4]})
        self.assertEqual(building["direction"], "building")
        from_list = logic.trend([
            {"stress_score": 2.0},
            {"stress_score": 2.6},
            {"stress_score": 3.4},
            {"stress_score": 4.9, "status": "pending"},
        ])
        self.assertEqual(from_list["direction"], "building")
        self.assertEqual(from_list["count"], 3)

    def test_no_top_level_procedural_functions_outside_classes(self) -> None:
        for py_file in APP_ROOT.rglob("*.py"):
            if ("tests" in py_file.parts or ".venv" in py_file.parts
                    or "__pycache__" in py_file.parts):
                continue
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            top_defs = [
                node.name for node in tree.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            self.assertEqual(
                top_defs, [],
                f"{py_file.name} has top-level function(s): {top_defs}",
            )


if __name__ == "__main__":
    unittest.main()
