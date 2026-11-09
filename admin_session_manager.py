"""AdminSessionManager: server-side admin tokens and login rate limiting.

SRP: only admin sign-in state. The route never trusts a role from the client.
"""

from __future__ import annotations

import secrets
import time
from threading import RLock

from werkzeug.security import check_password_hash


class AdminSessionManager:
    """Server-side tokens so logout/expiry revoke access even if a cookie is replayed."""

    USERNAME = "admin"
    # Fixed coursework/demo account. Only the hash lives in server code.
    # Password: DoNotStress2026!
    PASSWORD_HASH = (
        "scrypt:32768:8:1$aGX2K45NJqtPeR8c$"
        "bba912cd6b6f7fd252fb5cdd79f5ebebcccde0c7da7d19f7b3bc11cefc2a0bda6bd1c2468761884d12d3605b5aa07566b7c4878512db33e5bf033dafd83bca74"
    )

    def __init__(
        self,
        *,
        max_attempts: int = 5,
        window_seconds: int = 300,
        session_seconds: int = 1800,
    ) -> None:
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds
        self._session_seconds = session_seconds
        self._sessions: dict[str, float] = {}
        self._attempts: dict[str, list[float]] = {}
        self._lock = RLock()

    def is_admin(self, flask_session) -> bool:
        token = flask_session.get("admin_token")
        with self._lock:
            expires = self._sessions.get(token, 0)
            if expires > time.monotonic():
                return True
            self._sessions.pop(token, None)
        flask_session.pop("admin_token", None)
        return False

    def revoke(self, flask_session) -> None:
        with self._lock:
            self._sessions.pop(flask_session.pop("admin_token", None), None)

    def expire(self) -> None:
        """Drop expired admin tokens and old login attempts."""
        now = time.monotonic()
        with self._lock:
            for key in [key for key, expiry in self._sessions.items() if expiry <= now]:
                del self._sessions[key]
            for key in list(self._attempts):
                self._attempts[key] = [
                    stamp
                    for stamp in self._attempts[key]
                    if stamp > now - self._window_seconds
                ]
                if not self._attempts[key]:
                    del self._attempts[key]

    def record_attempt(self, address: str) -> bool:
        """Record one attempt. Returns True if the address is already locked out."""
        with self._lock:
            attempts = self._attempts.setdefault(address, [])
            if len(attempts) >= self._max_attempts:
                return True
            attempts.append(time.monotonic())
        return False

    def clear_attempts(self, address: str) -> None:
        with self._lock:
            self._attempts.pop(address, None)

    def grant(self, flask_session) -> None:
        """Issue a new admin token and rotate the CSRF token."""
        self.revoke(flask_session)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._sessions[token] = time.monotonic() + self._session_seconds
        flask_session["admin_token"] = token
        flask_session["csrf_token"] = secrets.token_urlsafe(32)

    def check_password(self, username: object, password: object) -> bool:
        valid = isinstance(password, str) and len(password) <= 256 and check_password_hash(
            self.PASSWORD_HASH, password
        )
        return username == self.USERNAME and valid
