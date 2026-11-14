"""DoNotStress — AI Processing Layer (ai_manager).

AIManager is the only class that talks to an AI provider. For every
check-in it builds the prompt, calls the provider with model fallback,
parses the reply and validates it field by field.

It holds no domain rules. The scoring instructions and the check on each
reply are injected by App from LogicManager (instructions and verify).
A reply that fails that check is treated like any other invalid reply
and can be retried.

Only the 11 raw answers, the questionnaire version and the question
wording are sent: never a student id, reflection, or precomputed score,
flag or tier. On failure it returns an error dict and never invents
soft_label / tips / speak_prominence or falls back to Logic.
"""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable

from ai.ai_provider import AIProvider
from base_manager import BaseManager
from json_types import JSONObject, JSONValue
from questionnaire import Questionnaire

# Field rules used to validate Gemini's reply. Wording and scoring
# constants stay as data; they are not classes.
RISK_CATEGORIES: tuple[str, ...] = ("Low", "Moderate", "High")
SOFT_LABELS: tuple[str, ...] = (
    "You're doing ok",
    "Worth a check-in",
    "Please reach out",
)
LABEL_ALIASES: dict[str, str] = {"You’re doing ok": "You're doing ok"}
SPEAK_PROMINENCE: tuple[str, ...] = ("low", "medium", "high")
ALLOWED_STRESSORS: frozenset[str] = frozenset({
    "sleep_deprivation",
    "high_stress",
    "academic_overload",
    "financial_pressure",
    "low_social_support",
})
ALLOWED_TIPS: frozenset[str] = frozenset({
    "sleep_routine",
    "rest_a_little_more",
    "short_breaks",
    "workload_chunks",
    "money_worries",
    "talk_to_someone",
    "keep_social_contact",
})

MISSING_KEY_MARKERS: tuple[str, ...] = (
    "missing_api_key", "gemini_api_key is not set", "api key is not set",
    "api_key is not set",
)
RATE_LIMIT_MARKERS: tuple[str, ...] = (
    "429", "resource exhausted", "resourceexhausted", "too many requests",
    "toomanyrequests", "rate limit", "ratelimit", "quota",
)
TIMEOUT_MARKERS: tuple[str, ...] = (
    "timeout", "timed out", "timed_out", "read timed out",
    "deadlineexceeded", "deadline exceeded",
)
SCHEMA_MARKERS: tuple[str, ...] = (
    "schema validation", "not valid json", "jsondecode", "jsondecodeerror",
    "malformed", "missing required fields", "must be a json object",
    "ai response must be", "empty ai response", "allow-list", "invalid json",
)

ERROR_MISSING_API_KEY = "missing_api_key"
ERROR_TIMEOUT = "timeout"
ERROR_INVALID_RESPONSE = "invalid_response"
ERROR_RETRIES_EXHAUSTED = "retries_exhausted"
ERROR_RATE_LIMITED = "rate_limited"
ERROR_UNAVAILABLE = "unavailable"


class AIManager(BaseManager):
    """Builds the prompt, calls the provider, parses and checks the reply.

    The provider and the questionnaire are passed in and shared
    (aggregation). instructions and verify are bound methods from
    LogicManager, injected by App, so this manager never imports Logic.
    """

    MAX_TOTAL_CALLS: int = 4
    TRIES_PER_MODEL: int = 2
    OVERALL_TIMEOUT_SEC: float = 45.0
    REPEATABLE: tuple[str, ...] = (ERROR_TIMEOUT, ERROR_INVALID_RESPONSE)
    SOURCE: str = "gemini"
    REQUIRED_FIELDS: tuple[str, ...] = (
        "scored_items", "stress_score", "risk_category", "soft_label",
        "speak_prominence", "primary_stressors", "tips", "reasoning",
        "confidence",
    )

    def __init__(self, provider: AIProvider, questionnaire: Questionnaire,
                 instructions: Callable[[], str],
                 verify: Callable[[JSONObject, JSONObject], str | None],
                 *,
                 max_attempts: int = 3,
                 retry_delay_sec: float = 0.5,
                 overall_timeout_sec: float = OVERALL_TIMEOUT_SEC) -> None:
        super().__init__("ai_manager")
        self.__provider: AIProvider = provider
        self.__questionnaire: Questionnaire = questionnaire
        self.__instructions: Callable[[], str] = instructions
        self.__verify: Callable[[JSONObject, JSONObject], str | None] = verify
        self.__tries_per_model: int = max(
            1, min(max_attempts, self.TRIES_PER_MODEL))
        self.__retry_delay_sec: float = max(0.0, retry_delay_sec)
        self.__overall_timeout_sec: float = max(0.0, overall_timeout_sec)
        self.__schema: JSONObject = self.__build_schema()

    @property
    def answer_keys(self) -> tuple[str, ...]:
        return self.__questionnaire.keys()

    @property
    def prompt_fields(self) -> tuple[str, ...]:
        """The only check-in fields ever sent to the provider."""
        return self.answer_keys + ("survey_version",)

    def describe(self) -> JSONObject:
        return {
            "provider": self.__provider.name,
            "ready": self.__provider.is_ready(),
            "models": list(self.__provider.models),
            "validated_fields": list(self.REQUIRED_FIELDS),
            "max_calls": self.MAX_TOTAL_CALLS,
        }

    def analyse(self, record: JSONObject) -> JSONObject:
        """Prompt → provider → validated fields merged into the record.

        Returns {"ok": True, "fields": ...} or
        {"ok": False, "error_code": ..., "detail": ...}. Never raises
        for API or schema failures. Every successful record is marked
        source="gemini".
        """
        if not isinstance(record, dict):
            return {"ok": False, "error_code": ERROR_INVALID_RESPONSE,
                    "detail": "The check-in must be a dict from io_manager."}
        result = self.__call_api(self.__build_prompt(record), answers=record)
        if not result.get("ok"):
            return result
        fields = result["fields"]
        if not isinstance(fields, dict):
            raise TypeError("AI result fields must be a dict.")
        return {"ok": True, "fields": {**record, **fields}}

    def __build_prompt(self, record: JSONObject) -> str:
        """Ask Gemini to calculate stress_score from the raw answers.

        The JSON at the end holds only prompt_fields. Question wording and
        answer labels are instructions, not scored fields. Logic's
        instructions() are included so Gemini is told the same formula
        that verify() will check.
        """
        payload = {key: record.get(key) for key in self.prompt_fields}
        count = len(self.answer_keys)
        labels = ", ".join(f'"{label}"' for label in SOFT_LABELS)
        rules = self.__instructions()
        lines = [
            "You are a supportive student-wellbeing assistant for "
            "DoNotStress, a local check-in used by students.",
            f"Calculate stress_score from the {count} answers with the "
            "formula below. You are not given a score, a tier, or a "
            "written reflection. Do not diagnose, and do not invent "
            "contacts.",
            rules + "Question wording and answer labels:",
            *(self.__format_question(item)
              for item in self.__questionnaire.questions),
            "Speak to the student with warmth. Return ONLY a single JSON "
            "object (no markdown fences, no commentary) with exactly these "
            "keys:",
            f'- "scored_items": object of the {count} converted values. '
            f"Keys are {', '.join(self.answer_keys)}. Each value is an "
            "integer from 1 to 5.",
            '- "stress_score": the mean above, from 1 to 5, rounded to '
            "2 decimal places",
            '- "risk_category": "Low", "Moderate", or "High", matching '
            "stress_score",
            '- "primary_stressors": list of snake_case strings chosen ONLY '
            f"from: {', '.join(sorted(ALLOWED_STRESSORS))}",
            '- "confidence": number from 0.0 to 1.0',
            '- "reasoning": 2 or 3 warm, plain sentences written to the '
            "student. No numbers, no jargon, no diagnosis, and no contacts",
            f'- "soft_label": exactly one of {labels}, matching '
            "risk_category. Use a straight apostrophe in You're doing ok",
            '- "tips": list of 1 to 3 tip IDs only, each one of: '
            f"{', '.join(sorted(ALLOWED_TIPS))}. Do not invent "
            "tip text",
            '- "speak_prominence": "low", "medium", or "high", matching '
            "risk_category. This is how strongly the UI highlights Talk to "
            "someone. SIT Counselling stays available and is shown more "
            "prominently when stress is higher",
            "Do not add other keys. Never invent phone numbers, emails, or "
            "offices. SIT Counselling contacts are shown by the UI, not by "
            "you.",
            "",
            "Student check-in:",
            json.dumps(payload, ensure_ascii=False, indent=2),
        ]
        return "\n".join(lines) + "\n"

    def __call_api(self, prompt: str, answers: JSONObject) -> JSONObject:
        """Try the provider's models in order until a reply is valid.

        A missing key stops at once. A timeout or invalid reply gets one
        more try on the same model; any other error moves to the next
        model. At most MAX_TOTAL_CALLS calls are made, and retries stop
        once the overall deadline passes.
        """
        if not self.__provider.is_ready():
            detail = "GEMINI_API_KEY is not set; cannot call Gemini."
            self.logger.error(detail)
            return {"ok": False, "error_code": ERROR_MISSING_API_KEY,
                    "detail": detail}
        failures: list[tuple[str, str]] = []
        calls = 0
        last_try = 1
        deadline = time.monotonic() + self.__overall_timeout_sec
        for model in self.__provider.models:
            if calls == self.MAX_TOTAL_CALLS or time.monotonic() >= deadline:
                break
            for attempt in range(1, self.__tries_per_model + 1):
                if calls == self.MAX_TOTAL_CALLS or time.monotonic() >= deadline:
                    break
                if attempt > 1:
                    self.__pause(attempt - 1, deadline)
                    if time.monotonic() >= deadline:
                        break
                calls += 1
                last_try = attempt
                result = self.__attempt(prompt, model, answers, attempt)
                if result.get("ok"):
                    return result
                code = str(result.get("error_code") or ERROR_UNAVAILABLE)
                detail = str(result.get("detail") or "")
                if code == ERROR_MISSING_API_KEY:
                    return result
                failures.append((code, detail))
                if code not in self.REPEATABLE:
                    break
            self.logger.warning("Gemini model %s failed (%s)", model,
                                failures[-1][0] if failures else "unknown")
        return self.__final_failure(failures, last_try)

    def __parse_response(self, raw: object) -> JSONObject | None:
        """The JSON object inside a raw reply, even inside code fences."""
        if isinstance(raw, dict):
            return raw
        if not isinstance(raw, str):
            return None
        start, end = raw.find("{"), raw.rfind("}")
        if start == -1 or end <= start:
            return None
        try:
            data = json.loads(raw[start:end + 1])
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def __validate_response(self, payload: object) -> tuple[bool, JSONValue]:
        """Check required keys, types, ranges and allow-lists.

        Extra keys are dropped. Returns (True, fields) or (False, message).
        """
        if isinstance(payload, str):
            if not payload.strip():
                return False, "Empty AI response string."
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as error:
                return False, f"AI response is not valid JSON: {error}"
        if not isinstance(payload, dict):
            return False, "AI response must be a JSON object."
        missing = [name for name in self.REQUIRED_FIELDS if name not in payload]
        if missing:
            return False, ("AI response missing required fields: "
                           f"{', '.join(missing)}.")
        fields: JSONObject = {}
        for field in self.REQUIRED_FIELDS:
            ok, value = self.__validate_field(field, payload[field])
            if not ok:
                return False, value
            fields[field] = value
        return True, fields

    def __classify_error(self, error: BaseException | str | None) -> str:
        """One error code. Unknown errors map to "unavailable"."""
        kind = type(error).__name__ if isinstance(error, BaseException) else ""
        text = f"{kind} {error or ''}".strip().lower()
        if not text:
            return ERROR_UNAVAILABLE
        if self.__mentions(text, MISSING_KEY_MARKERS) or (
                "gemini_api_key" in text
                and self.__mentions(text, ("not set", "missing", "blank"))):
            return ERROR_MISSING_API_KEY
        status = (getattr(error, "code", None),
                  getattr(error, "status_code", None))
        if 429 in status or self.__mentions(text, RATE_LIMIT_MARKERS):
            return ERROR_RATE_LIMITED
        if self.__mentions(text, TIMEOUT_MARKERS):
            return ERROR_TIMEOUT
        if self.__mentions(text, SCHEMA_MARKERS):
            return ERROR_INVALID_RESPONSE
        if "retries" in text and "exhaust" in text:
            return ERROR_RETRIES_EXHAUSTED
        return ERROR_UNAVAILABLE

    def __attempt(self, prompt: str, model: str, answers: JSONObject,
                  attempt: int) -> JSONObject:
        label = f"(attempt {attempt}/{self.__tries_per_model}) model={model}"
        try:
            raw = self.__provider.generate(prompt, model, self.__schema)
        except Exception as error:
            detail = (f"Gemini API failure {label}: "
                      f"{self.__provider.redact(str(error))}")
            self.logger.warning(detail)
            return {"ok": False, "error_code": self.__classify_error(error),
                    "detail": detail}
        ok, checked = self.__check_reply(raw, answers)
        if ok and isinstance(checked, dict):
            return {"ok": True, "fields": {**checked, "source": self.SOURCE,
                                           "ai_model": model}}
        detail = f"Schema validation failed {label}: {checked}"
        self.logger.warning(detail)
        return {"ok": False, "error_code": ERROR_INVALID_RESPONSE,
                "detail": detail}

    def __check_reply(self, raw: str,
                      answers: JSONObject) -> tuple[bool, JSONValue]:
        parsed = self.__parse_response(raw)
        ok, fields = self.__validate_response(raw if parsed is None else parsed)
        if not ok or not isinstance(fields, dict):
            return False, fields
        try:
            problem = self.__verify(fields, answers)
        except Exception as error:
            return False, f"Score check could not run: {error}"
        return (False, problem) if problem else (True, fields)

    def __final_failure(self, failures: list[tuple[str, str]],
                        last_try: int) -> JSONObject:
        if not failures:
            return {"ok": False, "error_code": ERROR_TIMEOUT,
                    "detail": "AI check-in timed out before completing."}
        code, detail = failures[-1]
        if all(item_code == ERROR_RATE_LIMITED for item_code, _ in failures):
            return {"ok": False, "error_code": ERROR_RATE_LIMITED,
                    "detail": detail}
        if last_try > 1 and code not in self.REPEATABLE:
            return {"ok": False, "error_code": ERROR_RETRIES_EXHAUSTED,
                    "detail": detail}
        return {"ok": False, "error_code": code, "detail": detail}

    def __pause(self, retry: int, deadline: float | None = None) -> None:
        delay = self.__retry_delay_sec * 2 ** (retry - 1)
        if deadline is not None:
            delay = min(delay, max(0.0, deadline - time.monotonic()))
        if delay > 0:
            time.sleep(delay)

    def __build_schema(self) -> JSONObject:
        names: list[JSONValue] = list(self.REQUIRED_FIELDS)
        keys = list(self.answer_keys)
        properties: JSONObject = {
            "scored_items": {
                "type": "OBJECT",
                "properties": {key: {"type": "INTEGER"} for key in keys},
                "required": keys,
            },
            "stress_score": {"type": "NUMBER"},
            "risk_category": {"type": "STRING", "enum": list(RISK_CATEGORIES)},
            "soft_label": {"type": "STRING", "enum": list(SOFT_LABELS)},
            "speak_prominence": {
                "type": "STRING", "enum": list(SPEAK_PROMINENCE)},
            "primary_stressors": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": sorted(ALLOWED_STRESSORS)},
            },
            "tips": {
                "type": "ARRAY",
                "items": {"type": "STRING", "enum": sorted(ALLOWED_TIPS)},
                "minItems": 1, "maxItems": 3,
            },
            "reasoning": {"type": "STRING"},
            "confidence": {"type": "NUMBER"},
        }
        return {
            "type": "OBJECT",
            "propertyOrdering": names,
            "required": names,
            "properties": properties,
        }

    def __format_question(self, question: JSONObject) -> str:
        reverse = question.get("reverse") is True
        tone = (" Positively worded: a high answer means less stress."
                if reverse else "")
        key = question["key"]
        prompt = question["prompt"]
        head = f"- {key}: {prompt}{tone}"
        options = question.get("options") or []
        if options:
            labels = ", ".join(
                f"{number} = {label}"
                for number, label in enumerate(options, start=1))
            return f"{head} Answer labels: {labels}."
        minimum = question["min"]
        maximum = question["max"]
        step = question["step"]
        low = question.get("low") or ""
        high = question.get("high") or ""
        return (f"{head} Answer: {minimum} to {maximum} "
                f"hours in steps of {step:g} ({low} to {high}), "
                "not a 1 to 5 rating.")

    def __validate_field(self, field: str,
                         value: JSONValue) -> tuple[bool, JSONValue]:
        if field == "scored_items":
            return self.__validate_scored_items(value)
        if field == "stress_score":
            return self.__validate_range(field, value, 1.0, 5.0)
        if field == "confidence":
            return self.__validate_range(field, value, 0.0, 1.0)
        if field == "risk_category":
            return self.__validate_choice(field, value, RISK_CATEGORIES)
        if field == "soft_label":
            return self.__validate_choice(field, value, SOFT_LABELS)
        if field == "speak_prominence":
            return self.__validate_choice(field, value, SPEAK_PROMINENCE)
        if field == "primary_stressors":
            return self.__validate_id_list(
                field, value, ALLOWED_STRESSORS, 0, None)
        if field == "tips":
            return self.__validate_id_list(field, value, ALLOWED_TIPS, 1, 3)
        if field == "reasoning":
            if not isinstance(value, str) or not value.strip():
                return False, f"{field} must be a non-empty string."
            return True, value.strip()
        return False, f"Unknown field {field}."

    def __validate_scored_items(self, value: JSONValue
                                ) -> tuple[bool, JSONValue]:
        if not isinstance(value, dict):
            return False, "scored_items must be an object of integer scores."
        expected = set(self.answer_keys)
        got = set(value)
        if got != expected:
            return False, "scored_items keys must be exactly the 11 answers."
        cleaned: dict[str, int] = {}
        for key in self.answer_keys:
            item = value[key]
            if (isinstance(item, bool) or not isinstance(item, int)
                    or not 1 <= item <= 5):
                return False, f"scored_items.{key} must be an integer 1 to 5."
            cleaned[key] = item
        return True, cleaned

    def __validate_range(self, field: str, value: JSONValue,
                         minimum: float, maximum: float
                         ) -> tuple[bool, JSONValue]:
        message = f"{field} must be a number between {minimum} and {maximum}."
        if isinstance(value, bool) or not isinstance(value, (int, float, str)):
            return False, message
        try:
            number = float(value)
        except (ValueError, OverflowError):
            return False, message
        if not math.isfinite(number) or not minimum <= number <= maximum:
            return False, message
        return True, number

    def __validate_choice(self, field: str, value: JSONValue,
                          choices: tuple[str, ...]
                          ) -> tuple[bool, JSONValue]:
        if not isinstance(value, str):
            return False, f"{field} must be one of {choices}."
        text = value.strip()
        if field == "soft_label":
            text = LABEL_ALIASES.get(text, text)
        if text not in choices:
            return False, f"{field} must be one of {choices}."
        return True, text

    def __validate_id_list(self, field: str, value: JSONValue,
                           allowed: frozenset[str], min_items: int,
                           max_items: int | None
                           ) -> tuple[bool, JSONValue]:
        if not isinstance(value, list):
            return False, f"{field} must be a list of allow-listed IDs."
        if len(value) < min_items or (
                isinstance(max_items, int) and len(value) > max_items):
            return False, f"{field} item count out of bounds."
        cleaned: list[str] = []
        for item in value:
            if not isinstance(item, str):
                return False, f"each {field} item must be a string ID."
            tid = item.strip()
            if tid not in allowed:
                return False, f"{field} ID is not on the allow-list: {tid}."
            if tid not in cleaned:
                cleaned.append(tid)
        if len(cleaned) < min_items:
            return False, f"{field} must contain at least {min_items} IDs."
        return True, cleaned

    def __mentions(self, text: str, markers: tuple[str, ...]) -> bool:
        return any(marker in text for marker in markers)
