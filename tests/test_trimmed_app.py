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
from unittest.mock import patch

from ai.ai_provider import AIProvider
from ai.gemini_provider import GeminiProvider
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
from logic_manager import (ANSWER_KEYS, CATEGORY_LABELS, CATEGORY_PROMINENCE,
                           REVERSED_KEYS, SLEEP_HOURS_BELOW_ALL,
                           SLEEP_HOUR_BANDS, SLEEP_KEY, LogicManager)
from main import App
from questionnaire import Questionnaire
from records.check_in_record import CheckInRecord
from records.pending_record import PendingRecord
from records.record import Record
from flask import session as flask_session
from werkzeug.security import generate_password_hash
from web_controller import WebController
import survey
import web_controller


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


def wired_app(**kwargs) -> tuple[App, WebController]:
    """Tests attach routes with WebController(App(...))."""
    test_config = kwargs.get("test_config")
    application = App(**kwargs)
    controller = WebController(application, test_config=test_config)
    return application, controller


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


def _expected_scored_items(answers: JSONObject) -> dict[str, int]:
    scored: dict[str, int] = {}
    for key in ANSWER_KEYS:
        raw = float(answers[key])  # type: ignore[arg-type]
        if key == SLEEP_KEY:
            value = SLEEP_HOURS_BELOW_ALL
            for at_least, band_val in SLEEP_HOUR_BANDS:
                if raw >= at_least:
                    value = band_val
                    break
        elif key in REVERSED_KEYS:
            value = int(6 - raw)
        else:
            value = int(raw)
        scored[key] = value
    return scored


def _expected_category(score: float) -> str:
    if score > 3.5:
        return "High"
    if score >= 2.5:
        return "Moderate"
    return "Low"


def matching_gemini_reply(
    answers: JSONObject,
    logic: LogicManager | None = None,
    **overrides: object,
) -> str:
    del logic
    scored_items = _expected_scored_items(answers)
    score = round(sum(scored_items.values()) / len(scored_items), 2)
    cat = _expected_category(score)
    payload: JSONObject = {
        "scored_items": scored_items,
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
        self.assertNotIn("flask", top_imports)
        self.assertNotIn("records", top_imports)
        self.assertNotIn("dotenv", top_imports)
        top_calls = [
            node.value.func.id
            for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Name)
        ]
        self.assertEqual(top_calls, [])
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
        self.assertFalse(qn.validate_answer("pss_1", float("nan"))[0])
        self.assertFalse(qn.validate_answer("pss_1", float("inf"))[0])
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
        # There is no module-level questionnaire singleton or import-time maps.
        self.assertFalse(hasattr(survey, "QUESTIONNAIRE"))
        self.assertFalse(hasattr(survey, "QUESTION_MAP"))
        self.assertFalse(hasattr(survey, "REVERSED_KEYS"))
        first = Questionnaire.from_survey()
        second = Questionnaire.from_survey()
        self.assertIsNot(first, second)
        wired_logic = LogicManager(
            answer_keys=qn.keys(), reversed_keys=qn.reversed_keys()
        )
        self.assertEqual(wired_logic.describe()["answer_count"], len(qn.keys()))
        self.assertEqual(ANSWER_KEYS, qn.keys())
        self.assertEqual(set(REVERSED_KEYS), set(qn.reversed_keys()))

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
            for _ in range(2):
                with self.assertRaises(OSError):
                    storage.load()
            self.assertEqual(list(Path(tmp).glob("records.corrupt-*.json")), [])
            # The original file is left in place after a load() failure.
            self.assertEqual(path.read_text(encoding="utf-8"), "{corrupt")

            # append() backs up once and starts a fresh file.
            storage.append({"record_id": "fresh"})
            self.assertEqual(
                len(list(Path(tmp).glob("records.corrupt-*.json"))), 1)
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

    def test_json_storage_backs_up_corrupt_variants_only_on_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            storage = JSONStorage(path)
            for index, payload in enumerate(("{}", '{"other": 1}', '["bad"]'), 1):
                path.write_text(payload, encoding="utf-8")
                with self.assertRaises(OSError):
                    storage.load()
                self.assertEqual(path.read_text(encoding="utf-8"), payload)
                self.assertEqual(
                    len(list(Path(tmp).glob("records.corrupt-*.json"))),
                    index - 1,
                )
                storage.append({"record_id": f"r{index}"})
                self.assertEqual(
                    len(list(Path(tmp).glob("records.corrupt-*.json"))), index)

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
        good = json.loads(matching_gemini_reply(answers, logic))
        self.assertEqual(good["risk_category"], "Moderate")
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

    def test_decision_strips_reflection_encapsulates_tier_and_preserves_safety_lead(self) -> None:
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
        # M1/m1: mutating returned list from field() must not mutate Decision.
        returned_stressors = decision.field("primary_stressors")
        assert isinstance(returned_stressors, list)
        returned_stressors.append("financial_pressure")
        self.assertEqual(decision.field("primary_stressors"), ["academic_overload"])

        ContextFlagRule().run(decision)
        # Flags only suggest; they must not overwrite Gemini's tips.
        self.assertEqual(decision.tips, record["tips"])
        decision.finalise_tips()
        self.assertEqual(len(decision.tips), 4)
        self.assertEqual(decision.tips[:3], record["tips"])
        # M3: No public setters on Decision.
        for prop in ("tips", "risk_category", "soft_label",
                     "speak_prominence", "support_priority"):
            self.assertIsNone(
                inspect.getattr_static(type(decision), prop).fset,
                f"Decision.{prop} must be read-only",
            )

        # M2: OCP proof - a later rule leading with a different tip cannot
        # displace SafetyOverrideRule's talk_to_someone tip.
        class LeadsWithBreaks(BusinessRule):
            @property
            def name(self) -> str:
                return "breaks"

            def applies(self, d: Decision) -> bool:
                return True

            def apply(self, d: Decision) -> None:
                d.lead_with("short_breaks")

        safety_answers = sample_answers(safety_flag=True)
        reply = json.loads(matching_gemini_reply(
            safety_answers, tips=["sleep_routine"]))
        out = LogicManager(rules=(SafetyOverrideRule(), LeadsWithBreaks())
                           ).evaluate({**safety_answers, **reply})
        self.assertEqual(out["tips"][0], "talk_to_someone")

    def test_context_flag_and_support_priority_rules(self) -> None:
        logic = LogicManager()
        answers = sample_answers(mspss_friends=1, mspss_family=1,
                                 pas_workload=5, fin_stress=5,
                                 sleep_hours_avg=5, sleep_quality=5,
                                 pss_1=5, pss_4=5, pss_2=1, pss_3=1)
        reply = json.loads(matching_gemini_reply(
            answers, logic,
            primary_stressors=["low_social_support", "academic_overload"],
        ))
        evaluated = logic.evaluate({**answers, **reply})
        self.assertTrue(evaluated["ok"])
        self.assertEqual(evaluated["risk_category"], "High")
        flags = evaluated["context_flags"]
        self.assertTrue(flags["sleep"])
        self.assertTrue(flags["workload"])
        self.assertTrue(flags["finances"])
        self.assertTrue(flags["support"])
        self.assertTrue(evaluated["support_priority"])
        self.assertEqual(evaluated["tips"][0], "talk_to_someone")
        self.assertIn("keep_social_contact", evaluated["tips"])

    def test_ai_uses_instructions_retries_and_matches_main_validation(self) -> None:
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
        self.assertEqual(fake.calls[0][1], GeminiProvider.MODEL_CHAIN[0])

        # M4: Numeric strings like "0.62" are accepted; float scored_items rejected.
        string_conf = matching_gemini_reply(answers, logic, confidence="0.62")
        fake_str = FakeProvider(string_conf)
        res_str = AIManager(
            fake_str, questionnaire,
            instructions=logic.instructions, verify=logic.verify,
            retry_delay_sec=0,
        ).analyse(answers)
        self.assertTrue(res_str["ok"])

        float_items = _expected_scored_items(answers)
        float_scored = {k: float(v) for k, v in float_items.items()}
        bad_float = matching_gemini_reply(answers, logic, scored_items=float_scored)
        res_float = AIManager(
            FakeProvider(bad_float), questionnaire,
            instructions=logic.instructions, verify=logic.verify,
            retry_delay_sec=0,
        ).analyse(answers)
        self.assertFalse(res_float["ok"])
        self.assertEqual(res_float["error_code"], "invalid_response")

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

    def test_job_results_are_session_bound_and_history_is_record_scoped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            expected_score = json.loads(matching_gemini_reply(answers, logic))["stress_score"]
            fake = FakeProvider(matching_gemini_reply(answers, logic))
            dns_app, web = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret"},
                provider=fake,
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            owner = web.flask.test_client()
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

            stranger = web.flask.test_client()
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
            self.assertEqual(body["entries"][0]["score"], expected_score)

            # B3: A second browser has no history for 2605581 (403), and even if it
            # submits once under 2605581 it sees ONLY its own 1 entry, never owner's.
            stranger.get("/")
            with stranger.session_transaction() as sess:
                s_csrf = sess["csrf_token"]
            blocked = stranger.post(
                "/api/history",
                json={"student_id": "2605581"},
                headers={"X-CSRF-Token": s_csrf},
            )
            self.assertEqual(blocked.status_code, 403)

            s_answers = sample_answers(pss_1=5, pss_4=5)
            fake.reply_with(matching_gemini_reply(s_answers, logic))
            s_post = stranger.post(
                "/",
                json={**s_answers, "feelings_text": ""},
                headers={"X-CSRF-Token": s_csrf},
            )
            s_job = s_post.get_json()["jobId"]
            dns_app.wait_for_job(s_job, timeout=5.0)
            self.assertEqual(stranger.get(f"/checkin/status/{s_job}").status_code, 200)
            s_hist = stranger.post(
                "/api/history",
                json={"student_id": "2605581"},
                headers={"X-CSRF-Token": s_csrf},
            )
            self.assertEqual(s_hist.status_code, 200)
            self.assertEqual(len(s_hist.get_json()["history"]["entries"]), 1)
            dns_app.close()

    def test_wait_timeout_and_per_owner_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            reply = matching_gemini_reply(answers, logic)

            def slow_reply(prompt: str, model: str) -> str:
                time.sleep(0.15)
                return reply

            fake = FakeProvider(slow_reply)
            dns_app, web = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret"},
                provider=fake,
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            with web.flask.test_client() as client:
                client.get("/")
                with client.session_transaction() as sess:
                    owner_id = sess["owner_id"]
                job1 = dns_app.submit_checkin(answers, owner_id)
                job2 = dns_app.submit_checkin(
                    sample_answers(pss_1=4), owner_id)
                busy = dns_app.submit_checkin(
                    sample_answers(pss_1=5), owner_id)
                self.assertEqual(busy["status"], "busy")
                status = dns_app.wait_for_job(job1["job_id"], timeout=0.001)
                self.assertEqual(status["status"], "running")
            dns_app.wait_for_job(job1["job_id"], timeout=5.0)
            dns_app.wait_for_job(job2["job_id"], timeout=5.0)
            dns_app.close()

    def test_pending_save_when_gemini_fails_then_upgrade_on_retry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            good = matching_gemini_reply(answers, logic)
            fake = FakeProvider(RuntimeError("Gemini is down"))
            dns_app, web = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret"},
                provider=fake,
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            client = web.flask.test_client()
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
            admin_hash = generate_password_hash("TestAdminPass!")
            application, web = wired_app(
                testing=True,
                test_config={
                    "TESTING": True,
                    "SECRET_KEY": "test-secret",
                    "DATA_PATH": str(Path(tmp) / "records.json"),
                    "ADMIN_PASSWORD_HASH": admin_hash,
                },
                provider=fake,
                data_path=Path(tmp) / "records.json",
            )
            client = web.flask.test_client()
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
                data={"username": "admin", "password": "TestAdminPass!",
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

    def test_record_problem_guards_ai_deadline_owner_id_and_admin_hash(self) -> None:
        # m2 / m3: Record base fields and stress_score are enforced on restore
        missing_sid = PendingRecord({"student_id": "", "survey_version": "pss10_sleep_v1"})
        self.assertIsNotNone(missing_sid.problem())
        answers = sample_answers()
        logic = LogicManager()
        complete_row = finished_fields(answers, logic)
        self.assertIsNone(CheckInRecord(complete_row).problem())
        del complete_row["stress_score"]
        problem = CheckInRecord(complete_row).problem()
        self.assertIsNotNone(problem)
        self.assertIn("stress_score", str(problem))

        # m9: Overall timeout stops retries cleanly
        fake = FakeProvider(RuntimeError("503 unavailable"))
        ai = AIManager(
            fake,
            Questionnaire.from_survey(),
            instructions=logic.instructions,
            verify=logic.verify,
            overall_timeout_sec=0.0,
        )
        res = ai.analyse(answers)
        self.assertFalse(res["ok"])
        self.assertEqual(res["error_code"], "timeout")
        self.assertEqual(fake.calls, [])

        # m8 & m12: Unset ADMIN_PASSWORD_HASH fails closed; admin login rotates CSRF but keeps owner_id
        with tempfile.TemporaryDirectory() as tmp:
            app_no_hash, web_no_hash = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret",
                             "ADMIN_PASSWORD_HASH": ""},
                provider=fake,
                data_path=Path(tmp) / "a.json",
                testing=True,
            )
            c1 = web_no_hash.flask.test_client()
            c1.get("/admin/login")
            with c1.session_transaction() as sess:
                csrf1 = sess["csrf_token"]
            r_no_hash = c1.post("/admin/login", data={
                "username": "admin", "password": "any-password", "csrf_token": csrf1,
            })
            self.assertEqual(r_no_hash.status_code, 401)
            app_no_hash.close()

            admin_hash = generate_password_hash("TestAdminPass!")
            app_ok, web_ok = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret",
                             "ADMIN_PASSWORD_HASH": admin_hash},
                provider=fake,
                data_path=Path(tmp) / "b.json",
                testing=True,
            )
            c2 = web_ok.flask.test_client()
            c2.get("/")
            with c2.session_transaction() as sess:
                owner_before = sess["owner_id"]
                csrf_before = sess["csrf_token"]
            r_login = c2.post("/admin/login", data={
                "username": "admin", "password": "TestAdminPass!",
                "csrf_token": csrf_before,
            })
            self.assertEqual(r_login.status_code, 302)
            with c2.session_transaction() as sess:
                self.assertEqual(sess["owner_id"], owner_before)
                self.assertNotEqual(sess["csrf_token"], csrf_before)
            app_ok.close()

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

    def test_encapsulation_and_copy_isolation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            fake = FakeProvider(matching_gemini_reply(answers, logic))
            dns_app, web = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret"},
                provider=fake,
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            self.assertNotIn("admin_sessions", web.flask.extensions)
            self.assertFalse(hasattr(dns_app, "managers"))
            self.assertIn("history", dns_app.status_message("history_locked"))
            with web.flask.test_request_context("/"):
                token = web._WebController__put_result({"soft": {"label": "Worth a check-in"}})
                flask_session["checkin_token"] = token
                first = web._WebController__current_result()
                assert isinstance(first, dict) and isinstance(first["soft"], dict)
                first["soft"]["label"] = "mutated"
                second = web._WebController__current_result()
                assert isinstance(second, dict) and isinstance(second["soft"], dict)
                self.assertEqual(second["soft"]["label"], "Worth a check-in")
            dns_app.close()

    def test_ai_code_fences_rate_limit_fallback_and_key_redaction(self) -> None:
        logic = LogicManager()
        answers = sample_answers()
        good = matching_gemini_reply(answers, logic)
        questionnaire = Questionnaire.from_survey()

        fenced_ai = AIManager(
            FakeProvider(f"```json\n{good}\n```"),
            questionnaire,
            instructions=logic.instructions,
            verify=logic.verify,
            retry_delay_sec=0,
        )
        self.assertTrue(fenced_ai.analyse(answers)["ok"])

        bad_ai = AIManager(
            FakeProvider("not valid json at all"),
            questionnaire,
            instructions=logic.instructions,
            verify=logic.verify,
            max_attempts=1,
            retry_delay_sec=0,
        )
        bad_res = bad_ai.analyse(answers)
        self.assertFalse(bad_res["ok"])
        self.assertEqual(bad_res["error_code"], "invalid_response")

        rate_fake = FakeProvider(
            RuntimeError("429 ResourceExhausted"),
            RuntimeError("429 ResourceExhausted"),
            RuntimeError("429 ResourceExhausted"),
        )
        rate_res = AIManager(
            rate_fake,
            questionnaire,
            instructions=logic.instructions,
            verify=logic.verify,
            retry_delay_sec=0,
        ).analyse(answers)
        self.assertFalse(rate_res["ok"])
        self.assertEqual(rate_res["error_code"], "rate_limited")
        self.assertEqual(
            [model for _, model in rate_fake.calls],
            list(GeminiProvider.MODEL_CHAIN),
        )

        provider = GeminiProvider(api_key="SECRET_KEY_123")
        self.assertEqual(
            provider.redact("Failure using SECRET_KEY_123 here"),
            "Failure using [redacted] here",
        )

    def test_corrupt_storage_and_non_finite_scores_on_history_and_admin(self) -> None:
        nan_row = finished_fields(sample_answers(), LogicManager())
        nan_row["stress_score"] = float("nan")
        nan_row["record_id"] = "nan1"
        self.assertIsNone(CheckInRecord(nan_row).score)
        inf_row = dict(nan_row, record_id="inf1", stress_score=float("inf"))
        self.assertIsNone(CheckInRecord(inf_row).score)

        io = IOManager(Questionnaire.from_survey())
        history_view = io.display_history(
            {"student_id": "2605581", "records": [nan_row], "pending_count": 0},
            {"comparison": "none", "direction": "not_enough", "change": float("nan")},
        )
        self.assertIsNone(history_view["entries"][0]["score"])
        self.assertIsNone(history_view["trend"]["change"])

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "records.json"
            admin_hash = generate_password_hash("TestAdminPass!")
            dns_app, web = wired_app(
                test_config={
                    "TESTING": True,
                    "SECRET_KEY": "test-secret",
                    "ADMIN_PASSWORD_HASH": admin_hash,
                },
                provider=FakeProvider(),
                data_path=path,
                testing=True,
            )
            client = web.flask.test_client()
            client.get("/admin/login")
            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]
            client.post(
                "/admin/login",
                data={"username": "admin", "password": "TestAdminPass!",
                      "csrf_token": csrf},
            )
            path.write_text("{corrupt", encoding="utf-8")
            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]
            hist_res = client.post(
                "/api/history",
                json={"student_id": "2605581"},
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(hist_res.status_code, 500)
            rec_res = client.get("/api/records")
            self.assertEqual(rec_res.status_code, 500)
            self.assertEqual(list(Path(tmp).glob("records.corrupt-*.json")), [])
            dns_app.close()

    def test_repeat_identical_checkin_does_not_overwrite_completed_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            good = matching_gemini_reply(answers, logic)
            fake = FakeProvider(good)
            path = Path(tmp) / "records.json"
            dns_app, web = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret"},
                provider=fake,
                data_path=path,
                testing=True,
            )
            client = web.flask.test_client()
            client.get("/")
            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]

            r1 = client.post("/", json={**answers, "feelings_text": ""},
                             headers={"X-CSRF-Token": csrf})
            j1 = r1.get_json()["jobId"]
            dns_app.wait_for_job(j1, timeout=5.0)
            self.assertEqual(client.get(f"/checkin/status/{j1}").status_code, 200)
            self.assertEqual(len(DataManager(path).load()), 1)

            # Second identical submit when Gemini fails must create a new pending row,
            # leaving the completed check-in untouched.
            fake.reply_with(RuntimeError("Gemini down"))
            r2 = client.post("/", json={**answers, "feelings_text": ""},
                             headers={"X-CSRF-Token": csrf})
            j2 = r2.get_json()["jobId"]
            dns_app.wait_for_job(j2, timeout=5.0)
            self.assertEqual(client.get(f"/checkin/status/{j2}").status_code, 503)
            rows = DataManager(path).load()
            self.assertEqual([row.status for row in rows], ["evaluated", "pending"])

            # Retrying the second check-in upgrades only the pending row.
            fake.reply_with(good)
            r3 = client.post("/", json={**answers, "feelings_text": ""},
                             headers={"X-CSRF-Token": csrf})
            j3 = r3.get_json()["jobId"]
            dns_app.wait_for_job(j3, timeout=5.0)
            self.assertEqual(client.get(f"/checkin/status/{j3}").status_code, 200)
            rows = DataManager(path).load()
            self.assertEqual([row.status for row in rows], ["evaluated", "evaluated"])

            # Third distinct completed check-in appends instead of overwriting row 2.
            fake.reply_with(good)
            r4 = client.post("/", json={**answers, "feelings_text": ""},
                             headers={"X-CSRF-Token": csrf})
            j4 = r4.get_json()["jobId"]
            dns_app.wait_for_job(j4, timeout=5.0)
            self.assertEqual(client.get(f"/checkin/status/{j4}").status_code, 200)
            self.assertEqual(len(DataManager(path).load()), 3)
            dns_app.close()

    def test_status_poll_idempotent_nan_wait_and_global_job_cap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            logic = LogicManager()
            answers = sample_answers()
            good = matching_gemini_reply(answers, logic)
            fake = FakeProvider(good)
            dns_app, web = wired_app(
                test_config={"TESTING": True, "SECRET_KEY": "test-secret"},
                provider=fake,
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            client = web.flask.test_client()
            client.get("/")
            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]
            sent = client.post("/", json={**answers, "feelings_text": ""},
                               headers={"X-CSRF-Token": csrf})
            job_id = sent.get_json()["jobId"]
            dns_app.wait_for_job(job_id, timeout=5.0)

            first_poll = client.get(f"/checkin/status/{job_id}?wait=nan")
            self.assertEqual(first_poll.status_code, 200)
            second_poll = client.get(f"/checkin/status/{job_id}")
            self.assertEqual(second_poll.status_code, 200)
            self.assertTrue(second_poll.get_json()["ok"])
            with client.session_transaction() as sess:
                owner_id = str(sess.get("owner_id") or "")
            dns_app.forget_job(job_id, owner_id)
            after_forget = client.get(f"/checkin/status/{job_id}")
            self.assertEqual(after_forget.status_code, 404)
            dns_app.close()

        with tempfile.TemporaryDirectory() as tmp:
            gate = threading.Event()
            logic = LogicManager()
            good = matching_gemini_reply(sample_answers(), logic)

            def blocked_reply(prompt: str, model: str) -> str:
                gate.wait(timeout=2.0)
                return good

            dns_app = App(
                provider=FakeProvider(blocked_reply),
                data_path=Path(tmp) / "cap.json",
                testing=True,
            )
            try:
                queued: list[str] = []
                for idx in range(dns_app.MAX_ACTIVE_JOBS):
                    res = dns_app.submit_checkin(
                        sample_answers(student_id=f"26055{idx:02d}"),
                        f"owner-{idx}",
                    )
                    self.assertEqual(res["status"], "queued")
                    queued.append(str(res["job_id"]))
                capped = dns_app.submit_checkin(sample_answers(), "owner-extra")
                self.assertEqual(capped["status"], "busy")
            finally:
                gate.set()
                for job_id in queued:
                    dns_app.wait_for_job(job_id, timeout=5.0)
                dns_app.close()

    def test_security_csrf_admin_throttle_and_payload_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            admin_hash = generate_password_hash("TestAdminPass!")
            dns_app, web = wired_app(
                test_config={
                    "TESTING": True,
                    "SECRET_KEY": "test-secret",
                    "ADMIN_PASSWORD_HASH": admin_hash,
                },
                provider=FakeProvider(),
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            client = web.flask.test_client()
            client.get("/")
            no_csrf = client.post("/", json=sample_answers())
            self.assertEqual(no_csrf.status_code, 403)

            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]
            too_big = client.post(
                "/",
                data="x" * (dns_app.MAX_CONTENT_LENGTH + 1024),
                content_type="application/json",
                headers={"X-CSRF-Token": csrf},
            )
            self.assertEqual(too_big.status_code, 413)

            client.get("/admin/login")
            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]
            for _ in range(web.ADMIN_MAX_ATTEMPTS):
                attempt = client.post(
                    "/admin/login",
                    data={"username": "admin", "password": "wrong",
                          "csrf_token": csrf},
                )
                self.assertEqual(attempt.status_code, 401)
            throttled = client.post(
                "/admin/login",
                data={"username": "admin", "password": "wrong",
                      "csrf_token": csrf},
            )
            self.assertEqual(throttled.status_code, 429)
            dns_app.close()

    def test_cross_layer_tier_constants_agree(self) -> None:
        from ai_manager import RISK_CATEGORIES, SOFT_LABELS, SPEAK_PROMINENCE
        from data_manager import DataManager
        from io_manager import (
            CATEGORY_LABELS as IO_CATEGORY_LABELS,
            SOFT_LABEL_COPY,
            SPEAK_PANEL_COPY,
        )
        from logic.decision import TIERS
        from records.check_in_record import CheckInRecord

        tiers = tuple(TIERS.keys())
        self.assertEqual(tiers, RISK_CATEGORIES)
        self.assertEqual(tiers, CheckInRecord.CATEGORIES)
        self.assertEqual(
            DataManager.TIER_TO_CATEGORY,
            {label: tier for tier, label in CATEGORY_LABELS.items()},
        )
        self.assertEqual(tuple(CATEGORY_LABELS.keys()), tiers)
        self.assertEqual(tuple(CATEGORY_PROMINENCE.keys()), tiers)
        self.assertEqual(CATEGORY_LABELS, IO_CATEGORY_LABELS)
        self.assertEqual(tuple(CATEGORY_LABELS.values()), SOFT_LABELS)
        self.assertEqual(tuple(SOFT_LABEL_COPY.keys()), SOFT_LABELS)
        self.assertEqual(tuple(CATEGORY_PROMINENCE.values()), SPEAK_PROMINENCE)
        self.assertEqual(tuple(SPEAK_PANEL_COPY.keys()), SPEAK_PROMINENCE)
        for tier in tiers:
            self.assertEqual(
                TIERS[tier], (CATEGORY_LABELS[tier], CATEGORY_PROMINENCE[tier]))

        logic_tree = ast.parse(
            (APP_ROOT / "logic_manager.py").read_text(encoding="utf-8"))
        for node in logic_tree.body:
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                if node.target.id in ("CATEGORY_LABELS", "CATEGORY_PROMINENCE"):
                    self.assertIsInstance(node.value, ast.Dict)
            self.assertFalse(
                any(isinstance(child, (ast.DictComp, ast.ListComp, ast.SetComp))
                    for child in ast.walk(node)
                    if isinstance(node, (ast.Assign, ast.AnnAssign))))

    def test_deep_copy_isolation_on_init_and_evaluate(self) -> None:
        from logic.decision import Decision
        from records.check_in_record import CheckInRecord

        answers = sample_answers()
        reply = json.loads(matching_gemini_reply(answers))
        rec_input: JSONObject = {
            "record_id": "rec_copy_1",
            **answers,
            **reply,
        }
        rec = CheckInRecord(rec_input)
        rec_input["primary_stressors"].append("mutated_stressor")  # type: ignore[union-attr]
        rec_input["scored_items"]["pss_1"] = 99  # type: ignore[index]
        self.assertEqual(rec.to_row()["primary_stressors"], ["academic_overload"])
        self.assertNotEqual(rec.get("scored_items")["pss_1"], 99)  # type: ignore[index]

        dec_input: JSONObject = {**answers, **json.loads(matching_gemini_reply(answers))}
        decision = Decision(dec_input, {"low_sleep": True})
        dec_input["tips"].append("mutated_tip")  # type: ignore[union-attr]
        dec_input["primary_stressors"].append("mutated_stressor")  # type: ignore[union-attr]
        self.assertNotIn("mutated_tip", decision.gemini_tips)
        self.assertEqual(decision.field("primary_stressors"), ["academic_overload"])

        eval_input: JSONObject = {**answers, **json.loads(matching_gemini_reply(answers))}
        evaluated = LogicManager().evaluate(eval_input)
        self.assertTrue(evaluated["ok"])
        eval_input["primary_stressors"].append("leaked_stressor")  # type: ignore[union-attr]
        eval_input["tips"].append("leaked_tip")  # type: ignore[union-attr]
        eval_input["scored_items"]["pss_1"] = 99  # type: ignore[index]
        self.assertNotIn("leaked_stressor", evaluated["primary_stressors"])  # type: ignore[operator]
        self.assertNotIn("leaked_tip", evaluated["tips"])  # type: ignore[operator]
        self.assertNotEqual(evaluated["scored_items"]["pss_1"], 99)  # type: ignore[index]

    def test_logic_manager_evaluate_rejects_invalid_tier_confidence_and_reasoning(self) -> None:
        answers = sample_answers()
        scorer = LogicManager()
        bad_cases: list[dict[str, object]] = [
            {"risk_category": "Unknown"},
            {"risk_category": ["unhashable"]},
            {"soft_label": "Invalid label"},
            {"speak_prominence": "urgent"},
            {"confidence": 1.5},
            {"confidence": -0.1},
            {"confidence": True},
            {"reasoning": "   "},
            {
                "risk_category": "Low",
                "soft_label": CATEGORY_LABELS["Low"],
                "speak_prominence": CATEGORY_PROMINENCE["Low"],
            },
            {"soft_label": CATEGORY_LABELS["High"]},
            {"speak_prominence": CATEGORY_PROMINENCE["High"]},
        ]
        for overrides in bad_cases:
            with self.subTest(overrides=overrides):
                payload: JSONObject = {
                    **answers,
                    **json.loads(matching_gemini_reply(answers)),
                    **overrides,  # type: ignore[arg-type]
                }
                result = scorer.evaluate(payload)
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], LogicManager.ERROR_AI_FIELDS_REQUIRED)

        with self.assertRaises(ValueError):
            LogicManager(answer_keys=())

    def test_logic_manager_trend_ignores_out_of_range_scores(self) -> None:
        scorer = LogicManager()
        from_scores = scorer.trend({"scores": [2.0, -2.0, 8.5, 4.0]})
        self.assertEqual(from_scores["count"], 2)
        self.assertEqual(from_scores["average"], 3.0)
        self.assertEqual(from_scores["latest"], 4.0)
        self.assertEqual(from_scores["previous"], 2.0)

        from_rows = scorer.trend([
            {"stress_score": 2.0},
            {"stress_score": 9.0},
            {"stress_score": -1.0},
            {"stress_score": 4.0},
        ])
        self.assertEqual(from_rows["count"], 2)
        self.assertEqual(from_rows["average"], 3.0)
        self.assertEqual(from_rows["change"], 2.0)

    def test_stale_pending_record_id_does_not_overwrite_completed_record(self) -> None:
        answers = sample_answers()
        provider = FakeProvider(RuntimeError("down"))
        with tempfile.TemporaryDirectory() as tmp:
            dns_app, _ = wired_app(
                provider=provider,
                data_path=Path(tmp) / "records.json",
                secret_key="test-secret",
                ai_retry_delay_sec=0.0,
            )
            first = dns_app.run_checkin(dict(answers), owner="owner_1")
            self.assertEqual(first["status"], "pending")
            rec_1 = str(first["pending_id"])

            provider.reply_with(matching_gemini_reply(answers))
            upgraded_1 = dns_app.run_checkin(
                dict(answers), owner="owner_1",
                pending_fingerprint=str(first["fingerprint"]),
                pending_record_id=rec_1)
            self.assertEqual(upgraded_1["status"], "completed")

            provider.reply_with(RuntimeError("down"))
            second = dns_app.run_checkin(dict(answers), owner="owner_1")
            self.assertEqual(second["status"], "pending")
            rec_2 = str(second["pending_id"])
            self.assertNotEqual(rec_1, rec_2)

            provider.reply_with(matching_gemini_reply(answers))
            upgraded_2 = dns_app.run_checkin(
                dict(answers), owner="owner_1",
                pending_fingerprint=str(second["fingerprint"]),
                pending_record_id=rec_2)
            self.assertEqual(upgraded_2["status"], "completed")

            replay = dns_app.run_checkin(
                dict(answers), owner="owner_1",
                pending_fingerprint=str(first["fingerprint"]),
                pending_record_id=rec_1)
            self.assertEqual(replay["status"], "completed")
            self.assertEqual(dns_app.admin_records("", "", "")["total"], 3)

            # Even after __submissions expires / restarts, replaying rec_1 must not
            # overwrite the completed row on disk or duplicate its record_id.
            dns_app.forget_submission("owner_1")
            replay_after_expiry = dns_app.run_checkin(
                dict(answers), owner="owner_1",
                pending_fingerprint=str(first["fingerprint"]),
                pending_record_id=rec_1)
            self.assertEqual(replay_after_expiry["status"], "completed")
            self.assertEqual(dns_app.admin_records("", "", "")["total"], 4)
            stored_rows = JSONStorage(Path(tmp) / "records.json").load()
            stored_ids = [str(row["record_id"]) for row in stored_rows]
            self.assertEqual(len(stored_ids), 4)
            self.assertEqual(len(set(stored_ids)), 4)
            self.assertIn(rec_1, stored_ids)

            # Replaying a stale rec_1 after expiry when AI is down must create a
            # fresh pending row instead of marking completed rec_1 pending.
            dns_app.forget_submission("owner_1")
            provider.reply_with(RuntimeError("down"))
            failed_replay = dns_app.run_checkin(
                dict(answers), owner="owner_1",
                pending_fingerprint=str(first["fingerprint"]),
                pending_record_id=rec_1)
            self.assertEqual(failed_replay["status"], "pending")
            self.assertTrue(failed_replay["saved"])
            new_pending_id = str(failed_replay["pending_id"])
            self.assertNotEqual(new_pending_id, rec_1)
            stored_rows = JSONStorage(Path(tmp) / "records.json").load()
            stored_ids = [str(row["record_id"]) for row in stored_rows]
            self.assertEqual(len(stored_ids), 5)
            self.assertEqual(len(set(stored_ids)), 5)
            by_id = {str(row["record_id"]): row for row in stored_rows}
            self.assertIsNone(by_id[rec_1].get("status"))
            self.assertTrue(by_id[rec_1].get("ai_ok"))
            self.assertEqual(by_id[new_pending_id]["status"], "pending")
            loaded = {r.record_id: r for r in DataManager(Path(tmp) / "records.json").load()}
            self.assertEqual(loaded[rec_1].status, "evaluated")
            self.assertEqual(loaded[new_pending_id].status, "pending")
            dns_app.close()

    def test_gemini_provider_reads_gemini_model_env_fallback(self) -> None:
        import os
        from unittest import mock

        from ai.gemini_provider import GeminiProvider

        with mock.patch.dict(
            os.environ, {"GEMINI_MODEL": "gemini-2.5-pro"}, clear=False
        ):
            provider = GeminiProvider(api_key="test-key")
        self.assertEqual(provider.models[0], "gemini-2.5-pro")

    def test_display_history_ignores_blank_category_and_sanitizes_pending_count(self) -> None:
        io = IOManager(Questionnaire.from_survey())
        with_blank_tail = io.display_history(
            {
                "student_id": "2605581",
                "records": [
                    {"risk_category": "High", "soft_label": "Please reach out", "stress_score": 4.2},
                    {"risk_category": "", "soft_label": "", "stress_score": None},
                ],
                "pending_count": True,
            },
            {"comparison": "higher", "direction": "steady", "change": 0.1},
        )
        self.assertIsNotNone(with_blank_tail["advisor"])
        self.assertEqual(with_blank_tail["pending"], 0)

        with_low_tail = io.display_history(
            {
                "student_id": "2605581",
                "records": [
                    {"risk_category": "High", "soft_label": "Please reach out", "stress_score": 4.2},
                    {"risk_category": "Low", "soft_label": "You're doing ok", "stress_score": 1.8},
                ],
                "pending_count": -3,
            },
            {"comparison": "lower", "direction": "improving", "change": -2.4},
        )
        self.assertIsNone(with_low_tail["advisor"])
        self.assertEqual(with_low_tail["pending"], 0)

    def test_retry_pending_checkin_persists_updated_safety_flag_on_failure(self) -> None:
        provider = FakeProvider(RuntimeError("down"))
        with tempfile.TemporaryDirectory() as tmp:
            dns_app, _ = wired_app(
                provider=provider,
                data_path=Path(tmp) / "records.json",
                secret_key="test-secret",
                ai_retry_delay_sec=0.0,
            )
            first = dns_app.run_checkin(
                sample_answers(safety_flag=False), owner="owner_1")
            self.assertEqual(first["status"], "pending")
            self.assertTrue(first["saved"])
            rec_1 = str(first["pending_id"])

            retry = dns_app.run_checkin(
                sample_answers(safety_flag=True),
                owner="owner_1",
                pending_fingerprint=str(first["fingerprint"]),
                pending_record_id=rec_1,
            )
            self.assertEqual(retry["status"], "pending")
            self.assertTrue(retry["saved"])
            self.assertEqual(retry["pending_id"], rec_1)
            stored_rows = JSONStorage(Path(tmp) / "records.json").load()
            self.assertEqual(len(stored_rows), 1)
            self.assertEqual(stored_rows[0]["record_id"], rec_1)
            self.assertEqual(stored_rows[0]["status"], "pending")
            self.assertTrue(stored_rows[0]["safety_flag"])
            dns_app.close()

    def test_oversized_admin_password_hashes_dummy_value_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            admin_hash = generate_password_hash("TestAdminPass!")
            dns_app, web = wired_app(
                test_config={
                    "TESTING": True,
                    "SECRET_KEY": "test-secret",
                    "ADMIN_PASSWORD_HASH": admin_hash,
                },
                provider=FakeProvider(),
                data_path=Path(tmp) / "records.json",
                testing=True,
            )
            client = web.flask.test_client()
            client.get("/admin/login")
            with client.session_transaction() as sess:
                csrf = sess["csrf_token"]
            real_check = web_controller.check_password_hash
            oversized = "x" * (WebController.ADMIN_MAX_PASSWORD_LENGTH + 10)
            with patch("web_controller.check_password_hash",
                       wraps=real_check) as check_spy:
                resp = client.post(
                    "/admin/login",
                    data={
                        "username": WebController.ADMIN_USERNAME,
                        "password": oversized,
                        "csrf_token": csrf,
                    },
                )
            self.assertEqual(resp.status_code, 401)
            self.assertGreaterEqual(check_spy.call_count, 1)
            for call in check_spy.call_args_list:
                self.assertEqual(call.args[1], "x")
            dns_app.close()

    def test_mapping_proxies_and_pending_saved_at_preserved(self) -> None:
        with self.assertRaises(TypeError):
            DataManager.TIER_TO_CATEGORY["extra"] = "Low"  # type: ignore[index]
        with self.assertRaises(TypeError):
            WebController.STATUS_CODES["extra"] = 200  # type: ignore[index]

        with tempfile.TemporaryDirectory() as tmp:
            provider = FakeProvider()
            provider.reply_with(RuntimeError("down"))
            dns_app, _web = wired_app(
                provider=provider, data_path=Path(tmp) / "records.json"
            )
            answers = sample_answers()
            first = dns_app.run_checkin(dict(answers), owner="owner_1")
            self.assertEqual(first["status"], "pending")
            rec_id = str(first["pending_id"])
            storage = JSONStorage(Path(tmp) / "records.json")
            initial_saved_at = str(storage.load()[0]["saved_at"])

            with patch("data_manager.datetime") as mock_dt:
                mock_dt.now.return_value.isoformat.return_value = (
                    "2099-01-01T00:00:00+00:00"
                )
                retried = dns_app.run_checkin(
                    dict(answers),
                    owner="owner_1",
                    pending_fingerprint=str(first["fingerprint"]),
                    pending_record_id=rec_id,
                )
                self.assertEqual(retried["status"], "pending")
                self.assertEqual(
                    storage.load()[0]["saved_at"], initial_saved_at
                )

                provider.reply_with(matching_gemini_reply(answers))
                upgraded = dns_app.run_checkin(
                    dict(answers),
                    owner="owner_1",
                    pending_fingerprint=str(first["fingerprint"]),
                    pending_record_id=rec_id,
                )
                self.assertEqual(upgraded["status"], "completed")
                rows = storage.load()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["record_id"], rec_id)
                self.assertNotIn("status", rows[0])
                self.assertEqual(rows[0]["risk_category"], "Moderate")
                self.assertEqual(rows[0]["saved_at"], initial_saved_at)
            dns_app.close()

    def test_delivered_job_ttl_and_forget_submission_cleanup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            answers = sample_answers()
            provider = FakeProvider()
            provider.reply_with(matching_gemini_reply(answers))
            dns_app, _web = wired_app(
                provider=provider, data_path=Path(tmp) / "records.json"
            )
            queued = dns_app.submit_checkin(dict(answers), owner="owner_1")
            job_id = str(queued["job_id"])
            first_poll = dns_app.job_status(job_id, "owner_1", wait=2.0)
            self.assertEqual(first_poll["status"], "completed")

            dns_app.expire_jobs()
            second_poll = dns_app.job_status(job_id, "owner_1")
            self.assertEqual(second_poll["status"], "completed")

            later = time.monotonic() + App.DELIVERED_TTL_SECONDS + 5.0
            with patch("main.time.monotonic", return_value=later):
                dns_app.expire_jobs()
            expired_poll = dns_app.job_status(job_id, "owner_1")
            self.assertEqual(expired_poll["status"], "not_found")

            answers_2 = sample_answers(pss_1=5)
            provider.reply_with(matching_gemini_reply(answers_2))
            queued_2 = dns_app.submit_checkin(dict(answers_2), owner="owner_1")
            job_id_2 = str(queued_2["job_id"])
            done_2 = dns_app.job_status(job_id_2, "owner_1", wait=2.0)
            self.assertEqual(done_2["status"], "completed")
            dns_app.forget_submission("owner_1")
            self.assertEqual(
                dns_app.job_status(job_id_2, "owner_1")["status"], "not_found"
            )
            dns_app.close()

    def test_logic_tier_problems_and_non_mapping_form(self) -> None:
        logic = LogicManager()
        answers = sample_answers()
        valid = json.loads(matching_gemini_reply(answers))
        bad_verify = dict(valid)
        bad_verify["soft_label"] = "You're doing ok"
        problem = logic.verify(bad_verify, answers)
        self.assertIsNotNone(problem)
        self.assertIn("soft_label", str(problem))

        bad_record = {**answers, **valid}
        bad_record["risk_category"] = "Low"
        bad_record["soft_label"] = CATEGORY_LABELS["Moderate"]
        bad_record["speak_prominence"] = CATEGORY_PROMINENCE["High"]
        evaluated = logic.evaluate(bad_record)
        self.assertFalse(evaluated["ok"])
        self.assertEqual(
            evaluated["invalid"],
            ["risk_category", "speak_prominence"],
        )

        with tempfile.TemporaryDirectory() as tmp:
            dns_app, _web = wired_app(
                provider=FakeProvider(), data_path=Path(tmp) / "records.json"
            )
            checked = dns_app.validate_form(["not", "a", "mapping"])  # type: ignore[arg-type]
            self.assertFalse(checked["ok"])
            dns_app.close()


if __name__ == "__main__":
    unittest.main()
