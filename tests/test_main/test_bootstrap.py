from __future__ import annotations

import builtins

from radaragent.main import ensure_admin_user
from radaragent.storage.db import Database


def test_ensure_admin_prompts_when_no_users(tmp_path, monkeypatch):
    db = Database(tmp_path / "b.db")
    db.init_schema()
    answers = iter(["admin@x.com", "zh"])
    monkeypatch.setattr(builtins, "input", lambda *_a: next(answers))
    monkeypatch.setattr("radaragent.main.getpass", lambda *_a: "supersecret")
    ensure_admin_user(db)
    n = db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    assert n == 1
    db.close()


def test_ensure_admin_noop_when_users_exist(tmp_path, monkeypatch):
    db = Database(tmp_path / "b.db")
    db.init_schema()
    from radaragent.users.auth import register

    register(db, "a@b.com", "hunter2pass")

    def boom(*_a):
        raise AssertionError("should not prompt")

    monkeypatch.setattr(builtins, "input", boom)
    ensure_admin_user(db)  # must not raise / not prompt
    db.close()
