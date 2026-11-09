"""Questionnaire and safety-check tests."""

from __future__ import annotations

import unittest

from ai_manager import AIResponseSchema
from logic_manager import ScoringPolicy, StudentAnswers
from survey import Questionnaire, SafetyCheck


class QuestionnaireTests(unittest.TestCase):
    def test_eleven_questions_shared_by_every_manager(self):
        keys = tuple(Questionnaire.QUESTION_MAP)
        self.assertEqual(len(keys), 11)
        self.assertEqual(keys, StudentAnswers.KEYS)
        self.assertEqual(keys, AIResponseSchema.RAW_ANSWER_KEYS)

    def test_reverse_scored_items_match_the_scoring_policy(self):
        self.assertEqual(Questionnaire.REVERSED_KEYS, ScoringPolicy().reversed_keys)

    def test_sections_cover_every_question_once(self):
        listed = [key for section in Questionnaire.SECTIONS for key in section["keys"]]
        self.assertEqual(sorted(listed), sorted(Questionnaire.QUESTION_MAP))

    def test_answer_validation(self):
        sleep = Questionnaire.QUESTION_MAP["sleep_hours_avg"]
        likert = Questionnaire.QUESTION_MAP["pss_1"]
        self.assertEqual(Questionnaire.validate_answer("7.5", sleep), (True, 7.5))
        self.assertEqual(Questionnaire.validate_answer("4", likert), (True, 4))
        for bad, question in (("7.25", sleep), ("15", sleep), ("0", likert), (True, likert), ("", likert), ("x", likert)):
            with self.subTest(value=bad):
                self.assertFalse(Questionnaire.validate_answer(bad, question)[0])

    def test_browser_config(self):
        config = Questionnaire.public_config()
        self.assertEqual(config["version"], "evidence-v3")
        self.assertEqual(len(config["questions"]), 11)
        self.assertEqual(config["safetyPatterns"], SafetyCheck.PATTERNS)


class SafetyCheckTests(unittest.TestCase):
    def test_crisis_language_is_flagged(self):
        check = SafetyCheck()
        for text in ("I want to die", "thinking about self-harm", "I don’t want to live", "better off dead"):
            with self.subTest(text=text):
                self.assertTrue(check.is_flagged(text))

    def test_ordinary_text_is_not_flagged(self):
        check = SafetyCheck()
        for text in ("", None, "exams are killing me lol", "I am tired but okay"):
            with self.subTest(text=text):
                self.assertFalse(check.is_flagged(text))


if __name__ == "__main__":
    unittest.main()
