"""SafetyCheck: the conservative keyword check on the optional reflection."""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import ClassVar


class SafetyCheck:
    """Looks for crisis language in the reflection text.

    The check only answers True or False. The text itself is never stored,
    scored or sent to the AI. Keywords can give false positives and false
    negatives, so the app never claims to assess safety: a True result just
    shows the support contacts more prominently.

    The same patterns are shared with the browser (``Questionnaire.public_config``)
    so the page can show support immediately while the student is typing.
    """

    PATTERNS: ClassVar[list[str]] = [
        r"\bsuicid(?:e|al)\b",
        r"\bself[ -]?harm(?:ing)?\b",
        r"\b(?:kill|hurt|harm|cut)(?:ing)? myself\b",
        r"\b(?:end|take) my (?:own )?life\b",
        r"\b(?:want|wish|going|plan|planning) to die\b",
        r"\b(?:cannot|can't|dont|don't) (?:go on|keep myself safe|want to live)\b",
        r"\bbetter off dead\b",
        r"\b(?:took|taken|take) an overdose\b",
    ]

    def __init__(self, patterns: Iterable[str] | None = None) -> None:
        source = tuple(patterns) if patterns is not None else tuple(self.PATTERNS)
        self.__patterns = tuple(re.compile(pattern) for pattern in source)

    def is_flagged(self, text: object) -> bool:
        """True when any pattern matches the (lower-cased) reflection text."""
        cleaned = str(text or "").lower().replace("’", "'")
        return any(pattern.search(cleaned) for pattern in self.__patterns)
