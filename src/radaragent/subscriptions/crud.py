from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from radaragent.storage.db import Database
from radaragent.subscriptions.models import (
    Channel,
    Subscription,
    SubscriptionCreate,
    SubscriptionFilter,
)


def _row_to_subscription(row: sqlite3.Row) -> Subscription:
    return Subscription(
        id=row["id"],
        user_id=row["user_id"],
        name=row["name"],
        interest_profile=row["interest_profile"],
        filter=SubscriptionFilter.model_validate_json(row["filter_json"]),
        schedule=row["schedule"],
        channels=[Channel.model_validate(c) for c in json.loads(row["channels_json"])],
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
    assert cur.lastrowid is not None
    created = get_subscription(db, cur.lastrowid)
    assert created is not None
    return created


def get_subscription(db: Database, sub_id: int) -> Subscription | None:
    row = db.connection.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
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


def todays_scored_articles(
    db: Database, subscription_id: int, date: str | None = None
) -> list[sqlite3.Row]:
    if date is None:
        rows = db.connection.execute(
            "SELECT * FROM article_scores WHERE subscription_id=? ORDER BY relevance_score DESC",
            (subscription_id,),
        ).fetchall()
    else:
        rows = db.connection.execute(
            "SELECT * FROM article_scores WHERE subscription_id=? "
            "AND substr(scored_at,1,10)=? ORDER BY relevance_score DESC",
            (subscription_id, date),
        ).fetchall()
    return list(rows)


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
