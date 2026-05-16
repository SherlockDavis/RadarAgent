from __future__ import annotations

from radaragent.storage.db import Database


def test_init_schema_creates_all_tables(tmp_path):
    db = Database(tmp_path / "x.db")
    db.init_schema()
    names = {
        row[0] for row in db.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"users", "subscriptions", "article_scores", "digests"} <= names
    db.close()


def test_init_schema_is_idempotent(tmp_path):
    path = tmp_path / "y.db"
    Database(path).init_schema()
    db2 = Database(path)
    db2.init_schema()  # must not raise
    db2.close()


def test_foreign_keys_enabled(db):
    assert db.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
