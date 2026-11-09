"""StudentIO: the I/O Manager. Validates input and formats every student-facing message."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, ClassVar

from .student_form_validator import StudentFormValidator


class StudentIO:
    """Input validation and student-facing wording for the web and desktop apps.

    All wording lives here so the other managers return only codes and IDs
    (tip IDs, soft labels, error codes) and never write text for students.
    The form checks are delegated to a StudentFormValidator that this
    manager creates and owns (composition).
    """

    SOFT_LABEL_COPY: ClassVar[dict[str, dict[str, str]]] = {
        "You're doing ok": {
            "label": "You're doing ok",
            "heading": "You're doing ok",
            "body": "Your check-in looks steady. Keep looking after yourself.",
            "tone": "reassuring",
        },
        "Worth a check-in": {
            "label": "Worth a check-in",
            "heading": "Worth a check-in",
            "body": "Some things look a bit heavier right now. A conversation could help.",
            "tone": "supportive",
        },
        "Please reach out": {
            "label": "Please reach out",
            "heading": "Please reach out",
            "body": "Please reach out for support. You do not have to handle this on your own.",
            "tone": "urgent",
        },
    }
    DEFAULT_SOFT_LABEL: ClassVar[str] = "Worth a check-in"

    TIPS_ALLOWLIST: ClassVar[dict[str, str]] = {
        "sleep_routine": "Try to keep a regular sleep schedule, including on weekends.",
        "rest_a_little_more": "If you can, give yourself a bit more rest — even 30 extra minutes can help.",
        "short_breaks": "Take short, planned breaks between study blocks instead of pushing through without a pause.",
        "workload_chunks": "Break larger assignments into smaller tasks and spread them across the week.",
        "money_worries": "If money is on your mind, campus support can help you find the right next step.",
        "talk_to_someone": "Reach out to a friend, classmate, or family member — you do not have to handle this alone.",
        "keep_social_contact": "Stay in touch with people who help you feel supported, even with a short check-in.",
    }
    TIPS_HEADING: ClassVar[str] = "A few ideas that might help"

    ADVISOR_CONTACTS: ClassVar[dict[str, str]] = {
        "email": "SITCounselling@SingaporeTech.edu.sg",
        "helpline": "6592 2030",
        "sos": "1767",
        "mindline": "1771",
        "mailto": "mailto:SITCounselling@SingaporeTech.edu.sg",
    }
    SPEAK_PANEL_COPY: ClassVar[dict[str, dict[str, str]]] = {
        "low": {
            "heading": "Support is available",
            "body": "If you would like to talk, you can contact SIT Counselling.",
            "cta": "Optional: get in touch",
        },
        "medium": {
            "heading": "Consider speaking with someone",
            "body": "It may help to talk with SIT Counselling about how you have been feeling.",
            "cta": "Reach out when you are ready",
        },
        "high": {
            "heading": "Please reach out",
            "body": "You do not have to handle this on your own. SIT Counselling is here to help.",
            "cta": "Contact support now",
        },
    }
    DEFAULT_PROMINENCE: ClassVar[str] = "medium"

    AI_UNAVAILABLE_COPY: ClassVar[dict[str, str]] = {
        "heading": "We could not finish your check-in",
        "action_label": "Try again",
        "tone": "calm",
    }
    AI_ERROR_HINTS: ClassVar[dict[str, str]] = {
        "missing_api_key": "The assessment service is not configured.",
        "timeout": "The assessment took too long. Please try again.",
        "invalid_response": "The assessment could not be read. Please try again.",
        "retries_exhausted": "We tried a few times and could not complete the check-in.",
        "rate_limited": "The service is busy right now. Please try again shortly.",
        "unavailable": "Your answers are still here. Please try again in a moment.",
    }
    URGENT_ERROR_CODES: ClassVar[frozenset[str]] = frozenset({"rate_limited", "unavailable", "retries_exhausted"})

    STRESSOR_LABELS: ClassVar[dict[str, str]] = {
        "academic_overload": "Academic overload",
        "low_social_support": "Low social support",
        "high_stress": "High stress",
        "financial_pressure": "Financial pressure",
        "sleep_deprivation": "Sleep deprivation",
    }
    FACTOR_LABELS: ClassVar[dict[str, str]] = {
        "sleep": "Rest & recovery",
        "workload": "Study demands",
        "finances": "Money pressures",
        "support": "Support & connection",
    }

    RECORD_FIELD_ORDER: ClassVar[tuple[str, ...]] = (
        "student_id", "survey_version", "safety_flag",
        "pss_1", "pss_2", "pss_3", "pss_4", "sleep_hours_avg", "sleep_quality",
        "pas_workload", "pas_catchup", "fin_stress", "mspss_friends", "mspss_family",
        "stress_score", "risk_category", "soft_label", "tips", "reasoning",
    )

    def __init__(self) -> None:
        self.__validator = StudentFormValidator()

    # -- input ------------------------------------------------------------

    def validate_form(self, values: Any) -> tuple[bool, dict[str, Any]]:
        """``(True, clean_record)`` or ``(False, {field: message})``."""
        return self.__validator.validate(values)

    def validate_student_id(self, raw: Any) -> tuple[bool, str]:
        return self.__validator.validate_student_id(raw)

    # -- output -----------------------------------------------------------

    def format_soft_label(self, label: str) -> dict[str, str]:
        """Heading, body and tone for a tier name (unknown names use "Worth a check-in")."""
        return dict(self.SOFT_LABEL_COPY.get(label, self.SOFT_LABEL_COPY[self.DEFAULT_SOFT_LABEL]))

    def format_tips(self, tip_ids: Sequence[str]) -> dict[str, Any]:
        """The wording for each known tip ID; unknown IDs are dropped."""
        items = [
            {"id": tip_id, "text": self.TIPS_ALLOWLIST[str(tip_id)]}
            for tip_id in tip_ids
            if str(tip_id) in self.TIPS_ALLOWLIST
        ]
        return {"heading": self.TIPS_HEADING, "items": items}

    def format_advisor(self, prominence: str) -> dict[str, Any]:
        """The "Talk to someone" panel, with the SIT Counselling contacts."""
        copy = self.SPEAK_PANEL_COPY.get(prominence, self.SPEAK_PANEL_COPY[self.DEFAULT_PROMINENCE])
        return {**copy, **self.ADVISOR_CONTACTS, "prominence": prominence}

    def format_ai_error(self, code: str) -> dict[str, Any]:
        """Calm student-facing copy for an AI failure, with the advisor panel."""
        prominence = "high" if code in self.URGENT_ERROR_CODES else "medium"
        return {
            "heading": self.AI_UNAVAILABLE_COPY["heading"],
            "body": self.AI_ERROR_HINTS.get(code, self.AI_ERROR_HINTS["unavailable"]),
            "action_label": self.AI_UNAVAILABLE_COPY["action_label"],
            "tone": self.AI_UNAVAILABLE_COPY["tone"],
            "speak_to_advisor": self.format_advisor(prominence),
            "error_code": code,
        }

    def format_record(self, record: Mapping[str, Any]) -> dict[str, Any]:
        """A compact, display-ready view of one stored record (no free text)."""
        return {key: record.get(key) for key in self.RECORD_FIELD_ORDER if key in record}

    def format_summary(self, summary: Mapping[str, Any]) -> dict[str, Any]:
        """The cohort summary with a readable ``label`` on every tier, stressor and factor."""
        formatted = {key: dict(value) if isinstance(value, Mapping) else value for key, value in summary.items()}
        self.__label_items(formatted, "tiers", lambda item: item.get("soft_label") or item.get("category", ""))
        self.__label_items(formatted, "stressors", lambda item: self.__stressor_label(str(item.get("id", ""))))
        self.__label_items(formatted, "factors", lambda item: self.FACTOR_LABELS.get(str(item.get("id")), str(item.get("id", ""))))
        return formatted

    @staticmethod
    def __label_items(
        summary: dict[str, Any], section: str, label_for: Callable[[Mapping[str, Any]], str]
    ) -> None:
        part = summary.get(section)
        if isinstance(part, dict) and isinstance(part.get("items"), list):
            part["items"] = [{**item, "label": label_for(item)} for item in part["items"] if isinstance(item, Mapping)]

    def __stressor_label(self, stressor: str) -> str:
        return self.STRESSOR_LABELS.get(stressor, stressor.replace("_", " ").capitalize())
