"""Questionnaire: the evidence-v3 question wording, scales and answer checks.

Source: donotstress_question_evidence.docx, 9 October 2026, section 2.
Every question uses one 1-5 scale except typical sleep, which stays a
0-14 hour slider (half-hour steps) and is converted to 1-5 only when
scoring. logic_manager owns scoring, context flags and factor cards.
Items are adapted from their source instruments, so results are NOT
PSS-4, PSQI, IFDFW or MSPSS scores. Positively worded items (reverse=True)
are scored as 6 - answer, so a higher scored value always means more
stress. Never convert legacy /10 or evidence-v2 records onto this scale.
"""

from __future__ import annotations

import math
from typing import Any, ClassVar

from .safety_check import SafetyCheck


class Questionnaire:
    """The 11 scored questions, the chapter sections and answer validation.

    The wording is class-level data because there is exactly one
    questionnaire version per release: other classes read
    ``Questionnaire.QUESTIONS`` or ``Questionnaire.QUESTION_MAP`` directly.
    The browser receives the same definitions through ``public_config()``.
    """

    VERSION: ClassVar[str] = "evidence-v3"
    SCALE_MIN: ClassVar[int] = 1
    SCALE_MAX: ClassVar[int] = 5
    PSS_OPTIONS: ClassVar[list[str]] = ["Never", "Almost never", "Sometimes", "Fairly often", "Very often"]
    SLEEP_OPTIONS: ClassVar[list[str]] = ["Very good", "Fairly good", "Okay", "Fairly bad", "Very bad"]
    AGREE_OPTIONS: ClassVar[list[str]] = ["Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree"]
    FIN_OPTIONS: ClassVar[list[str]] = [
        "No stress at all", "A little stress", "Moderate stress", "High stress", "Overwhelming stress",
    ]

    QUESTIONS: ClassVar[list[dict[str, Any]]] = [
        {"key": "pss_1", "label": "Losing control",
         "prompt": "In the past month, how often have you felt you couldn't control the important things in your life?",
         "min": 1, "max": 5, "step": 1, "options": PSS_OPTIONS},
        {"key": "pss_2", "label": "Handling personal problems",
         "prompt": "In the past month, how often have you felt confident handling your personal problems?",
         "min": 1, "max": 5, "step": 1, "options": PSS_OPTIONS, "reverse": True},
        {"key": "pss_3", "label": "Things going your way",
         "prompt": "In the past month, how often have you felt things were going well for you?",
         "min": 1, "max": 5, "step": 1, "options": PSS_OPTIONS, "reverse": True},
        {"key": "pss_4", "label": "Difficulties piling up",
         "prompt": "In the past month, how often have you felt problems were piling up too much to handle?",
         "min": 1, "max": 5, "step": 1, "options": PSS_OPTIONS},
        {"key": "sleep_hours_avg", "label": "Typical sleep · past week",
         "prompt": "On average, how many hours of sleep have you gotten each night this week?",
         "min": 0, "max": 14, "step": 0.5, "options": None, "kind": "slider", "default": 7,
         "low": "0 hours", "high": "14 hours", "unit": "hours"},
        {"key": "sleep_quality", "label": "Sleep quality · past week",
         "prompt": "During the past week, how would you rate your sleep quality overall?",
         "min": 1, "max": 5, "step": 1, "options": SLEEP_OPTIONS},
        {"key": "pas_workload", "label": "Study workload",
         "prompt": "I feel my coursework is too much to handle.",
         "min": 1, "max": 5, "step": 1, "options": AGREE_OPTIONS},
        {"key": "pas_catchup", "label": "Catching up",
         "prompt": "When I fall behind on my work, I find it hard to catch up.",
         "min": 1, "max": 5, "step": 1, "options": AGREE_OPTIONS},
        {"key": "fin_stress", "label": "Personal finances",
         "prompt": "How stressed do you feel about your personal finances in general?",
         "min": 1, "max": 5, "step": 1, "options": FIN_OPTIONS, "kind": "slider", "default": 3,
         "low": "No stress at all", "high": "Overwhelming stress", "unit": "out of 5"},
        {"key": "mspss_friends", "label": "Support from friends",
         "prompt": "I can count on my friends when things go wrong.",
         "min": 1, "max": 5, "step": 1, "options": AGREE_OPTIONS, "reverse": True},
        {"key": "mspss_family", "label": "Support from family",
         "prompt": "I get the emotional help and support I need from my family.",
         "min": 1, "max": 5, "step": 1, "options": AGREE_OPTIONS, "reverse": True},
    ]
    QUESTION_MAP: ClassVar[dict[str, dict[str, Any]]] = {q["key"]: q for q in QUESTIONS}
    # Positively worded items: a high answer means LESS stress, so they are scored as 6 - answer.
    REVERSED_KEYS: ClassVar[tuple[str, ...]] = tuple(q["key"] for q in QUESTIONS if q.get("reverse"))

    SECTIONS: ClassVar[list[dict[str, Any]]] = [
        {"title": "Your month", "heading": "Start with the bigger picture.",
         "period": "Think about the last month",
         "intro": "Notice how manageable life has felt, including moments when things went well. "
                  "Choose how often each experience happened.",
         "why": "These four questions explore perceived stress: how unpredictable, difficult to control, "
                "or overwhelming life has felt. Together they give more context than one stress rating.",
         "keys": ["pss_1", "pss_2", "pss_3", "pss_4"]},
        {"title": "Rest & recovery", "heading": "How has your sleep been?",
         "period": "Think about the past week",
         "intro": "Now zoom in on your recent routine. Think about a typical night, rather than only last night.",
         "why": "Sleep and stress can affect one another. Hours and quality capture different parts of rest; "
                "either can help explain why daily demands feel harder to manage.",
         "keys": ["sleep_hours_avg", "sleep_quality"]},
        {"title": "Study demands", "heading": "Make room for your study load.",
         "period": "Your current study experience",
         "intro": "With your overall feelings and rest in mind, consider the demands of your coursework.",
         "why": "Feeling overloaded by assignments can add pressure and reduce time for recovery. "
                "This question identifies a possible source of strain, rather than judging your academic performance.",
         "keys": ["pas_workload", "pas_catchup"]},
        {"title": "Money pressures", "heading": "Life outside the timetable.",
         "period": "Your personal finances in general",
         "intro": "Everyday expenses can take up mental space too. You do not need to share amounts or financial details.",
         "why": "Financial worries may compete for attention alongside study demands. This question helps us "
                "suggest relevant support without assuming your income or circumstances.",
         "keys": ["fin_stress"]},
        {"title": "Your support", "heading": "Who can you lean on?",
         "period": "The support available to you",
         "intro": "After looking at pressures, consider the people who help you face them. "
                  "Friends and family may support you in different ways.",
         "why": "Support can make stressful experiences easier to navigate. These questions look at sources "
                "of support; they do not cancel out or invalidate the stress you reported.",
         "keys": ["mspss_friends", "mspss_family"]},
        {"title": "A moment to reflect", "heading": "Anything else on your mind?",
         "period": "Optional · not scored",
         "intro": "Numbers cannot capture everything. You can reflect here, or continue without writing anything.",
         "why": "Your reflection does not contribute to the stress score. A basic safety check can highlight "
                "support, but it cannot recognise every situation. You can contact support at any time.",
         "keys": []},
    ]

    @staticmethod
    def validate_answer(raw: Any, question: dict[str, Any]) -> tuple[bool, Any]:
        """Check one raw answer against its question.

        Returns ``(True, value)`` with the value as an int (or a float for the
        half-hour sleep slider), or ``(False, message)`` for the student.
        """
        if raw is None or str(raw).strip() == "":
            return (True, None) if question.get("optional") else (False, "Please answer this question.")
        if isinstance(raw, (bool, list, dict)):
            return False, "Choose one of the available answers."
        try:
            value = float(raw)
        except (ValueError, TypeError, OverflowError):
            return False, "Choose a number in the available range."
        if (not math.isfinite(value) or not question["min"] <= value <= question["max"]
                or not (value / question["step"]).is_integer()):
            return False, f"Choose {question['min']} to {question['max']} in steps of {question['step']}."
        return True, value if question["step"] == 0.5 else int(value)

    @classmethod
    def public_config(cls) -> dict[str, Any]:
        """Everything the browser needs to draw the check-in (no secrets)."""
        return {
            "version": cls.VERSION,
            "questions": cls.QUESTIONS,
            "sections": cls.SECTIONS,
            "safetyPatterns": SafetyCheck.PATTERNS,
        }
