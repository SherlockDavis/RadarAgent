from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta


class SessionStore:
    """In-memory token -> (user_id, expires_at).

    Daemon restart drops sessions (single-user scope makes that acceptable).
    The dict-backed API is the seam: a future SQLite-backed store only needs
    to reimplement create/resolve/revoke with the same signatures.
    """

    def __init__(self, ttl_days: int = 30) -> None:
        self._ttl = timedelta(days=ttl_days)
        self._sessions: dict[str, tuple[int, datetime]] = {}

    def create_session(self, user_id: int) -> str:
        token = secrets.token_urlsafe(32)
        self._sessions[token] = (user_id, datetime.now(tz=UTC) + self._ttl)
        return token

    def resolve(self, token: str) -> int | None:
        entry = self._sessions.get(token)
        if entry is None:
            return None
        user_id, expires_at = entry
        if datetime.now(tz=UTC) >= expires_at:
            del self._sessions[token]
            return None
        return user_id

    def revoke(self, token: str) -> None:
        self._sessions.pop(token, None)
