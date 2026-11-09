"""GeminiAIManager: the AI Manager. Every check-in passes through here before Logic."""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any, ClassVar

from .ai_error_classifier import AIErrorClassifier
from .ai_manager_interface import AIManagerInterface
from .ai_processing_error import AIProcessingError
from .ai_response_schema import AIResponseSchema
from .gemini_text_generator import GeminiTextGenerator
from .prompt_builder import PromptBuilder
from .response_parser import ResponseParser
from .response_validator import ResponseValidator
from .retry_policy import RetryPolicy
from .score_verifier import ScoreVerifier
from .text_generator import TextGenerator

logger = logging.getLogger(__name__)


class GeminiAIManager(AIManagerInterface):
    """Builds the prompt, calls the API, parses the reply and validates its schema.

    Relationships (see the UML class diagram):
      * composition: PromptBuilder, ResponseParser, ResponseValidator,
        AIErrorClassifier and RetryPolicy are created here, are private and
        live only as long as this manager.
      * aggregation: the TextGenerator (the API client) is passed in or
        created by default. It can exist and be reused on its own.
      * association: the ScoreVerifier comes from the Logic Manager and is
        shared with it; this manager only uses it.

    The manager never invents a result. If no reply passes parsing, schema
    validation and the score check, ``analyse`` raises AIProcessingError.
    """

    PRIVATE_FIELDS: ClassVar[tuple[str, ...]] = ("feelings_text", "reflection")

    def __init__(
        self,
        verifier: ScoreVerifier | None = None,
        generator: TextGenerator | None = None,
        *,
        questions: Sequence[Mapping[str, Any]] = (),
        model_name: str = RetryPolicy.DEFAULT_MODEL,
        max_attempts: int = 3,
        retry_delay_sec: float = 0.5,
    ) -> None:
        self.__verifier = verifier
        self.__generator = generator if generator is not None else GeminiTextGenerator()
        self.__prompt_builder = PromptBuilder(questions)
        self.__parser = ResponseParser()
        self.__validator = ResponseValidator()
        self.__classifier = AIErrorClassifier()
        self.__retry = RetryPolicy(max_attempts, retry_delay_sec)
        self.__model_name = model_name

    @property
    def model_name(self) -> str:
        """The first model tried; the RetryPolicy chain follows it."""
        return self.__model_name

    def analyse(self, student: Mapping[str, Any]) -> dict[str, Any]:
        """Analyse one validated check-in. Raises AIProcessingError on failure."""
        if not isinstance(student, Mapping):
            raise AIProcessingError(AIProcessingError.INVALID_RESPONSE, "student must be a dict")
        fields = self.call_api(self.build_prompt(student), answers=student)
        enriched = {**dict(student), **fields}
        for key in self.PRIVATE_FIELDS:
            enriched.pop(key, None)
        return enriched

    def build_prompt(self, student: Mapping[str, Any]) -> str:
        """The prompt for one check-in, including the Logic Manager's scoring rules."""
        instructions = self.__verifier.instructions() if self.__verifier is not None else None
        return self.__prompt_builder.build(student, instructions)

    def parse_response(self, raw: Any) -> dict[str, Any] | None:
        """The reply as a JSON object, or None when it is malformed."""
        return self.__parser.parse(raw)

    def validate_response(self, data: Any) -> tuple[bool, Any]:
        """Schema check: ``(True, cleaned_fields)`` or ``(False, message)``."""
        return self.__validator.validate(data)

    def call_api(self, prompt: str, answers: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """Call the model with retries and model fallback.

        Returns the validated AI fields (plus ``source``). A reply that is not
        JSON, fails the schema, or fails the score check is retried like a
        connection error. Raises AIProcessingError when every attempt fails.
        """
        if not self.__generator.is_configured():
            raise AIProcessingError(AIProcessingError.MISSING_API_KEY, "GEMINI_API_KEY is not set")

        models = self.__retry.models_for(self.__model_name)
        tries = self.__retry.tries_per_model()
        last_code, last_detail = AIProcessingError.UNAVAILABLE, ""
        failures: list[str] = []
        calls = 0
        for model in models:
            for attempt in range(1, tries + 1):
                if not self.__retry.has_budget(calls):
                    break
                calls += 1
                try:
                    fields, problem = self.__attempt(prompt, model, answers)
                except Exception as exc:  # noqa: BLE001 - any API failure is classified and retried
                    last_detail = self.__generator.redact(str(exc))
                    last_code, switch_model = self.__classifier.classify(exc, last_detail)
                    failures.append(last_code)
                    if switch_model:
                        logger.warning("Gemini %s unavailable, trying the next model: %s", model, last_detail[:100])
                        break
                    logger.warning("Gemini call failed (%s): %s - %s", model, last_code, last_detail[:120])
                    if model != models[-1] and attempt == tries:
                        logger.info("Falling back from %s to the next model (%s)", model, last_code)
                    self.__retry.wait(attempt)
                    continue
                if fields is not None:
                    return fields
                last_code, last_detail = AIProcessingError.INVALID_RESPONSE, problem
                failures.append(last_code)
                self.__retry.wait(attempt)
        raise AIProcessingError(self.__classifier.final_code(last_code, calls, failures), last_detail)

    def __attempt(
        self, prompt: str, model: str, answers: Mapping[str, Any] | None
    ) -> tuple[dict[str, Any] | None, str]:
        """One call. ``(fields, "")`` when the reply is usable, else ``(None, reason)``."""
        parsed = self.parse_response(self.__generator.generate(prompt, model))
        if parsed is None:
            return None, "could not parse JSON"
        ok, cleaned = self.validate_response(parsed)
        if not ok:
            return None, str(cleaned)
        if self.__verifier is not None and answers is not None:
            problem = self.__check_scores(self.__verifier, cleaned, answers)
            if problem:
                return None, problem
        return {**cleaned, "source": AIResponseSchema.SOURCE}, ""

    @staticmethod
    def __check_scores(
        verifier: ScoreVerifier, fields: dict[str, Any], answers: Mapping[str, Any]
    ) -> str | None:
        """The Logic Manager's check on Gemini's arithmetic. A crash counts as a failed check."""
        try:
            return verifier.verify(fields, answers)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Score verifier raised: %s", type(exc).__name__)
            return "verifier error"
