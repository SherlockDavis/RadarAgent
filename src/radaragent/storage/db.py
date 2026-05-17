from __future__ import annotations

import sqlite3
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    email           TEXT UNIQUE NOT NULL,
    password_hash   TEXT NOT NULL,
    output_language TEXT NOT NULL DEFAULT 'zh',
    is_admin        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    interest_profile TEXT NOT NULL,
    filter_json      TEXT NOT NULL,
    schedule         TEXT NOT NULL,
    channels_json    TEXT NOT NULL,
    format           TEXT NOT NULL DEFAULT 'digest',
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS article_scores (
    article_id      TEXT NOT NULL,
    subscription_id INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    relevance_score REAL NOT NULL,
    summary         TEXT NOT NULL,
    tags_json       TEXT NOT NULL,
    key_insight     TEXT,
    scored_at       TEXT NOT NULL,
    PRIMARY KEY (article_id, subscription_id)
);

CREATE TABLE IF NOT EXISTS digests (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    subscription_id  INTEGER NOT NULL REFERENCES subscriptions(id) ON DELETE CASCADE,
    date             TEXT NOT NULL,
    content          TEXT NOT NULL,
    article_ids_json TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    UNIQUE (subscription_id, date)
);
"""


class Database:
    """Thin SQLite wrapper. Owns one connection; DAO modules borrow it."""

    def __init__(self, path: str | Path) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(p), check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    def init_schema(self) -> None:
        self.connection.executescript(_SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
