from __future__ import annotations

from datetime import UTC, datetime, timedelta

from radaragent.users.sessions import SessionStore


def test_create_and_resolve():
    s = SessionStore(ttl_days=30)
    token = s.create_session(user_id=7)
    assert isinstance(token, str) and len(token) >= 32
    assert s.resolve(token) == 7


def test_resolve_unknown_token():
    assert SessionStore().resolve("nope") is None


def test_revoke():
    s = SessionStore()
    t = s.create_session(1)
    s.revoke(t)
    assert s.resolve(t) is None


def test_expired_token_returns_none():
    s = SessionStore(ttl_days=30)
    t = s.create_session(1)
    s._sessions[t] = (1, datetime.now(tz=UTC) - timedelta(seconds=1))
    assert s.resolve(t) is None
