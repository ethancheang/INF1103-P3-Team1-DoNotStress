"""GeminiTextGenerator: the live Gemini API client."""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from typing import Any, ClassVar

from .text_generator import TextGenerator

logger = logging.getLogger(__name__)


class GeminiTextGenerator(TextGenerator):
    """Calls Gemini with JSON output requested.

    It tries the google-genai SDK first and falls back to the REST endpoint
    (which accepts both AIza... and AQ... keys). The API key is read from
    the ``GEMINI_API_KEY`` environment variable unless one is passed in, is
    kept private, and is masked in every log line and error message.
    """

    ENV_VAR: ClassVar[str] = "GEMINI_API_KEY"
    REST_URL: ClassVar[str] = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
    DEFAULT_TEMPERATURE: ClassVar[float] = 0.2
    DEFAULT_TIMEOUT_SECONDS: ClassVar[float] = 30.0

    def __init__(
        self,
        api_key: str | None = None,
        *,
        temperature: float = DEFAULT_TEMPERATURE,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self.__api_key = api_key
        self.__temperature = temperature
        self.__timeout_seconds = timeout_seconds

    def is_configured(self) -> bool:
        return bool(self.__key())

    def redact(self, text: str) -> str:
        key = self.__key()
        return text.replace(key, "***") if key and key in text else text

    def generate(self, prompt: str, model_name: str) -> str:
        text = self.__generate_with_sdk(prompt, model_name)
        if text:
            return text
        return self.__generate_with_rest(prompt, model_name)

    def __key(self) -> str:
        """The configured key (read when needed, so a key set after start-up is used)."""
        return self.__api_key if self.__api_key is not None else os.environ.get(self.ENV_VAR, "")

    def __generate_with_sdk(self, prompt: str, model_name: str) -> str:
        """The SDK reply text, or "" when the SDK is missing or the call fails."""
        try:
            from google import genai
            from google.genai import types as genai_types

            client = genai.Client(api_key=self.__key())
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
                config=genai_types.GenerateContentConfig(
                    temperature=self.__temperature,
                    response_mime_type="application/json",
                ),
            )
            text = getattr(response, "text", None) or ""
            if not text:
                text = self.__first_candidate_text(response)
            return text
        except Exception as exc:  # noqa: BLE001 - any SDK problem falls back to REST
            logger.warning("SDK call failed (%s): %s", model_name, self.redact(str(exc))[:180])
            return ""

    def __generate_with_rest(self, prompt: str, model_name: str) -> str:
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.__temperature,
                "responseMimeType": "application/json",
            },
        }).encode("utf-8")
        request = urllib.request.Request(
            self.REST_URL.format(model=model_name, key=self.__key()),
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.__timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
            parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            return parts[0].get("text", "") if parts else ""
        except Exception as exc:
            detail = self.redact(str(exc))[:180]
            logger.warning("REST call failed (%s): %s", model_name, detail)
            raise RuntimeError(detail) from None

    @staticmethod
    def __first_candidate_text(response: Any) -> str:
        for candidate in getattr(response, "candidates", None) or []:
            for part in getattr(getattr(candidate, "content", None), "parts", None) or []:
                if getattr(part, "text", None):
                    return str(part.text)
        return ""
