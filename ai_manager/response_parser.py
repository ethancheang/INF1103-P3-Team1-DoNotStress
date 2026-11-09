"""ResponseParser: turns Gemini's raw text reply into a JSON object."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


class ResponseParser:
    """Extracts one JSON object from a model reply.

    Gemini is asked for bare JSON, but a reply wrapped in markdown code
    fences is still accepted. Anything that is not a JSON object gives None,
    which the AI Manager treats as a malformed response and retries.
    """

    _FENCE = "```"

    def parse(self, raw: Any) -> dict[str, Any] | None:
        """The reply as a dict, or None when it is not a JSON object."""
        if isinstance(raw, Mapping):
            return dict(raw)
        if not isinstance(raw, str):
            return None
        try:
            data = json.loads(self._strip_fences(raw.strip()))
        except json.JSONDecodeError:
            return None
        return data if isinstance(data, dict) else None

    def _strip_fences(self, text: str) -> str:
        """Remove a leading ```json line and a trailing ``` line, if present."""
        if not text.startswith(self._FENCE):
            return text
        lines = text.splitlines()
        if lines[0].startswith(self._FENCE):
            lines = lines[1:]
        if lines and lines[-1].startswith(self._FENCE):
            lines = lines[:-1]
        return "\n".join(lines).strip()
