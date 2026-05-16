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
