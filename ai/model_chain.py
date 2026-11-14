"""Named Gemini models to try, preferred first. This is data, not a class.

Kept in its own module so the test double can use the same default chain
without importing the live provider.
"""

from __future__ import annotations

# Named models only, newest first. No moving alias such as -latest.
DEFAULT_MODEL_CHAIN: tuple[str, ...] = (
    "gemini-3.6-flash",
    "gemini-3.5-flash",
    "gemini-3.5-flash-lite",
)

