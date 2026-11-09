"""Pipeline and advanced-feature tests: the check-in pipeline and the background worker thread."""

from __future__ import annotations

import threading
import unittest

from ai_manager import AIManagerInterface, AIProcessingError
from checkin_pipeline import CheckinPipeline
from checkin_worker import CheckinWorker
from desktop_palette import DesktopPalette
from doubles import InMemoryRecordRepository, MockAIManager
from logic_manager import AIScoreVerifier, LogicManager, ScoreCalculator
from sample_ai_records import LOW_STRESS_REPLY, LOW_STRESS_STUDENT


class FailingAI(AIManagerInterface):
    def analyse(self, student):
        raise AIProcessingError("timeout", "slow")


class BlockingAI(AIManagerInterface):
    """Waits until the test releases it, to prove the caller is not blocked."""

    def __init__(self, inner):
        self.release = threading.Event()
        self.inner = inner

    def analyse(self, student):
        self.release.wait(timeout=5)
        return self.inner.analyse(student)


class CheckinPipelineTests(unittest.TestCase):
    def setUp(self):
        self.logic = LogicManager(calculator=ScoreCalculator())
        self.verifier = AIScoreVerifier(ScoreCalculator())

    def test_success_returns_the_evaluated_record(self):
        ok, record = CheckinPipeline(MockAIManager(LOW_STRESS_REPLY, self.verifier), self.logic).process(LOW_STRESS_STUDENT)
        self.assertTrue(ok)
        self.assertEqual((record["risk_category"], record["source"]), ("Low", "ai_logic"))

    def test_ai_failure_returns_its_code(self):
        self.assertEqual(CheckinPipeline(FailingAI(), self.logic).process(LOW_STRESS_STUDENT), (False, "timeout"))

    def test_logic_rejection_is_reported_as_unavailable(self):
        wrong = MockAIManager({**LOW_STRESS_REPLY, "stress_score": 1.5})  # no verifier, so Logic catches it
        self.assertEqual(CheckinPipeline(wrong, self.logic).process(LOW_STRESS_STUDENT), (False, "unavailable"))


class CheckinWorkerTests(unittest.TestCase):
    def setUp(self):
        self.store = InMemoryRecordRepository()
        self.logic = LogicManager()
        self.ai = MockAIManager(LOW_STRESS_REPLY, AIScoreVerifier(ScoreCalculator()))

    def test_runs_in_the_background_and_saves_the_result(self):
        blocking = BlockingAI(self.ai)
        worker = CheckinWorker(CheckinPipeline(blocking, self.logic), self.store)
        worker.start({**LOW_STRESS_STUDENT, "feelings_text": "private"})
        self.assertTrue(worker.busy)          # start() returned while the AI is still "working"
        self.assertIsNone(worker.poll())
        with self.assertRaises(RuntimeError):  # one check-in at a time
            worker.start(LOW_STRESS_STUDENT)
        blocking.release.set()
        ok, record = worker.wait(timeout=5)
        self.assertTrue(ok)
        self.assertEqual(record["record_id"], self.store.load()[0]["record_id"])
        self.assertNotIn("feelings_text", self.store.load()[0])

    def test_ai_failure_saves_a_pending_row(self):
        worker = CheckinWorker(CheckinPipeline(FailingAI(), self.logic), self.store)
        worker.start(LOW_STRESS_STUDENT)
        self.assertEqual(worker.wait(timeout=5), (False, "timeout"))
        self.assertEqual(self.store.load()[0]["status"], "pending")

    def test_unexpected_errors_do_not_kill_the_worker(self):
        class Broken(AIManagerInterface):
            def analyse(self, student):
                raise ZeroDivisionError

        worker = CheckinWorker(CheckinPipeline(Broken(), self.logic), self.store)
        self.assertEqual(worker.run(LOW_STRESS_STUDENT), (False, "unavailable"))


class DesktopPaletteTests(unittest.TestCase):
    def test_toggle_and_tier_colours(self):
        light = DesktopPalette()
        dark = light.toggled()
        self.assertEqual((light.name, dark.name, dark.toggled().name), ("light", "dark", "light"))
        self.assertNotEqual(light.bg, dark.bg)
        self.assertEqual(light.tier_color("High"), light.high)
        self.assertEqual(light.tier_color("unknown"), light.soft)
        with self.assertRaises(ValueError):
            DesktopPalette("neon")


if __name__ == "__main__":
    unittest.main()
