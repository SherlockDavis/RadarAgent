from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

import bcrypt

from radaragent.storage.db import Database
from radaragent.users.models import User

_MIN_PASSWORD_LEN = 8


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _row_to_user(row: sqlite3.Row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        output_language=row["output_language"],
        is_admin=bool(row["is_admin"]),
        created_at=row["created_at"],
    )


def register(db: Database, email: str, password: str, output_language: str = "zh") -> User:
    if len(password) < _MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LEN} characters")
    conn = db.connection
    exists = conn.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone()
    if exists:
        raise ValueError(f"email {email!r} already registered")
    is_first = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0
    now = datetime.now(tz=UTC).isoformat()
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, output_language, is_admin, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (email, hash_password(password), output_language, 1 if is_first else 0, now),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    return _row_to_user(row)


def authenticate(db: Database, email: str, password: str) -> User | None:
    row = db.connection.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return _row_to_user(row)


def get_user(db: Database, user_id: int) -> User | None:
    row = db.connection.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return _row_to_user(row) if row else None
