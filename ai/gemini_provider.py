"""The live Google Gemini provider."""

from __future__ import annotations

import os

from google import genai

from ai.ai_provider import AIProvider
from json_types import JSONObject


class GeminiProvider(AIProvider):
    """One structured-JSON Gemini call per generate().

    The API key stays in a private attribute and is never logged. The
    client is built once and reused, so a check-in that falls back
    across models does not open a new connection each time.
    """

    MODEL_CHAIN: tuple[str, ...] = (
        "gemini-3.6-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite",
    )
    TEMPERATURE: float = 0.0
    TIMEOUT_SEC: float = 30.0

    def __init__(self, api_key: str | None = None,
                 preferred_model: str | None = None) -> None:
        super().__init__()
        if api_key is None:
            api_key = os.environ.get("GEMINI_API_KEY", "")
        self.__api_key: str = api_key.strip()
        self.__models: tuple[str, ...] = self.__model_order(preferred_model)
        self.__client: object | None = None

    def __model_order(self, preferred: str | None = None) -> tuple[str, ...]:
        """The preferred model first, then the rest of MODEL_CHAIN, no repeats."""
        first = (preferred or "").strip() or self.MODEL_CHAIN[0]
        return (first, *(name for name in self.MODEL_CHAIN if name != first))

    @property
    def name(self) -> str:
        return "gemini"

    @property
    def models(self) -> tuple[str, ...]:
        return self.__models

    def is_ready(self) -> bool:
        return bool(self.__api_key)

    def generate(self, prompt: str, model_name: str,
                 schema: JSONObject | None = None) -> str:
        # The SDK's own HTTP retries are off: AIManager's call cap is the
        # only retry policy, so a 429 never turns into a retry storm.
        client = self.__get_client()
        config: JSONObject = {
            "temperature": self.TEMPERATURE,
            "response_mime_type": "application/json",
            "automatic_function_calling": {"disable": True},
        }
        if schema is not None:
            config["response_schema"] = schema
        response = client.models.generate_content(
            model=model_name, contents=prompt, config=config)
        text = getattr(response, "text", None) if response is not None else None
        if isinstance(text, str) and text.strip():
            return text
        try:
            candidates = getattr(response, "candidates", None) or []
            parts = getattr(candidates[0].content, "parts", None) or []
            part_text = getattr(parts[0], "text", None)
            if isinstance(part_text, str) and part_text.strip():
                return part_text
        except (IndexError, AttributeError, TypeError):
            pass
        raise RuntimeError("Gemini returned no text payload.")

    def redact(self, text: str) -> str:
        if self.__api_key:
            return text.replace(self.__api_key, "[redacted]")
        return text

    def __get_client(self):
        if self.__client is None:
            self.__client = genai.Client(
                api_key=self.__api_key,
                http_options={
                    "timeout": int(self.TIMEOUT_SEC * 1000),
                    "retry_options": {"attempts": 1},
                },
            )
        return self.__client
