from __future__ import annotations

import pytest

from radaragent.users.auth import authenticate, hash_password, register, verify_password


def test_hash_roundtrip():
    h = hash_password("hunter2pass")
    assert h != "hunter2pass"
    assert verify_password("hunter2pass", h)
    assert not verify_password("wrong", h)


def test_register_then_authenticate(db):
    user = register(db, "a@b.com", "hunter2pass", output_language="zh")
    assert user.id is not None
    assert user.email == "a@b.com"
    got = authenticate(db, "a@b.com", "hunter2pass")
    assert got is not None and got.id == user.id


def test_authenticate_wrong_password(db):
    register(db, "a@b.com", "hunter2pass")
    assert authenticate(db, "a@b.com", "nope") is None


def test_authenticate_unknown_email(db):
    assert authenticate(db, "ghost@b.com", "x") is None


def test_register_duplicate_email_rejected(db):
    register(db, "a@b.com", "hunter2pass")
    with pytest.raises(ValueError, match="already registered"):
        register(db, "a@b.com", "another1pass")


def test_register_short_password_rejected(db):
    with pytest.raises(ValueError, match="at least 8"):
        register(db, "a@b.com", "short")


def test_first_user_is_admin(db):
    first = register(db, "admin@b.com", "hunter2pass")
    second = register(db, "user@b.com", "hunter2pass")
    assert first.is_admin is True
    assert second.is_admin is False
