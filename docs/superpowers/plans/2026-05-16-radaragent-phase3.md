# RadarAgent Phase 3 Implementation Plan — User-ization + Backend Services

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the single-tenant pipeline into a multi-user, multi-subscription backend (SQLite + auth + per-subscription scoring + ServiceAPI + per-subscription digest jobs + EmailNotifier), all CLI-triggerable; no web pages.

**Architecture:** SQLite (`db.py` DAO layer) holds users / subscriptions / per-(article,subscription) scores / digest history; Chroma still holds the single global article vectors, joined by `article_id = sha1(url)`. A `ServiceAPI` facade exposes `generate_digest` / `query` (`search` signature-only). APScheduler keeps per-plugin fetch jobs and gains per-subscription digest jobs. First daemon start with an empty `users` table bootstraps an admin account interactively.

**Tech Stack:** Python 3.11, asyncio, sqlite3 (stdlib), bcrypt, aiosmtplib, pydantic v2, APScheduler, Chroma, pytest + pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-05-16-radaragent-phase3-design.md`. The 5 open questions are resolved to their recommended defaults: (1) blocking interactive bootstrap; (2) `query` spans all of a user's subscription-hit articles; (3) `search` signature-only; (4) digest history context default 5, settings-configurable; (5) in-memory `SessionStore` with a persistence seam.

**Conventions:**
- Conda env Python: `C:\Users\32586\.conda\envs\RadarAgent\python.exe`. Run pytest as `python -m pytest`.
- Commits: Conventional Commits, SSH-signed (global config already on), end body with `Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>`. Scope enum: `plugin/scheduler/processor/rag/output/config/provider/service`.
- All timestamps stored as ISO-8601 UTC strings.
- `from __future__ import annotations` at top of every new module (matches existing code).
- After each task: `python -m ruff check src tests && python -m ruff format --check src tests && python -m mypy src` must pass before commit.

---

## File Structure

| File | Responsibility |
|---|---|
| `tests/conftest.py` | shared fixtures: temp SQLite db, fake LLM/embedding providers, in-memory Chroma |
| `src/radaragent/storage/db.py` | SQLite connection, schema DDL, low-level row helpers |
| `src/radaragent/users/models.py` | `User`, `UserCreate` pydantic models |
| `src/radaragent/users/auth.py` | bcrypt hash/verify, `register`, `authenticate` |
| `src/radaragent/users/sessions.py` | `SessionStore` (in-memory + persistence seam) |
| `src/radaragent/users/__init__.py` | package exports |
| `src/radaragent/subscriptions/models.py` | `SubscriptionFilter`, `Subscription`, `SubscriptionCreate`, `Channel` |
| `src/radaragent/subscriptions/crud.py` | subscription + user + article_score + digest DAO |
| `src/radaragent/subscriptions/scheduling.py` | register/reschedule per-subscription digest jobs |
| `src/radaragent/subscriptions/__init__.py` | package exports |
| `src/radaragent/providers/notifier/base.py` | `Notifier` ABC |
| `src/radaragent/providers/notifier/email.py` | `EmailNotifier` (aiosmtplib) |
| `src/radaragent/providers/notifier/__init__.py` | package exports |
| `src/radaragent/service/digest.py` | digest orchestration |
| `src/radaragent/service/query.py` | RAG Q&A orchestration |
| `src/radaragent/service/api.py` | `ServiceAPI` facade + `SearchFilters` placeholder |
| `src/radaragent/service/__init__.py` | package exports |
| `src/radaragent/config/loader.py` (modify) | drop `InterestsConfig`; add `SMTPConfig`, `AuthConfig`, `storage.sqlite_path` |
| `src/radaragent/config/__init__.py` (modify) | update exports |
| `src/radaragent/processor/llm_filter.py` | per-subscription scoring sink factory (moved out of main.py) |
| `src/radaragent/scheduler/scheduler.py` (modify) | add digest-job registration alongside plugin jobs |
| `src/radaragent/main.py` (modify) | first-run bootstrap, wiring, CLI subcommands |
| `config/settings.yaml` (modify) | drop interests refs; add smtp/auth/sqlite_path |
| `config/interests.yaml` (delete) | migrated into DB |
| `pyproject.toml` (modify) | add `bcrypt`, `aiosmtplib`; fix description |
| `CHANGELOG.md` (modify) | record Phase 3 |

---

## Task 1: Test scaffolding + dependency + metadata

**Files:**
- Create: `tests/__init__.py`, `tests/conftest.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Add runtime deps and fix description**

In `pyproject.toml`, change line 8:
```toml
description = "A 24/7 multi-user personal intelligence web platform"
```
In the `dependencies` list (after `"chromadb>=0.5",`) add:
```toml
    # Phase 3 — users, subscriptions, email
    "bcrypt>=4.1",
    "aiosmtplib>=3.0",
```

- [ ] **Step 2: Create empty test package + conftest**

Create `tests/__init__.py` (empty file).

Create `tests/conftest.py`:
```python
from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from radaragent.storage.db import Database


@pytest.fixture
def db(tmp_path) -> Iterator[Database]:
    database = Database(tmp_path / "test.db")
    database.init_schema()
    yield database
    database.close()


@pytest.fixture
def raw_conn(db: Database) -> sqlite3.Connection:
    return db.connection
```

- [ ] **Step 3: Install deps into the env**

Run: `C:\Users\32586\.conda\envs\RadarAgent\python.exe -m pip install -e ".[dev]" bcrypt aiosmtplib`
Expected: ends with `Successfully installed ... aiosmtplib ... bcrypt ...`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml tests/__init__.py tests/conftest.py
git commit -m "chore: add bcrypt + aiosmtplib deps and test scaffold

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 2: SQLite `Database` — connection + schema

**Files:**
- Create: `src/radaragent/storage/db.py`
- Test: `tests/test_storage/test_db.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_storage/__init__.py` (empty).
Create `tests/test_storage/test_db.py`:
```python
from __future__ import annotations

from radaragent.storage.db import Database


def test_init_schema_creates_all_tables(tmp_path):
    db = Database(tmp_path / "x.db")
    db.init_schema()
    names = {
        row[0]
        for row in db.connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_storage/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.storage.db'`

- [ ] **Step 3: Write minimal implementation**

Create `src/radaragent/storage/db.py`:
```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_storage/test_db.py -v`
Expected: 3 passed

- [ ] **Step 5: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
Expected: no errors
```bash
git add src/radaragent/storage/db.py tests/test_storage/
git commit -m "feat(storage): add SQLite Database with users/subscriptions schema

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 3: User models + auth (bcrypt)

**Files:**
- Create: `src/radaragent/users/__init__.py`, `src/radaragent/users/models.py`, `src/radaragent/users/auth.py`
- Test: `tests/test_users/test_auth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_users/__init__.py` (empty).
Create `tests/test_users/test_auth.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_users/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.users'`

- [ ] **Step 3: Write minimal implementation**

Create `src/radaragent/users/models.py`:
```python
from __future__ import annotations

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str
    output_language: str = "zh"


class User(BaseModel):
    id: int
    email: str
    output_language: str = "zh"
    is_admin: bool = False
    created_at: str
```

`EmailStr` needs `email-validator`. Instead of adding a dep, replace `EmailStr` with `str` in both places (validation is done by `register`). Final `models.py`:
```python
from __future__ import annotations

from pydantic import BaseModel


class UserCreate(BaseModel):
    email: str
    password: str
    output_language: str = "zh"


class User(BaseModel):
    id: int
    email: str
    output_language: str = "zh"
    is_admin: bool = False
    created_at: str
```

Create `src/radaragent/users/auth.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime

import bcrypt

from radaragent.storage.db import Database
from radaragent.users.models import User

_MIN_PASSWORD_LEN = 8


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))


def _row_to_user(row) -> User:
    return User(
        id=row["id"],
        email=row["email"],
        output_language=row["output_language"],
        is_admin=bool(row["is_admin"]),
        created_at=row["created_at"],
    )


def register(
    db: Database, email: str, password: str, output_language: str = "zh"
) -> User:
    if len(password) < _MIN_PASSWORD_LEN:
        raise ValueError(f"password must be at least {_MIN_PASSWORD_LEN} characters")
    conn = db.connection
    exists = conn.execute(
        "SELECT 1 FROM users WHERE email = ?", (email,)
    ).fetchone()
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
    row = conn.execute(
        "SELECT * FROM users WHERE id = ?", (cur.lastrowid,)
    ).fetchone()
    return _row_to_user(row)


def authenticate(db: Database, email: str, password: str) -> User | None:
    row = db.connection.execute(
        "SELECT * FROM users WHERE email = ?", (email,)
    ).fetchone()
    if row is None or not verify_password(password, row["password_hash"]):
        return None
    return _row_to_user(row)
```

Create `src/radaragent/users/__init__.py`:
```python
from radaragent.users.auth import authenticate, hash_password, register, verify_password
from radaragent.users.models import User, UserCreate

__all__ = [
    "User",
    "UserCreate",
    "authenticate",
    "hash_password",
    "register",
    "verify_password",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_users/test_auth.py -v`
Expected: 7 passed

- [ ] **Step 5: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
```bash
git add src/radaragent/users/ tests/test_users/
git commit -m "feat: add User model + bcrypt auth (register/authenticate)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 4: SessionStore (in-memory + persistence seam)

**Files:**
- Create: `src/radaragent/users/sessions.py`
- Modify: `src/radaragent/users/__init__.py`
- Test: `tests/test_users/test_sessions.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_users/test_sessions.py`:
```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_users/test_sessions.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.users.sessions'`

- [ ] **Step 3: Write minimal implementation**

Create `src/radaragent/users/sessions.py`:
```python
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
```

Append to `src/radaragent/users/__init__.py` imports and `__all__`:
```python
from radaragent.users.sessions import SessionStore
```
and add `"SessionStore",` to `__all__` (keep list alphabetically sorted to satisfy RUF022).

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_users/test_sessions.py -v`
Expected: 4 passed

- [ ] **Step 5: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
```bash
git add src/radaragent/users/
git commit -m "feat: add in-memory SessionStore with ttl + persistence seam

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 5: Subscription models (pydantic validation)

**Files:**
- Create: `src/radaragent/subscriptions/__init__.py`, `src/radaragent/subscriptions/models.py`
- Test: `tests/test_subscriptions/test_models.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_subscriptions/__init__.py` (empty).
Create `tests/test_subscriptions/test_models.py`:
```python
from __future__ import annotations

import pytest
from pydantic import ValidationError

from radaragent.subscriptions.models import Channel, SubscriptionCreate, SubscriptionFilter


def test_filter_defaults():
    f = SubscriptionFilter()
    assert f.min_score == 6.0
    assert f.keywords_boost == []
    assert f.source_whitelist == []


def test_filter_min_score_range():
    with pytest.raises(ValidationError):
        SubscriptionFilter(min_score=11)
    with pytest.raises(ValidationError):
        SubscriptionFilter(min_score=-1)


def test_subscription_create_valid():
    sub = SubscriptionCreate(
        user_id=1,
        name="AI news",
        interest_profile="LLM agents and inference infra",
        filter=SubscriptionFilter(min_score=7),
        schedule="0 8 * * *",
        channels=[Channel(type="email", config={"to": "me@x.com"})],
        format="digest",
    )
    assert sub.schedule == "0 8 * * *"


def test_subscription_create_bad_cron_rejected():
    with pytest.raises(ValidationError, match="cron"):
        SubscriptionCreate(
            user_id=1,
            name="x",
            interest_profile="y",
            schedule="not a cron",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        )


def test_subscription_create_bad_format_rejected():
    with pytest.raises(ValidationError):
        SubscriptionCreate(
            user_id=1,
            name="x",
            interest_profile="y",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
            format="bogus",
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_subscriptions/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.subscriptions'`

- [ ] **Step 3: Write minimal implementation**

Create `src/radaragent/subscriptions/models.py`:
```python
from __future__ import annotations

from typing import Any, Literal

from apscheduler.triggers.cron import CronTrigger
from pydantic import BaseModel, Field, field_validator


class SubscriptionFilter(BaseModel):
    keywords_boost: list[str] = Field(default_factory=list)
    keywords_ignore: list[str] = Field(default_factory=list)
    min_score: float = 6.0
    source_whitelist: list[str] = Field(default_factory=list)

    @field_validator("min_score")
    @classmethod
    def _score_range(cls, v: float) -> float:
        if not 0.0 <= v <= 10.0:
            raise ValueError("min_score must be in [0, 10]")
        return v


class Channel(BaseModel):
    type: Literal["email"]
    config: dict[str, Any]


class SubscriptionCreate(BaseModel):
    user_id: int
    name: str
    interest_profile: str
    filter: SubscriptionFilter = Field(default_factory=SubscriptionFilter)
    schedule: str = "0 8 * * *"
    channels: list[Channel]
    format: Literal["digest", "alert", "summary"] = "digest"
    enabled: bool = True

    @field_validator("schedule")
    @classmethod
    def _valid_cron(cls, v: str) -> str:
        try:
            CronTrigger.from_crontab(v)
        except (ValueError, KeyError) as exc:
            raise ValueError(f"invalid cron expression: {v!r}") from exc
        return v


class Subscription(SubscriptionCreate):
    id: int
    created_at: str
```

Create `src/radaragent/subscriptions/__init__.py`:
```python
from radaragent.subscriptions.models import (
    Channel,
    Subscription,
    SubscriptionCreate,
    SubscriptionFilter,
)

__all__ = [
    "Channel",
    "Subscription",
    "SubscriptionCreate",
    "SubscriptionFilter",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_subscriptions/test_models.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
```bash
git add src/radaragent/subscriptions/ tests/test_subscriptions/
git commit -m "feat: add Subscription pydantic models with cron + score validation

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 6: Subscription + score + digest DAO

**Files:**
- Create: `src/radaragent/subscriptions/crud.py`
- Modify: `src/radaragent/subscriptions/__init__.py`
- Test: `tests/test_subscriptions/test_crud.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_subscriptions/test_crud.py`:
```python
from __future__ import annotations

from radaragent.subscriptions.crud import (
    create_subscription,
    get_subscription,
    list_enabled_subscriptions,
    record_digest,
    record_score,
    scored_article_ids_for_user,
    set_enabled,
    todays_scored_articles,
)
from radaragent.subscriptions.models import Channel, SubscriptionCreate
from radaragent.users.auth import register


def _sub(uid: int, **kw) -> SubscriptionCreate:
    base = dict(
        user_id=uid,
        name="AI",
        interest_profile="LLM infra",
        schedule="0 8 * * *",
        channels=[Channel(type="email", config={"to": "me@x.com"})],
    )
    base.update(kw)
    return SubscriptionCreate(**base)


def test_create_and_get(db):
    u = register(db, "a@b.com", "hunter2pass")
    sub = create_subscription(db, _sub(u.id))
    assert sub.id is not None
    fetched = get_subscription(db, sub.id)
    assert fetched is not None
    assert fetched.name == "AI"
    assert fetched.filter.min_score == 6.0


def test_list_enabled_excludes_disabled(db):
    u = register(db, "a@b.com", "hunter2pass")
    s1 = create_subscription(db, _sub(u.id, name="on"))
    s2 = create_subscription(db, _sub(u.id, name="off"))
    set_enabled(db, s2.id, False)
    enabled = list_enabled_subscriptions(db)
    assert [s.id for s in enabled] == [s1.id]


def test_record_score_idempotent(db):
    u = register(db, "a@b.com", "hunter2pass")
    s = create_subscription(db, _sub(u.id))
    record_score(db, "aid1", s.id, 8.0, "sum", ["t"], "insight")
    record_score(db, "aid1", s.id, 9.0, "sum2", ["t"], "insight2")  # upsert
    rows = todays_scored_articles(db, s.id)
    assert len(rows) == 1
    assert rows[0]["relevance_score"] == 9.0


def test_scored_article_ids_for_user_spans_subscriptions(db):
    u = register(db, "a@b.com", "hunter2pass")
    s1 = create_subscription(db, _sub(u.id, name="a"))
    s2 = create_subscription(db, _sub(u.id, name="b"))
    record_score(db, "aid1", s1.id, 8.0, "x", [], None)
    record_score(db, "aid2", s2.id, 7.0, "y", [], None)
    assert scored_article_ids_for_user(db, u.id) == {"aid1", "aid2"}


def test_record_digest_upsert(db):
    u = register(db, "a@b.com", "hunter2pass")
    s = create_subscription(db, _sub(u.id))
    record_digest(db, s.id, "2026-05-16", "body v1", ["aid1"])
    record_digest(db, s.id, "2026-05-16", "body v2", ["aid1", "aid2"])
    row = db.connection.execute(
        "SELECT content FROM digests WHERE subscription_id=? AND date=?",
        (s.id, "2026-05-16"),
    ).fetchone()
    assert row["content"] == "body v2"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_subscriptions/test_crud.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.subscriptions.crud'`

- [ ] **Step 3: Write minimal implementation**

Create `src/radaragent/subscriptions/crud.py`:
```python
from __future__ import annotations

import json
from datetime import UTC, datetime

from radaragent.storage.db import Database
from radaragent.subscriptions.models import Subscription, SubscriptionCreate, SubscriptionFilter


def _row_to_subscription(row) -> Subscription:
    return Subscription(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        interest_profile=row["interest_profile"],
        filter=SubscriptionFilter.model_validate_json(row["filter_json"]),
        schedule=row["schedule"],
        channels=json.loads(row["channels_json"]),
        format=row["format"],
        enabled=bool(row["enabled"]),
        created_at=row["created_at"],
    )


def create_subscription(db: Database, data: SubscriptionCreate) -> Subscription:
    now = datetime.now(tz=UTC).isoformat()
    conn = db.connection
    cur = conn.execute(
        "INSERT INTO subscriptions (user_id, name, interest_profile, filter_json, "
        "schedule, channels_json, format, enabled, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            data.user_id,
            data.name,
            data.interest_profile,
            data.filter.model_dump_json(),
            data.schedule,
            json.dumps([c.model_dump() for c in data.channels]),
            data.format,
            1 if data.enabled else 0,
            now,
        ),
    )
    conn.commit()
    return get_subscription(db, cur.lastrowid)  # type: ignore[arg-type, return-value]


def get_subscription(db: Database, sub_id: int) -> Subscription | None:
    row = db.connection.execute(
        "SELECT * FROM subscriptions WHERE id = ?", (sub_id,)
    ).fetchone()
    return _row_to_subscription(row) if row else None


def list_enabled_subscriptions(db: Database) -> list[Subscription]:
    rows = db.connection.execute(
        "SELECT * FROM subscriptions WHERE enabled = 1 ORDER BY id"
    ).fetchall()
    return [_row_to_subscription(r) for r in rows]


def set_enabled(db: Database, sub_id: int, enabled: bool) -> None:
    db.connection.execute(
        "UPDATE subscriptions SET enabled = ? WHERE id = ?",
        (1 if enabled else 0, sub_id),
    )
    db.connection.commit()


def record_score(
    db: Database,
    article_id: str,
    subscription_id: int,
    relevance_score: float,
    summary: str,
    tags: list[str],
    key_insight: str | None,
) -> None:
    db.connection.execute(
        "INSERT INTO article_scores (article_id, subscription_id, relevance_score, "
        "summary, tags_json, key_insight, scored_at) VALUES (?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(article_id, subscription_id) DO UPDATE SET "
        "relevance_score=excluded.relevance_score, summary=excluded.summary, "
        "tags_json=excluded.tags_json, key_insight=excluded.key_insight, "
        "scored_at=excluded.scored_at",
        (
            article_id,
            subscription_id,
            relevance_score,
            summary,
            json.dumps(tags),
            key_insight,
            datetime.now(tz=UTC).isoformat(),
        ),
    )
    db.connection.commit()


def has_score(db: Database, article_id: str, subscription_id: int) -> bool:
    return (
        db.connection.execute(
            "SELECT 1 FROM article_scores WHERE article_id=? AND subscription_id=?",
            (article_id, subscription_id),
        ).fetchone()
        is not None
    )


def todays_scored_articles(db: Database, subscription_id: int, date: str | None = None):
    if date is None:
        rows = db.connection.execute(
            "SELECT * FROM article_scores WHERE subscription_id=? "
            "ORDER BY relevance_score DESC",
            (subscription_id,),
        ).fetchall()
    else:
        rows = db.connection.execute(
            "SELECT * FROM article_scores WHERE subscription_id=? "
            "AND substr(scored_at,1,10)=? ORDER BY relevance_score DESC",
            (subscription_id, date),
        ).fetchall()
    return rows


def scored_article_ids_for_user(db: Database, user_id: int) -> set[str]:
    rows = db.connection.execute(
        "SELECT DISTINCT s2.article_id FROM article_scores s2 "
        "JOIN subscriptions sub ON sub.id = s2.subscription_id "
        "WHERE sub.user_id = ?",
        (user_id,),
    ).fetchall()
    return {r["article_id"] for r in rows}


def record_digest(
    db: Database,
    subscription_id: int,
    date: str,
    content: str,
    article_ids: list[str],
) -> None:
    db.connection.execute(
        "INSERT INTO digests (subscription_id, date, content, article_ids_json, "
        "created_at) VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT(subscription_id, date) DO UPDATE SET "
        "content=excluded.content, article_ids_json=excluded.article_ids_json, "
        "created_at=excluded.created_at",
        (
            subscription_id,
            date,
            content,
            json.dumps(article_ids),
            datetime.now(tz=UTC).isoformat(),
        ),
    )
    db.connection.commit()
```

Add to `src/radaragent/subscriptions/__init__.py` imports + `__all__` (keep sorted):
```python
from radaragent.subscriptions.crud import (
    create_subscription,
    get_subscription,
    has_score,
    list_enabled_subscriptions,
    record_digest,
    record_score,
    scored_article_ids_for_user,
    set_enabled,
    todays_scored_articles,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_subscriptions/test_crud.py -v`
Expected: 5 passed

- [ ] **Step 5: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
```bash
git add src/radaragent/subscriptions/ tests/test_subscriptions/test_crud.py
git commit -m "feat: add subscription/score/digest DAO

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 7: Config loader — drop interests, add SMTP/auth/sqlite

**Files:**
- Modify: `src/radaragent/config/loader.py`, `src/radaragent/config/__init__.py`
- Modify: `config/settings.yaml`
- Test: `tests/test_config/test_loader.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_config/__init__.py` (empty).
Create `tests/test_config/test_loader.py`:
```python
from __future__ import annotations

from radaragent.config import Settings, load_settings


def test_settings_has_smtp_auth_sqlite_defaults(tmp_path):
    yaml_text = """
llm:
  provider: openai
  api_key: dummy
storage:
  type: chroma
  sqlite_path: ./data/radaragent.db
"""
    p = tmp_path / "s.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    s = load_settings(p)
    assert s.storage.sqlite_path == "./data/radaragent.db"
    assert s.auth.session_ttl_days == 30
    assert s.smtp is None
    assert s.digest.history_context_size == 5


def test_settings_parses_smtp(tmp_path):
    yaml_text = """
llm:
  provider: openai
  api_key: dummy
smtp:
  host: smtp.example.com
  port: 587
  username: u
  password: p
  use_tls: true
  from_addr: bot@example.com
"""
    p = tmp_path / "s.yaml"
    p.write_text(yaml_text, encoding="utf-8")
    s = load_settings(p)
    assert s.smtp is not None
    assert s.smtp.host == "smtp.example.com"
    assert s.smtp.port == 587


def test_interests_config_removed():
    import radaragent.config as cfg

    assert not hasattr(cfg, "InterestsConfig")
    assert not hasattr(cfg, "load_interests")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config/test_loader.py -v`
Expected: FAIL — `AttributeError`/`ValidationError` (no `auth`/`smtp`/`digest`; `InterestsConfig` still present)

- [ ] **Step 3: Modify implementation**

In `src/radaragent/config/loader.py`:

Delete the `InterestsConfig` class (lines 61-67) and the `load_interests` function (lines 74-75).

Add these classes before `class Settings`:
```python
class SMTPConfig(BaseModel):
    host: str
    port: int = 587
    username: str
    password: str
    use_tls: bool = True
    from_addr: str


class AuthConfig(BaseModel):
    session_ttl_days: int = 30


class DigestConfig(BaseModel):
    history_context_size: int = 5
```

Change `StorageConfig` to add a field:
```python
class StorageConfig(BaseModel):
    type: str = "chroma"
    sqlite_path: str = "./data/radaragent.db"
    chroma: dict[str, Any] = Field(default_factory=dict)
    qdrant: dict[str, Any] = Field(default_factory=dict)
```

Change `Settings` to:
```python
class Settings(BaseModel):
    llm: LLMConfig
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    plugins: list[PluginConfig] = Field(default_factory=list)
    output: OutputConfig = Field(default_factory=OutputConfig)
    smtp: SMTPConfig | None = None
    auth: AuthConfig = Field(default_factory=AuthConfig)
    digest: DigestConfig = Field(default_factory=DigestConfig)
```

Replace `src/radaragent/config/__init__.py` entirely:
```python
from radaragent.config.loader import (
    AuthConfig,
    DigestConfig,
    PluginConfig,
    Settings,
    SMTPConfig,
    load_settings,
)

__all__ = [
    "AuthConfig",
    "DigestConfig",
    "PluginConfig",
    "SMTPConfig",
    "Settings",
    "load_settings",
]
```

- [ ] **Step 4: Update settings.yaml**

In `config/settings.yaml`, change the `storage:` block to add `sqlite_path` and replace the `output:` tail. Final bottom section:
```yaml
storage:
  type: chroma
  sqlite_path: ./data/radaragent.db
  chroma:
    persist_directory: ./data/chroma
```
Append at end of file (after plugins):
```yaml
auth:
  session_ttl_days: 30

digest:
  history_context_size: 5

# smtp: 取消注释并通过环境变量注入凭据后启用邮件推送
# smtp:
#   host: smtp.gmail.com
#   port: 587
#   username: ${SMTP_USERNAME}
#   password: ${SMTP_PASSWORD}
#   use_tls: true
#   from_addr: radaragent@example.com
```
Remove the existing `output:` block (lines 73-76) — `OutputConfig` keeps its defaults.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_config/test_loader.py -v`
Expected: 3 passed

- [ ] **Step 6: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
```bash
git add src/radaragent/config/ config/settings.yaml tests/test_config/
git commit -m "refactor(config): drop interests; add smtp/auth/digest/sqlite_path

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 8: Notifier ABC + EmailNotifier

**Files:**
- Create: `src/radaragent/providers/notifier/__init__.py`, `base.py`, `email.py`
- Test: `tests/test_providers/test_email.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_providers/__init__.py` (empty).
Create `tests/test_providers/test_email.py`:
```python
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from radaragent.config import SMTPConfig
from radaragent.providers.notifier import EmailNotifier


@pytest.fixture
def smtp_cfg() -> SMTPConfig:
    return SMTPConfig(
        host="smtp.x.com",
        port=587,
        username="u",
        password="p",
        use_tls=True,
        from_addr="bot@x.com",
    )


async def test_send_success(smtp_cfg):
    notifier = EmailNotifier(smtp_cfg)
    with patch("radaragent.providers.notifier.email.aiosmtplib.send", new=AsyncMock()) as m:
        ok = await notifier.send("hello body", {"to": "me@x.com"})
    assert ok is True
    assert m.await_count == 1


async def test_send_missing_recipient_returns_false(smtp_cfg):
    notifier = EmailNotifier(smtp_cfg)
    ok = await notifier.send("body", {})
    assert ok is False


async def test_send_smtp_error_returns_false(smtp_cfg):
    notifier = EmailNotifier(smtp_cfg)
    with patch(
        "radaragent.providers.notifier.email.aiosmtplib.send",
        new=AsyncMock(side_effect=RuntimeError("smtp down")),
    ):
        ok = await notifier.send("body", {"to": "me@x.com"})
    assert ok is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_providers/test_email.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.providers.notifier'`

- [ ] **Step 3: Write minimal implementation**

Create `src/radaragent/providers/notifier/base.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Notifier(ABC):
    """Delivery channel contract. Implementations never raise on send
    failure — they log and return False so one bad channel cannot abort a
    digest job."""

    @abstractmethod
    async def send(self, content: str, channel_config: dict[str, Any]) -> bool:
        """Deliver ``content`` per ``channel_config``; return success."""
```

Create `src/radaragent/providers/notifier/email.py`:
```python
from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Any

import aiosmtplib

from radaragent.config import SMTPConfig
from radaragent.providers.notifier.base import Notifier

logger = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    def __init__(self, cfg: SMTPConfig) -> None:
        self._cfg = cfg

    async def send(self, content: str, channel_config: dict[str, Any]) -> bool:
        to = channel_config.get("to")
        if not to:
            logger.warning("email channel_config missing 'to'; skipping")
            return False
        msg = EmailMessage()
        msg["From"] = self._cfg.from_addr
        msg["To"] = to
        msg["Subject"] = channel_config.get("subject", "RadarAgent 简报")
        msg.set_content(content)
        try:
            await aiosmtplib.send(
                msg,
                hostname=self._cfg.host,
                port=self._cfg.port,
                username=self._cfg.username,
                password=self._cfg.password,
                start_tls=self._cfg.use_tls,
            )
            return True
        except Exception:
            logger.exception("email send to %s failed", to)
            return False
```

Create `src/radaragent/providers/notifier/__init__.py`:
```python
from radaragent.providers.notifier.base import Notifier
from radaragent.providers.notifier.email import EmailNotifier

__all__ = ["EmailNotifier", "Notifier"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_providers/test_email.py -v`
Expected: 3 passed

- [ ] **Step 5: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
```bash
git add src/radaragent/providers/notifier/ tests/test_providers/
git commit -m "feat(provider): add Notifier ABC + EmailNotifier (aiosmtplib)

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 9: Per-subscription scoring sink (processor)

**Files:**
- Create: `src/radaragent/processor/__init__.py`, `src/radaragent/processor/llm_filter.py`
- Test: `tests/test_processor/test_llm_filter.py`

This moves scoring out of `main.py` and makes it per-subscription. The sink: URL dedup → embed + vector-dedup new articles into Chroma once → for each enabled subscription, score each new article (skip if `(article_id, sub_id)` already scored), persist scores ≥ `sub.filter.min_score`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_processor/__init__.py` (empty).
Create `tests/test_processor/test_llm_filter.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radaragent.processor.llm_filter import build_sink
from radaragent.storage import DedupChecker, ProcessedArticle, RawArticle
from radaragent.subscriptions.crud import create_subscription, todays_scored_articles
from radaragent.subscriptions.models import Channel, SubscriptionCreate, SubscriptionFilter
from radaragent.users.auth import register


class FakeLLM:
    def __init__(self, score: float = 8.0) -> None:
        self.calls = 0
        self._score = score

    async def score_and_summarize(self, article, profile, output_language):
        self.calls += 1
        return ProcessedArticle(
            raw=article,
            relevance_score=self._score,
            summary=f"sum::{article.title}",
            tags=["t"],
            key_insight="insight",
        )

    async def generate_digest(self, articles, context):
        return "digest"


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 3

    async def embed(self, text: str):
        return [float(len(text) % 7), 1.0, 2.0]

    async def embed_batch(self, texts):
        return [[float(len(t) % 7), 1.0, 2.0] for t in texts]


class FakePlugin:
    plugin_id = "fake"


def _raw(title: str, url: str) -> RawArticle:
    return RawArticle(
        title=title,
        url=url,
        content=f"body of {title}",
        source="fake",
        language="en",
        timestamp=datetime.now(tz=UTC),
    )


@pytest.fixture
def store(tmp_path):
    from radaragent.storage import RAGStore

    return RAGStore(persist_directory=tmp_path / "chroma")


async def test_sink_scores_per_enabled_subscription(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    s1 = create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s1",
            interest_profile="p1",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    llm = FakeLLM(score=8.0)
    sink = build_sink(llm, FakeEmbedder(), store, DedupChecker(store), db)
    await sink(FakePlugin(), [_raw("A", "http://x/a"), _raw("B", "http://x/b")])

    rows = todays_scored_articles(db, s1.id)
    assert len(rows) == 2
    assert llm.calls == 2


async def test_sink_low_score_not_persisted(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s1",
            interest_profile="p1",
            filter=SubscriptionFilter(min_score=9.0),
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    llm = FakeLLM(score=5.0)
    sink = build_sink(llm, FakeEmbedder(), store, DedupChecker(store), db)
    await sink(FakePlugin(), [_raw("A", "http://x/a")])
    rows = db.connection.execute("SELECT COUNT(*) FROM article_scores").fetchone()[0]
    assert rows == 0


async def test_sink_skips_already_scored_pair(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s1",
            interest_profile="p1",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    llm = FakeLLM()
    sink = build_sink(llm, FakeEmbedder(), store, DedupChecker(store), db)
    art = _raw("A", "http://x/a")
    await sink(FakePlugin(), [art])
    await sink(FakePlugin(), [art])  # second pass: URL dedup + score-pair dedup
    assert llm.calls == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_processor/test_llm_filter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.processor'`

- [ ] **Step 3: Write minimal implementation**

Create `src/radaragent/processor/__init__.py`:
```python
from radaragent.processor.llm_filter import build_sink

__all__ = ["build_sink"]
```

Create `src/radaragent/processor/llm_filter.py`:
```python
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from radaragent.storage import RawArticle
from radaragent.subscriptions.crud import (
    has_score,
    list_enabled_subscriptions,
    record_score,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from radaragent.providers.embedding import EmbeddingProvider
    from radaragent.providers.llm.base import LLMProvider
    from radaragent.storage import DedupChecker, RAGStore
    from radaragent.storage.db import Database

logger = logging.getLogger(__name__)


def build_sink(
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    store: RAGStore,
    dedup: DedupChecker,
    db: Database,
) -> Callable[[object, list[RawArticle]], Awaitable[None]]:
    """Fetch sink: store new article vectors once (global), then score each
    new article against every enabled subscription's profile.

    Scoring is the cartesian product article x subscription, deduplicated by
    the ``article_scores`` primary key so a re-fetched article is never
    re-scored for a subscription it already has a row for.
    """
    semaphore = asyncio.Semaphore(4)

    async def sink(plugin: object, articles: list[RawArticle]) -> None:
        if not articles:
            return

        fresh = [a for a in articles if not store.has_url(a.url)]
        if fresh:
            content_vecs = await embedder.embed_batch(
                [a.content[:4000] or a.title for a in fresh]
            )
            for art, cv in zip(fresh, content_vecs, strict=True):
                result = dedup.check(art.url, cv)
                # Minimal global ProcessedArticle row; per-sub summary lives in SQLite.
                from radaragent.storage import ProcessedArticle

                processed = ProcessedArticle(
                    raw=art,
                    relevance_score=0.0,
                    summary="",
                    tags=[],
                    key_insight="",
                    is_duplicate=result.is_duplicate,
                )
                store.add(processed, cv, cv)

        subscriptions = list_enabled_subscriptions(db)
        if not subscriptions:
            logger.info("no enabled subscriptions; %d article(s) stored only", len(fresh))
            return

        for sub in subscriptions:
            from radaragent.users.auth import _row_to_user  # local: avoid cycle

            urow = db.connection.execute(
                "SELECT * FROM users WHERE id = ?", (sub.user_id,)
            ).fetchone()
            out_lang = _row_to_user(urow).output_language if urow else "zh"

            async def score(art: RawArticle):
                aid = store.article_id(art.url)
                if has_score(db, aid, sub.id):
                    return
                async with semaphore:
                    try:
                        proc = await llm.score_and_summarize(
                            art, sub.interest_profile, out_lang
                        )
                    except Exception:
                        logger.exception("scoring failed: %s", art.url)
                        return
                if proc.relevance_score >= sub.filter.min_score:
                    record_score(
                        db,
                        aid,
                        sub.id,
                        proc.relevance_score,
                        proc.summary,
                        proc.tags,
                        proc.key_insight,
                    )

            await asyncio.gather(*(score(a) for a in articles))

    return sink
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_processor/test_llm_filter.py -v`
Expected: 3 passed

- [ ] **Step 5: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
```bash
git add src/radaragent/processor/ tests/test_processor/
git commit -m "feat(processor): per-subscription scoring sink

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 10: Service — query + digest + ServiceAPI facade

**Files:**
- Create: `src/radaragent/service/__init__.py`, `query.py`, `digest.py`, `api.py`
- Test: `tests/test_service/test_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_service/__init__.py` (empty).
Create `tests/test_service/test_api.py`:
```python
from __future__ import annotations

from datetime import UTC, datetime

import pytest

from radaragent.service.api import SearchFilters, ServiceAPI
from radaragent.storage import RAGStore, RawArticle
from radaragent.subscriptions.crud import create_subscription, record_score
from radaragent.subscriptions.models import Channel, SubscriptionCreate
from radaragent.users.auth import register


class FakeLLM:
    async def score_and_summarize(self, article, profile, output_language):  # unused here
        raise NotImplementedError

    async def generate_digest(self, articles, context):
        return f"DIGEST n={len(articles)} ctx={len(context)}"

    async def answer(self, question, context):
        return f"ANSWER to {question!r} using {len(context)} docs"


class FakeEmbedder:
    @property
    def dimension(self) -> int:
        return 3

    async def embed(self, text: str):
        return [1.0, 0.0, 0.0]

    async def embed_batch(self, texts):
        return [[1.0, 0.0, 0.0] for _ in texts]


@pytest.fixture
def store(tmp_path):
    return RAGStore(persist_directory=tmp_path / "chroma")


def _seed_article(store: RAGStore, url: str, title: str) -> str:
    from radaragent.storage import ProcessedArticle

    raw = RawArticle(
        title=title,
        url=url,
        content=f"content {title}",
        source="fake",
        language="en",
        timestamp=datetime.now(tz=UTC),
    )
    p = ProcessedArticle(raw=raw, relevance_score=0.0, summary=f"sum {title}", tags=[], key_insight="")
    store.add(p, [1.0, 0.0, 0.0], [1.0, 0.0, 0.0])
    return store.article_id(url)


async def test_generate_digest_writes_and_is_idempotent(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    sub = create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s",
            interest_profile="p",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    aid = _seed_article(store, "http://x/a", "A")
    record_score(db, aid, sub.id, 8.0, "sum A", ["t"], "insight")

    api = ServiceAPI(db=db, store=store, llm=FakeLLM(), embedder=FakeEmbedder())
    today = datetime.now(tz=UTC).date().isoformat()
    d1 = api.generate_digest(sub.id, today)
    assert "DIGEST n=1" in d1.content
    d2 = api.generate_digest(sub.id, today)  # rerun overwrites
    rows = db.connection.execute(
        "SELECT COUNT(*) FROM digests WHERE subscription_id=?", (sub.id,)
    ).fetchone()[0]
    assert rows == 1
    assert d2.date == today


async def test_query_scoped_to_user_articles(db, store):
    u = register(db, "a@b.com", "hunter2pass")
    sub = create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id,
            name="s",
            interest_profile="p",
            schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    aid = _seed_article(store, "http://x/a", "A")
    record_score(db, aid, sub.id, 8.0, "sum A", [], None)
    _seed_article(store, "http://x/other", "Other")  # not scored for this user

    api = ServiceAPI(db=db, store=store, llm=FakeLLM(), embedder=FakeEmbedder())
    ans = await api.query(u.id, "what is new?")
    assert "ANSWER" in ans.text
    assert ans.sources == [aid]


def test_search_is_placeholder(db, store):
    api = ServiceAPI(db=db, store=store, llm=FakeLLM(), embedder=FakeEmbedder())
    with pytest.raises(NotImplementedError):
        api.search(1, SearchFilters())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_service/test_api.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.service'`

- [ ] **Step 3: Extend LLMProvider with `answer` + implement service**

Add to `src/radaragent/providers/llm/base.py` a new abstract method (after `generate_digest`):
```python
    @abstractmethod
    async def answer(self, question: str, context: list[ProcessedArticle]) -> str:
        """Answer a user question grounded in retrieved context articles."""
```

Add to `src/radaragent/providers/llm/openai.py` an `answer` implementation mirroring the existing `generate_digest` prompt style (reuse its client + digest_model). Open the file and add:
```python
    async def answer(self, question: str, context: list[ProcessedArticle]) -> str:
        joined = "\n\n".join(
            f"- {c.summary or c.raw.title} ({c.raw.url})" for c in context
        )
        resp = await self._client.chat.completions.create(
            model=self._digest_model,
            messages=[
                {
                    "role": "system",
                    "content": "Answer the user's question using only the provided "
                    "context. Cite article titles. If the context is insufficient, "
                    "say so.",
                },
                {"role": "user", "content": f"Context:\n{joined}\n\nQuestion: {question}"},
            ],
        )
        return resp.choices[0].message.content or ""
```
(If the existing client attribute is not `self._client`/model not `self._digest_model`, match the actual attribute names already in `openai.py`.)

Create `src/radaragent/service/query.py`:
```python
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from radaragent.storage import ProcessedArticle, RawArticle
from radaragent.subscriptions.crud import scored_article_ids_for_user

if TYPE_CHECKING:
    from radaragent.providers.embedding import EmbeddingProvider
    from radaragent.providers.llm.base import LLMProvider
    from radaragent.storage import RAGStore
    from radaragent.storage.db import Database


@dataclass
class Answer:
    text: str
    sources: list[str]


async def run_query(
    db: Database,
    store: RAGStore,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    user_id: int,
    question: str,
    top_k: int = 8,
) -> Answer:
    allowed = scored_article_ids_for_user(db, user_id)
    if not allowed:
        return Answer(text="你还没有任何已评分的文章可供检索。", sources=[])
    qvec = await embedder.embed(question)
    neighbors = store.nearest_content(qvec, top_k=top_k)
    picked = [aid for aid, _ in neighbors if aid in allowed]
    context: list[ProcessedArticle] = []
    for aid in picked:
        meta = store.get_metadata(aid)
        if meta is None:
            continue
        context.append(
            ProcessedArticle(
                raw=RawArticle(
                    title=meta["title"],
                    url=meta["url"],
                    content="",
                    source=meta["source"],
                    language=meta["language"],
                    timestamp=__import__("datetime").datetime.fromisoformat(
                        meta["timestamp"]
                    ),
                ),
                relevance_score=float(meta.get("relevance_score", 0.0)),
                summary=meta.get("summary", ""),
                tags=[],
                key_insight="",
            )
        )
    text = await llm.answer(question, context)
    return Answer(text=text, sources=picked)
```

`run_query` needs `RAGStore.get_metadata`. Add to `src/radaragent/storage/rag.py`:
```python
    def get_metadata(self, article_id: str) -> dict[str, Any] | None:
        got = self._summary.get(ids=[article_id], include=["metadatas", "documents"])
        metas = got.get("metadatas") or []
        if not metas:
            return None
        meta = dict(metas[0])
        docs = got.get("documents") or []
        if docs:
            meta["summary"] = docs[0]
        return meta
```

Create `src/radaragent/service/digest.py`:
```python
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from radaragent.storage import ProcessedArticle, RawArticle
from radaragent.subscriptions.crud import (
    get_subscription,
    record_digest,
    todays_scored_articles,
)

if TYPE_CHECKING:
    from radaragent.providers.embedding import EmbeddingProvider
    from radaragent.providers.llm.base import LLMProvider
    from radaragent.storage import RAGStore
    from radaragent.storage.db import Database


@dataclass
class Digest:
    subscription_id: int
    date: str
    content: str
    article_ids: list[str]


def _meta_to_processed(meta: dict, score: float, summary: str) -> ProcessedArticle:
    return ProcessedArticle(
        raw=RawArticle(
            title=meta.get("title", ""),
            url=meta.get("url", ""),
            content="",
            source=meta.get("source", ""),
            language=meta.get("language", "en"),
            timestamp=datetime.fromisoformat(
                meta.get("timestamp", datetime.now(tz=UTC).isoformat())
            ),
        ),
        relevance_score=score,
        summary=summary,
        tags=[],
        key_insight="",
    )


async def generate_digest(
    db: Database,
    store: RAGStore,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    subscription_id: int,
    date: str,
    history_context_size: int = 5,
) -> Digest:
    sub = get_subscription(db, subscription_id)
    if sub is None:
        raise ValueError(f"subscription {subscription_id} not found")

    rows = todays_scored_articles(db, subscription_id, date)
    today_articles: list[ProcessedArticle] = []
    article_ids: list[str] = []
    for r in rows:
        meta = store.get_metadata(r["article_id"])
        if meta is None:
            continue
        today_articles.append(
            _meta_to_processed(meta, r["relevance_score"], r["summary"])
        )
        article_ids.append(r["article_id"])

    context: list[ProcessedArticle] = []
    if today_articles:
        qvec = await embedder.embed(sub.interest_profile)
        for aid, _ in store.nearest_content(qvec, top_k=history_context_size):
            if aid in article_ids:
                continue
            meta = store.get_metadata(aid)
            if meta:
                context.append(
                    _meta_to_processed(
                        meta,
                        float(meta.get("relevance_score", 0.0)),
                        meta.get("summary", ""),
                    )
                )

    content = await llm.generate_digest(today_articles, context)
    record_digest(db, subscription_id, date, content, article_ids)
    return Digest(
        subscription_id=subscription_id,
        date=date,
        content=content,
        article_ids=article_ids,
    )
```

Create `src/radaragent/service/api.py`:
```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from radaragent.service.digest import Digest, generate_digest
from radaragent.service.query import Answer, run_query

if TYPE_CHECKING:
    from radaragent.providers.embedding import EmbeddingProvider
    from radaragent.providers.llm.base import LLMProvider
    from radaragent.storage import RAGStore
    from radaragent.storage.db import Database


@dataclass
class SearchFilters:
    keywords: list[str] = field(default_factory=list)
    min_score: float = 0.0
    source: str | None = None


class ServiceAPI:
    """Facade over RAG + processor + persistence. Sole entry point for
    consumers (Phase 3 CLI, Phase 4 web)."""

    def __init__(
        self,
        db: Database,
        store: RAGStore,
        llm: LLMProvider,
        embedder: EmbeddingProvider,
        history_context_size: int = 5,
    ) -> None:
        self._db = db
        self._store = store
        self._llm = llm
        self._embedder = embedder
        self._history_context_size = history_context_size

    def generate_digest(self, subscription_id: int, date: str) -> Digest:
        import asyncio

        return asyncio.run(
            generate_digest(
                self._db,
                self._store,
                self._llm,
                self._embedder,
                subscription_id,
                date,
                self._history_context_size,
            )
        )

    async def query(self, user_id: int, question: str) -> Answer:
        return await run_query(
            self._db, self._store, self._llm, self._embedder, user_id, question
        )

    def search(self, user_id: int, filters: SearchFilters) -> list:
        raise NotImplementedError("search lands with the Phase 4 web layer")
```

> Note: `generate_digest` uses `asyncio.run`, so it must not be called from within a running loop. Task 11 calls the async `service.digest.generate_digest` directly inside the scheduler's loop; the facade's sync wrapper is for the CLI path only.

Create `src/radaragent/service/__init__.py`:
```python
from radaragent.service.api import SearchFilters, ServiceAPI
from radaragent.service.digest import Digest
from radaragent.service.query import Answer

__all__ = ["Answer", "Digest", "SearchFilters", "ServiceAPI"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_service/test_api.py -v`
Expected: 3 passed

- [ ] **Step 5: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
```bash
git add src/radaragent/service/ src/radaragent/storage/rag.py src/radaragent/providers/llm/ tests/test_service/
git commit -m "feat(service): ServiceAPI facade with generate_digest + query

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 11: Scheduler — per-subscription digest jobs

**Files:**
- Modify: `src/radaragent/scheduler/scheduler.py`
- Create: `src/radaragent/subscriptions/scheduling.py`
- Modify: `src/radaragent/subscriptions/__init__.py`
- Test: `tests/test_scheduler/test_digest_jobs.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_scheduler/__init__.py` (empty).
Create `tests/test_scheduler/test_digest_jobs.py`:
```python
from __future__ import annotations

from radaragent.scheduler import PluginScheduler
from radaragent.subscriptions.crud import create_subscription
from radaragent.subscriptions.models import Channel, SubscriptionCreate
from radaragent.subscriptions.scheduling import register_digest_jobs
from radaragent.users.auth import register


async def _noop_sink(plugin, articles):  # pragma: no cover - unused
    return None


def test_register_digest_jobs_adds_one_job_per_enabled_sub(db):
    u = register(db, "a@b.com", "hunter2pass")
    s1 = create_subscription(
        db,
        SubscriptionCreate(
            user_id=u.id, name="s1", interest_profile="p", schedule="0 8 * * *",
            channels=[Channel(type="email", config={"to": "me@x.com"})],
        ),
    )
    sched = PluginScheduler(sink=_noop_sink)

    called: list[int] = []

    async def fake_runner(sub_id: int) -> None:
        called.append(sub_id)

    register_digest_jobs(sched, db, fake_runner)
    job = sched._scheduler.get_job(f"digest:{s1.id}")
    assert job is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_scheduler/test_digest_jobs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'radaragent.subscriptions.scheduling'`

- [ ] **Step 3: Add scheduler hook + scheduling module**

In `src/radaragent/scheduler/scheduler.py`, add a method to `PluginScheduler` (after `register`):
```python
    def add_digest_job(self, job_id: str, cron: str, coro_func, sub_id: int) -> None:
        from apscheduler.triggers.cron import CronTrigger

        trigger = CronTrigger.from_crontab(cron)
        self._scheduler.add_job(
            coro_func,
            trigger=trigger,
            args=(sub_id,),
            id=job_id,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    def remove_digest_job(self, job_id: str) -> None:
        job = self._scheduler.get_job(job_id)
        if job is not None:
            self._scheduler.remove_job(job_id)
```

Create `src/radaragent/subscriptions/scheduling.py`:
```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from radaragent.subscriptions.crud import get_subscription, list_enabled_subscriptions

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from radaragent.scheduler import PluginScheduler
    from radaragent.storage.db import Database

logger = logging.getLogger(__name__)


def register_digest_jobs(
    scheduler: PluginScheduler,
    db: Database,
    runner: Callable[[int], Awaitable[None]],
) -> None:
    """Add one cron digest job per enabled subscription."""
    for sub in list_enabled_subscriptions(db):
        scheduler.add_digest_job(f"digest:{sub.id}", sub.schedule, runner, sub.id)
        logger.info("digest job registered: sub=%s cron=%s", sub.id, sub.schedule)


def reschedule(
    scheduler: PluginScheduler,
    db: Database,
    runner: Callable[[int], Awaitable[None]],
    subscription_id: int,
) -> None:
    """Re-sync a single subscription's digest job (add/update/remove)."""
    job_id = f"digest:{subscription_id}"
    sub = get_subscription(db, subscription_id)
    if sub is None or not sub.enabled:
        scheduler.remove_digest_job(job_id)
        return
    scheduler.add_digest_job(job_id, sub.schedule, runner, subscription_id)
```

Add to `src/radaragent/subscriptions/__init__.py` imports + sorted `__all__`:
```python
from radaragent.subscriptions.scheduling import register_digest_jobs, reschedule
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_scheduler/test_digest_jobs.py -v`
Expected: 1 passed

- [ ] **Step 5: Lint + commit**

Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
```bash
git add src/radaragent/scheduler/ src/radaragent/subscriptions/ tests/test_scheduler/
git commit -m "feat(scheduler): per-subscription digest jobs + reschedule

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 12: main.py — bootstrap, wiring, CLI subcommands

**Files:**
- Modify: `src/radaragent/main.py`
- Delete: `config/interests.yaml`
- Test: `tests/test_main/test_bootstrap.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_main/__init__.py` (empty).
Create `tests/test_main/test_bootstrap.py`:
```python
from __future__ import annotations

import builtins

from radaragent.main import ensure_admin_user
from radaragent.storage.db import Database


def test_ensure_admin_prompts_when_no_users(tmp_path, monkeypatch):
    db = Database(tmp_path / "b.db")
    db.init_schema()
    answers = iter(["admin@x.com", "supersecret", "zh"])
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_main/test_bootstrap.py -v`
Expected: FAIL — `ImportError: cannot import name 'ensure_admin_user'`

- [ ] **Step 3: Rewrite main.py**

Replace `src/radaragent/main.py` with:
```python
from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv

from radaragent.config import Settings, load_settings
from radaragent.plugins import SourcePlugin, build_plugin
from radaragent.processor import build_sink
from radaragent.providers.embedding import (
    EmbeddingProvider,
    LocalEmbeddingProvider,
    OpenAIEmbeddingProvider,
)
from radaragent.providers.llm.base import LLMProvider
from radaragent.providers.llm.openai import OpenAILLMProvider
from radaragent.providers.notifier import EmailNotifier
from radaragent.scheduler import PluginScheduler
from radaragent.service.digest import generate_digest
from radaragent.service.query import run_query
from radaragent.storage import DedupChecker, RAGStore
from radaragent.storage.db import Database
from radaragent.subscriptions.crud import get_subscription
from radaragent.subscriptions.scheduling import register_digest_jobs
from radaragent.users.auth import register

logger = logging.getLogger(__name__)


def _build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm.provider == "openai":
        return OpenAILLMProvider(
            api_key=settings.llm.api_key,
            filter_model=settings.llm.filter_model,
            digest_model=settings.llm.digest_model,
            base_url=settings.llm.base_url,
        )
    raise ValueError(f"unsupported llm.provider={settings.llm.provider!r}")


def _build_embedding_provider(settings: Settings) -> EmbeddingProvider:
    cfg = settings.embedding
    if cfg.provider == "local":
        return LocalEmbeddingProvider(model_name=cfg.model, device=cfg.device)
    if cfg.provider == "openai":
        if not cfg.api_key:
            raise ValueError("embedding.provider=openai requires embedding.api_key")
        return OpenAIEmbeddingProvider(
            api_key=cfg.api_key, model=cfg.model, base_url=cfg.base_url
        )
    raise ValueError(f"unknown embedding.provider={cfg.provider!r}")


def _build_rag_store(settings: Settings) -> RAGStore:
    return RAGStore(
        persist_directory=settings.storage.chroma.get(
            "persist_directory", "./data/chroma"
        )
    )


def ensure_admin_user(db: Database) -> None:
    """First-run bootstrap: if no users exist, interactively create the admin."""
    count = db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        return
    print("首次启动：创建管理员账号")
    email = input("邮箱: ").strip()
    password = getpass("密码 (≥8 位): ")
    output_language = input("输出语言 [zh]: ").strip() or "zh"
    register(db, email, password, output_language=output_language)
    print(f"管理员 {email} 已创建。")


def _make_digest_runner(db, store, llm, embedder, settings):
    async def runner(subscription_id: int) -> None:
        from datetime import UTC, datetime

        date = datetime.now(tz=UTC).date().isoformat()
        try:
            digest = await generate_digest(
                db, store, llm, embedder, subscription_id, date,
                settings.digest.history_context_size,
            )
        except Exception:
            logger.exception("digest generation failed for sub %s", subscription_id)
            return
        sub = get_subscription(db, subscription_id)
        if sub is None or settings.smtp is None:
            return
        notifier = EmailNotifier(settings.smtp)
        for ch in sub.channels:
            if ch.type == "email":
                await notifier.send(digest.content, ch.config)

    return runner


async def _run(settings_path: Path, once: bool) -> None:
    settings = load_settings(settings_path)
    db = Database(settings.storage.sqlite_path)
    db.init_schema()
    ensure_admin_user(db)

    llm = _build_llm_provider(settings)
    embedder = _build_embedding_provider(settings)
    store = _build_rag_store(settings)
    dedup = DedupChecker(store=store, threshold=settings.embedding.dedup_threshold)

    scheduler = PluginScheduler(sink=build_sink(llm, embedder, store, dedup, db))
    for p in settings.plugins:
        scheduler.register(build_plugin(p.type, p.id, p.config))

    runner = _make_digest_runner(db, store, llm, embedder, settings)
    register_digest_jobs(scheduler, db, runner)

    if once:
        await scheduler.run_once()
        return

    scheduler.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop(*_a: object) -> None:
        stop.set()

    for sig_name in ("SIGINT", "SIGTERM"):
        sig = getattr(signal, sig_name, None)
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, _request_stop)
        except NotImplementedError:
            signal.signal(sig, lambda *_a: _request_stop())

    try:
        await stop.wait()
    finally:
        scheduler.shutdown()
        db.close()


def _cmd_digest(args: argparse.Namespace) -> None:
    from datetime import UTC, datetime

    settings = load_settings(args.settings)
    db = Database(settings.storage.sqlite_path)
    db.init_schema()
    llm = _build_llm_provider(settings)
    embedder = _build_embedding_provider(settings)
    store = _build_rag_store(settings)
    date = args.date or datetime.now(tz=UTC).date().isoformat()
    digest = asyncio.run(
        generate_digest(
            db, store, llm, embedder, args.subscription, date,
            settings.digest.history_context_size,
        )
    )
    print(digest.content)
    db.close()


def _cmd_query(args: argparse.Namespace) -> None:
    settings = load_settings(args.settings)
    db = Database(settings.storage.sqlite_path)
    db.init_schema()
    llm = _build_llm_provider(settings)
    embedder = _build_embedding_provider(settings)
    store = _build_rag_store(settings)
    ans = asyncio.run(run_query(db, store, llm, embedder, args.user, args.question))
    print(ans.text)
    db.close()


def _cmd_useradd(args: argparse.Namespace) -> None:
    settings = load_settings(args.settings)
    db = Database(settings.storage.sqlite_path)
    db.init_schema()
    email = input("邮箱: ").strip()
    password = getpass("密码 (≥8 位): ")
    lang = input("输出语言 [zh]: ").strip() or "zh"
    register(db, email, password, output_language=lang)
    print(f"用户 {email} 已创建。")
    db.close()


def main() -> None:
    parser = argparse.ArgumentParser(prog="radaragent")
    parser.add_argument("--settings", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    sub = parser.add_subparsers(dest="command")

    p_run = sub.add_parser("run", help="start the 24/7 daemon")
    p_run.add_argument("--once", action="store_true", help="single fetch pass then exit")

    p_dig = sub.add_parser("digest", help="generate + print one digest")
    p_dig.add_argument("--subscription", type=int, required=True)
    p_dig.add_argument("--date", default=None, help="YYYY-MM-DD (default today)")

    p_q = sub.add_parser("query", help="one-shot RAG question")
    p_q.add_argument("--user", type=int, required=True)
    p_q.add_argument("question")

    sub.add_parser("useradd", help="create a user")

    args = parser.parse_args()

    if sys.platform == "win32":
        import ctypes

        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleOutputCP(65001)
        kernel32.SetConsoleCP(65001)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower() != "utf-8":
            stream.reconfigure(encoding="utf-8", errors="replace")

    logging.basicConfig(
        level=args.log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    load_dotenv()

    if args.command == "digest":
        _cmd_digest(args)
    elif args.command == "query":
        _cmd_query(args)
    elif args.command == "useradd":
        _cmd_useradd(args)
    else:  # "run" or default
        once = getattr(args, "once", False)
        asyncio.run(_run(settings_path=args.settings, once=once))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Delete interests.yaml**

```bash
git rm config/interests.yaml
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_main/test_bootstrap.py -v`
Expected: 2 passed

- [ ] **Step 6: Full suite + lint**

Run: `python -m pytest -q`
Expected: all tests pass
Run: `python -m ruff check src tests && python -m ruff format src tests && python -m mypy src`
Expected: no errors

- [ ] **Step 7: Commit**

```bash
git add src/radaragent/main.py tests/test_main/
git commit -m "feat: daemon bootstrap + CLI subcommands (run/digest/query/useradd)

Removes interests.yaml; admin account created interactively on first run.

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Task 13: Docs + CHANGELOG

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Update CHANGELOG**

Under `## [Unreleased]`, add:
```markdown
### Added
- Multi-user backend: SQLite `Database` (users / subscriptions / article_scores / digests)
- bcrypt auth (`register` / `authenticate`) + in-memory `SessionStore`
- `Subscription` models with cron + score validation; subscription/score/digest DAO
- `ServiceAPI` facade: `generate_digest` + `query` (`search` placeholder)
- `Notifier` ABC + `EmailNotifier` (aiosmtplib)
- Per-subscription scoring sink (article × subscription, dedup by score PK)
- Per-subscription APScheduler digest jobs + `reschedule`
- CLI subcommands: `run` / `digest` / `query` / `useradd`; first-run admin bootstrap

### Changed
- Config: removed `interests.yaml`/`InterestsConfig`; added `smtp`/`auth`/`digest`/`storage.sqlite_path`
- Scoring moved from `main.py` into `radaragent.processor`

### Removed
- `config/interests.yaml` (interests now per-subscription in DB)
```

- [ ] **Step 2: Commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): record Phase 3 user-ization + backend services

Co-Authored-By: Claude Opus 4.7 <noreply@anthropic.com>"
```

---

## Self-Review

**1. Spec coverage:**

| Spec section | Task |
|---|---|
| SQLite schema (4 tables) | Task 2 |
| Pydantic User/Subscription models | Task 3, 5 |
| Auth bcrypt + register/authenticate | Task 3 |
| SessionStore (in-memory + seam) | Task 4 |
| First-run bootstrap | Task 12 |
| Per-(article,subscription) scoring | Task 9 |
| Global shared fetch | Task 9 (vectors stored once before sub loop) |
| ServiceAPI generate_digest + query | Task 10 |
| search signature-only | Task 10 (`NotImplementedError`) |
| Digest = today + RAG history (size 5, configurable) | Task 7 (config) + Task 10 (digest.py) |
| Scheduler per-subscription digest jobs + reschedule | Task 11 |
| CLI run/digest/query/useradd | Task 12 |
| EmailNotifier (aiosmtplib) | Task 8 |
| interests.yaml removed; settings adds smtp/sqlite/auth | Task 7, 12 |
| Tests for each subsystem | Tasks 2-12 (TDD) |

No gaps.

**2. Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" — every code step has complete code. `search` raising `NotImplementedError` is an intentional spec'd placeholder, tested explicitly.

**3. Type consistency:** `Database` exposes `.connection`/`.init_schema()`/`.close()` — used consistently. `build_sink(llm, embedder, store, dedup, db)` signature matches Task 9 test and Task 12 caller. `generate_digest(db, store, llm, embedder, subscription_id, date, history_context_size)` consistent between Task 10 def, Task 12 daemon runner, and `_cmd_digest`. `run_query(db, store, llm, embedder, user_id, question)` consistent. `RAGStore.get_metadata` added in Task 10 and used by both query.py and digest.py. `register_digest_jobs(scheduler, db, runner)` consistent Task 11 ↔ Task 12. `Answer(text, sources)`, `Digest(subscription_id, date, content, article_ids)` consistent.

**Note for executor:** Task 10 Step 3 modifies `providers/llm/openai.py` and `base.py`; verify the existing OpenAI client attribute names before pasting `answer()`. If `OpenAILLMProvider` attribute names differ from `self._client`/`self._digest_model`, match the actual names. This is the one place that depends on unread existing code.
