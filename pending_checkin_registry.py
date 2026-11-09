"""PendingCheckinRegistry: in-memory pending results and submission claims.

Records stay in server memory, never inside Flask's client-readable session cookie.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from threading import RLock
from typing import Any


class PendingCheckinRegistry:
    """Temporary check-in results and the claim that stops a double submit."""

    def __init__(self) -> None:
        self._pending: dict[str, dict[str, Any]] = {}
        # csrf token -> {fingerprint, record_id} for the submission in this session.
        self._submissions: dict[str, dict[str, Any]] = {}
        self._lock = RLock()

    @contextmanager
    def locked(self):
        """Hold the registry lock across a check-and-save so a double submit is one row."""
        with self._lock:
            yield

    def clear(self, flask_session) -> None:
        """Drop the in-memory result for this session. Does not delete a saved record."""
        with self._lock:
            self._pending.pop(flask_session.pop("checkin_token", None), None)

    def current(self, flask_session) -> dict[str, Any] | None:
        with self._lock:
            return self._pending.get(flask_session.get("checkin_token"))

    def matched_id(self, flask_session, fingerprint: str) -> str | None:
        """Id of the pending row for this submission, if this session already saved one."""
        record_id = flask_session.get("pending_record_id")
        if (
            flask_session.get("pending_fingerprint") == fingerprint
            and isinstance(record_id, str)
            and record_id.strip()
        ):
            return record_id.strip()
        with self._lock:
            claim = self._submissions.get(flask_session.get("csrf_token"))
        if isinstance(claim, dict) and claim.get("fingerprint") == fingerprint:
            found = claim.get("record_id")
            if isinstance(found, str) and found.strip():
                return found.strip()
        return None

    def remember(
        self,
        flask_session,
        fingerprint: str,
        record_id: str,
        *,
        pending_save: bool,
    ) -> None:
        """Keep the submission id. Pending saves also go in the session cookie."""
        token = flask_session.get("csrf_token")
        if token:
            with self._lock:
                self._submissions[token] = {
                    "fingerprint": fingerprint,
                    "record_id": record_id,
                }
        if pending_save:
            flask_session["pending_fingerprint"] = fingerprint
            flask_session["pending_record_id"] = record_id
        else:
            flask_session.pop("pending_fingerprint", None)
            flask_session.pop("pending_record_id", None)

    def store_result(self, token: str, record: dict[str, Any], *, saved: bool) -> None:
        with self._lock:
            self._pending[token] = {
                "record": record,
                "saved": saved,
                "created": time.monotonic(),
            }

    def forget_csrf(self, csrf_token: str | None) -> None:
        if not csrf_token:
            return
        with self._lock:
            self._submissions.pop(csrf_token, None)

    def expire(self, ttl_seconds: int) -> None:
        cutoff = time.monotonic() - ttl_seconds
        with self._lock:
            for key in [key for key, item in self._pending.items() if item["created"] < cutoff]:
                del self._pending[key]

    @property
    def pending(self) -> dict[str, dict[str, Any]]:
        """Exposed so the app can still show the in-memory map on app.extensions."""
        return self._pending

    @property
    def submissions(self) -> dict[str, dict[str, Any]]:
        return self._submissions
