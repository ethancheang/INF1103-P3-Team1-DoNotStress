"""DoNotStress — I/O Layer (io_manager).

IOManager validates what students type into the web form and turns
records into the plain data each page shows. All wording and page shapes
live here and in the templates; no other layer writes student-facing
copy.

Student ID: seven ASCII digits beginning with 2. The reflection is checked
for crisis language and then discarded; only the safety flag remains.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from base_manager import BaseManager
from json_types import JSONObject, JSONValue
from questionnaire import Questionnaire

# ---------------------------------------------------------------------------
# Student-facing wording. These are data tables, not classes.
# ---------------------------------------------------------------------------

SOFT_LABEL_COPY: dict[str, dict[str, str]] = {
    "You're doing ok": {
        "heading": "You're doing ok",
        "body": "Your check-in looks steady. Keep looking after yourself.",
        "tone": "reassuring",
    },
    "Worth a check-in": {
        "heading": "Worth a check-in",
        "body": ("Some things look a bit heavier right now. A "
                 "conversation could help."),
        "tone": "supportive",
    },
    "Please reach out": {
        "heading": "Please reach out",
        "body": ("Please reach out for support. You do not have to "
                 "handle this on your own."),
        "tone": "urgent",
    },
}
TIPS: dict[str, str] = {
    "sleep_routine": ("Try to keep a regular sleep schedule, including "
                      "on weekends."),
    "rest_a_little_more": ("If you can, give yourself a bit more rest — "
                           "even 30 extra minutes can help."),
    "short_breaks": ("Take short, planned breaks between study blocks "
                     "instead of pushing through without a pause."),
    "workload_chunks": ("Break larger assignments into smaller tasks "
                        "and spread them across the week."),
    "money_worries": ("If money is on your mind, campus support can "
                      "help you find the right next step."),
    "talk_to_someone": ("Reach out to a friend, classmate, or family "
                        "member — you do not have to handle this "
                        "alone."),
    "keep_social_contact": ("Stay in touch with people who help you "
                            "feel supported, even with a short "
                            "check-in."),
    "feelings_check_in": ("Name how you have been feeling and give "
                          "yourself permission to ask for help if "
                          "school feels heavy."),
}
ADVISOR_EMAIL: str = "SITCounselling@SingaporeTech.edu.sg"
ADVISOR_HELPLINE: str = "6592 2030"
ADVISOR_MAILTO: str = "mailto:SITCounselling@SingaporeTech.edu.sg"
SOS_HELPLINE: str = "1767"
MINDLINE_HELPLINE: str = "1771"
SPEAK_PANEL_COPY: dict[str, dict[str, str]] = {
    "low": {
        "heading": "Support is available",
        "body": ("If you would like to talk, you can contact SIT "
                 "Counselling."),
        "cta": "Optional: get in touch",
    },
    "medium": {
        "heading": "Consider speaking with someone",
        "body": ("It may help to talk with SIT Counselling about how "
                 "you have been feeling."),
        "cta": "Reach out when you are ready",
    },
    "high": {
        "heading": "Please reach out",
        "body": ("Please contact SIT Counselling. You do not have to "
                 "handle this on your own."),
        "cta": "Contact support now",
    },
}
AI_ERROR_HEADING: str = "We couldn't complete your check-in"
AI_ERROR_BODY: str = (
    "This check-in needs Gemini AI before we can show a result. AI is "
    "required for every record, so we cannot finish your check-in "
    "right now. Please try again later.")
AI_RATE_LIMITED_BODY: str = (
    "Our check-in assistant is busy right now. Your answers have been "
    "saved and will be reviewed soon.")
AI_ERROR_HINTS: dict[str, str] = {
    "missing_api_key": (
        "Operators/dev: GEMINI_API_KEY is not set. Add it to the "
        "environment and restart the app. Never paste the key into the "
        "page or into student-facing copy."),
    "timeout": (
        "Operators/dev: the Gemini request timed out. Confirm "
        "GEMINI_API_KEY is set and the service is reachable, then try "
        "again. Do not share the key."),
    "invalid_response": (
        "Operators/dev: Gemini returned a response that could not be "
        "used. Confirm GEMINI_API_KEY is set and check server logs. Do "
        "not expose the key."),
    "retries_exhausted": (
        "Operators/dev: Gemini failed after retries. Confirm "
        "GEMINI_API_KEY is set and the service is reachable. Do not "
        "expose the key."),
    "rate_limited": (
        "Operators/dev: every Gemini model was rate-limited. The "
        "check-in is saved as pending. Do not share the API key."),
    "unavailable": (
        "Operators/dev: Gemini AI is required for every check-in. "
        "Confirm GEMINI_API_KEY is set in the environment. Do not "
        "share or display the key."),
}
COMPARISON_COPY: dict[str, str] = {
    "none": ("No finished check-ins yet. Your history starts with "
             "your next check-in."),
    "first": ("This is your first finished check-in. Check in again "
              "later to see how things change."),
    "lower": "Your latest score is {change} points lower than last time.",
    "similar": "Your latest score is about the same as last time.",
    "higher": "Your latest score is {change} points higher than last time.",
}
DIRECTION_COPY: dict[str, str] = {
    "not_enough": ("After three check-ins, this page shows which way "
                   "things are heading."),
    "easing": ("Across your recent check-ins, stress looks like it "
               "is easing."),
    "steady": ("Across your recent check-ins, stress has stayed "
               "fairly steady."),
    "building": ("Across your recent check-ins, stress looks like it "
                 "is building. Talking to someone can help."),
}
FACTOR_COPY: tuple[tuple[str, str, str], ...] = (
    ("sleep", "Rest & recovery",
     "Sleep and stress affect each other. When sleep is short or "
     "restless, everyday tasks can feel harder, and stress can make it "
     "harder to sleep well."),
    ("workload", "Study demands",
     "A heavy workload can leave less time to rest and recharge. "
     "Feeling behind or overloaded is one of the most common sources "
     "of student stress."),
    ("finances", "Money pressures",
     "Financial worries can add to the pressure of studying. Concerns "
     "about money often weigh on focus and sleep."),
    ("support", "Support & connection",
     "Having people to turn to can make stressful times easier to "
     "handle. Strong support from friends or family helps protect "
     "against stress."),
)
FACTOR_FIELDS: tuple[str, ...] = (
    "sleep_hours_avg", "sleep_quality", "pas_workload", "fin_stress",
    "support_mean",
)
ADMIN_COLUMNS: tuple[str, ...] = (
    "student_id", "stress_score", "risk_category", "soft_label",
    "pss_1", "pss_2", "pss_3", "pss_4", "sleep_hours_avg",
    "sleep_quality", "pas_workload", "pas_catchup", "fin_stress",
    "mspss_friends", "mspss_family", "saved_at", "survey_version",
)
CATEGORY_LABELS: dict[str, str] = {
    "Low": "You're doing ok",
    "Moderate": "Worth a check-in",
    "High": "Please reach out",
}
STATUS_LABELS: dict[str, str] = {
    "evaluated": "Evaluated",
    "pending": "Pending",
}
RISK_CLASSES: dict[str, str] = {
    "Low": "low", "Moderate": "moderate", "High": "high",
}


class IOManager(BaseManager):
    """Collects and validates input; renders results, lists and errors.

    The questionnaire is passed in and shared (aggregation). Wording
    tables above are module-level data; private methods turn them into
    the page shapes the browser needs.
    """

    STUDENT_ID_EXAMPLE: str = "2605581"
    REFLECTION_LIMIT: int = 2000

    def __init__(self, questionnaire: Questionnaire) -> None:
        super().__init__("io_manager")
        self.__questionnaire: Questionnaire = questionnaire

    def describe(self) -> JSONObject:
        return {"questionnaire": self.__questionnaire.version,
                "questions": len(self.__questionnaire.questions)}

    # --- Input -----------------------------------------------------------

    def validate_student_id(self, raw: object) -> tuple[bool, str]:
        """(True, the ID) or (False, a message). Seven digits from 2."""
        text = str(raw if raw is not None else "").strip()
        if (len(text) != 7 or not text.isascii() or not text.isdigit()
                or not text.startswith("2")):
            return False, ("Student ID must be exactly 7 digits and start "
                           f"with 2 (e.g. {self.STUDENT_ID_EXAMPLE}).")
        return True, text

    def validate_feelings_text(self, raw: object) -> tuple[bool, str]:
        """(True, the stripped reflection) or (False, a message)."""
        if raw is not None and not isinstance(raw, str):
            return False, "Please enter text or leave this blank."
        text = (raw or "").strip()
        if len(text) > self.REFLECTION_LIMIT:
            return False, ("Please keep your reflection within 2,000 "
                           "characters.")
        return True, text

    def validate_student_form(self, form: Mapping[str, object]
                              ) -> tuple[bool, JSONObject]:
        """(True, the check-in) or (False, a message for each bad field).

        The check-in never keeps the reflection, and never trusts a score,
        tier or flag sent by the browser.
        """
        record: JSONObject = {}
        errors: JSONObject = {}
        ok, student_id = self.validate_student_id(form.get("student_id"))
        (record if ok else errors)["student_id"] = student_id
        for question in self.__questionnaire.questions:
            key = str(question["key"])
            ok, answer = self.__questionnaire.validate_answer(
                key, form.get(key))
            (record if ok else errors)[key] = answer
        ok, reflection = self.validate_feelings_text(
            form.get("feelings_text"))
        if not ok:
            errors["feelings_text"] = reflection
        if errors:
            return False, errors
        record["safety_flag"] = self.__questionnaire.safety_fired(reflection)
        record["survey_version"] = self.__questionnaire.version
        return True, record

    def validate_record_filters(self, tier: str,
                                cohort_year: str) -> str | None:
        """A message for an unknown admin filter, or None when both are ok."""
        if tier and tier not in SOFT_LABEL_COPY:
            return ("Choose a tier: You're doing ok, Worth a check-in, or "
                    "Please reach out.")
        if cohort_year and (len(cohort_year) not in (2, 4)
                            or not cohort_year.isascii()
                            or not cohort_year.isdigit()):
            return "Choose a valid cohort year."
        return None

    def safety_fired(self, text: object) -> bool:
        """The reflection safety check, for an immediate support prompt."""
        return self.__questionnaire.safety_fired(text)

    # --- Output ----------------------------------------------------------

    def display_list(self, records: Sequence[JSONObject]) -> list[JSONObject]:
        """Admin table rows, newest first. Free text is never included."""
        newest = sorted(records, key=lambda row: str(row.get("saved_at") or ""),
                        reverse=True)
        rows: list[JSONObject] = []
        for record in newest:
            row: JSONObject = {key: record.get(key) for key in ADMIN_COLUMNS}
            if not row["soft_label"]:
                row["soft_label"] = CATEGORY_LABELS.get(
                    str(record.get("risk_category") or ""))
            status = str(record.get("status") or "evaluated")
            row["status"] = STATUS_LABELS.get(status, status)
            rows.append(row)
        return rows

    def display_result(self, record: JSONObject) -> JSONObject:
        """The student's result page for a finished check-in."""
        advisor = self.advisor_panel(str(record.get("speak_prominence") or ""))
        advisor.pop("cta", None)
        return {
            "soft": self.format_soft_label(str(record.get("soft_label") or "")),
            "tips": self.format_tips(record.get("tips")),
            "advisor": advisor,
            "insights": {
                "risk_category": str(record.get("risk_category") or "Unknown"),
                "explanation": str(record.get("reasoning") or ""),
                "stressors": self.__strings(record.get("primary_stressors")),
                "factors": self.__factor_cards(record),
                "safety_flag": record.get("safety_flag") is True,
            },
        }

    def display_history(self, history: JSONObject,
                        trend: JSONObject) -> JSONObject:
        """A student's own history page: scores, trend and support.

        Support is highlighted when stress is building or the latest
        check-in was High. Answers and reasoning are never included.
        """
        records = history.get("records") if isinstance(history, dict) else []
        entries: list[JSONObject] = []
        latest_category = ""
        if isinstance(records, list):
            for raw in records:
                if not isinstance(raw, dict):
                    continue
                category = str(raw.get("risk_category") or "")
                label = str(raw.get("soft_label") or "")
                score = raw.get("stress_score")
                if isinstance(score, bool) or not isinstance(score, (int, float)):
                    score_value: JSONValue = None
                else:
                    score_value = float(score)
                entries.append({
                    "saved_at": str(raw.get("saved_at") or ""),
                    "score": score_value,
                    "tier": label or CATEGORY_LABELS.get(category, ""),
                    "risk": RISK_CLASSES.get(category, "unknown"),
                    "status": str(raw.get("status") or "evaluated"),
                })
                latest_category = category
        high = latest_category == "High"
        direction = str(trend.get("direction") or "") if isinstance(trend, dict) else ""
        needs_support = high or direction == "building"
        advisor = (self.advisor_panel("high" if high else "medium")
                   if needs_support else None)
        pending = 0
        student_id = ""
        if isinstance(history, dict):
            pending = int(history.get("pending_count") or 0)
            student_id = str(history.get("student_id") or "")
        return {
            "student_id": student_id,
            "entries": entries,
            "pending": pending,
            "trend": self.__trend_summary(trend if isinstance(trend, dict) else {}),
            "advisor": advisor,
        }

    def display_error(self, code: str,
                      detail: str | None = None) -> JSONObject:
        """The page shown when the AI step could not finish."""
        known = code.strip().lower()
        error = None
        if known not in AI_ERROR_HINTS:
            if known:
                error = ("Unknown AI error_code. Use one of: "
                         f"{', '.join(AI_ERROR_HINTS)}.")
            known = "unavailable"
        body = (AI_RATE_LIMITED_BODY if known == "rate_limited"
                else AI_ERROR_BODY)
        hint = AI_ERROR_HINTS[known]
        reason = self.__operator_detail(detail)
        if reason:
            hint = f"{hint} Detail: {reason}."
        return {
            "heading": AI_ERROR_HEADING,
            "body": body,
            "hint": hint,
            "action_label": "Try again",
            "tone": "urgent",
            "ai_required": True,
            "error_code": known,
            "reason": reason,
            "speak_to_advisor": self.advisor_panel("high"),
            "error": error,
        }

    def format_soft_label(self, label: object) -> JSONObject:
        text = str(label or "").strip()
        copy = SOFT_LABEL_COPY.get(text)
        if copy is None:
            allowed = ", ".join(f'"{name}"' for name in SOFT_LABEL_COPY)
            return {"label": "", "heading": "", "body": "", "tone": "",
                    "error": f"Unknown soft label. Use one of: {allowed}."}
        return {"label": text, **copy, "error": None}

    def format_tips(self, tip_ids: object) -> JSONObject:
        items: list[JSONValue] = []
        seen: set[str] = set()
        raw_list = tip_ids if isinstance(tip_ids, list) else []
        for raw in raw_list:
            tip_id = str(raw).strip()
            if tip_id in TIPS and tip_id not in seen:
                seen.add(tip_id)
                items.append({"id": tip_id, "text": TIPS[tip_id]})
        return {"heading": "Suggestions for you", "items": items}

    def advisor_panel(self, prominence: str) -> JSONObject:
        """The "talk to someone" panel. Prominence only changes the tone."""
        level = prominence.strip().lower()
        error = None
        if level not in SPEAK_PANEL_COPY:
            level = "medium"
            error = "Unknown speak_prominence. Use one of: low, medium, high."
        return {
            "prominence": level,
            **SPEAK_PANEL_COPY[level],
            "email": ADVISOR_EMAIL,
            "helpline": ADVISOR_HELPLINE,
            "sos": SOS_HELPLINE,
            "mindline": MINDLINE_HELPLINE,
            "mailto": ADVISOR_MAILTO,
            "error": error,
        }

    def page_config(self) -> JSONObject:
        """The questionnaire as the browser needs it."""
        return self.__questionnaire.public_config()

    def __trend_summary(self, trend: JSONObject) -> JSONObject:
        comparison = str(trend.get("comparison") or "none")
        direction = str(trend.get("direction") or "not_enough")
        change = trend.get("change")
        amount = ""
        if isinstance(change, bool):
            change = None
        elif isinstance(change, (int, float)):
            amount = f"{abs(float(change)):.2f}"
        headline = COMPARISON_COPY.get(comparison, COMPARISON_COPY["none"])
        detail = DIRECTION_COPY.get(direction, DIRECTION_COPY["not_enough"])
        return {
            "comparison": comparison,
            "direction": direction,
            "headline": headline.format(change=amount),
            "detail": detail,
            "latest": trend.get("latest"),
            "previous": trend.get("previous"),
            "change": change,
            "average": trend.get("average"),
        }

    def __factor_cards(self, record: JSONObject) -> list[JSONValue]:
        found: dict[str, float] = {}
        for key in FACTOR_FIELDS:
            number = self.__number(record.get(key))
            if number is None:
                return []
            found[key] = number
        flags = record.get("context_flags")
        flagged = flags if isinstance(flags, dict) else {}
        workload, finances = found["pas_workload"], found["fin_stress"]
        shown = {
            "sleep": (f"{found['sleep_hours_avg']:g} hours · "
                      f"{self.__label(found, 'sleep_quality')} quality"),
            "workload": (f"{workload:g}/5 · "
                         f"{self.__label(found, 'pas_workload')}"),
            "finances": (f"{finances:g}/5 · "
                         f"{self.__label(found, 'fin_stress')}"),
            "support": (f"{found['support_mean']:g}/5 agreement across "
                        "2 answers"),
        }
        return [{"title": title, "flagged": flagged.get(flag) is True,
                 "value": shown[flag], "text": text}
                for flag, title, text in FACTOR_COPY]

    def __label(self, found: dict[str, float], key: str) -> str:
        return self.__questionnaire.option_label(key, int(found[key]))

    def __number(self, value: JSONValue) -> float | None:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        return float(value)

    def __strings(self, value: JSONValue) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    def __operator_detail(self, raw: str | None) -> str | None:
        text = (raw or "").strip()
        if not text or self.__looks_like_secret(text):
            return None
        return text if len(text) <= 200 else text[:200].rstrip() + "…"

    def __looks_like_secret(self, text: str) -> bool:
        compact = "".join(text.split())
        lowered = compact.lower()
        if "api_key=" in lowered:
            return True
        if "bearer" in lowered and len(compact) > 20:
            return True
        return len(compact) >= 32 and compact.isalnum()
