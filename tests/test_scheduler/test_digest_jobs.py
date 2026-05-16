from __future__ import annotations

from radaragent.scheduler import PluginScheduler
from radaragent.subscriptions.crud import create_subscription, set_enabled
from radaragent.subscriptions.models import Channel, SubscriptionCreate
from radaragent.subscriptions.scheduling import register_digest_jobs, reschedule
from radaragent.users.auth import register


async def _noop_sink(plugin, articles):  # pragma: no cover - unused
    return None


def _sub(uid: int, **kw) -> SubscriptionCreate:
    base = dict(
        user_id=uid,
        name="s",
        interest_profile="p",
        schedule="0 8 * * *",
        channels=[Channel(type="email", config={"to": "me@x.com"})],
    )
    base.update(kw)
    return SubscriptionCreate(**base)


async def _runner(sub_id: int) -> None:  # pragma: no cover - unused
    return None


def test_register_digest_jobs_adds_one_job_per_enabled_sub(db):
    u = register(db, "a@b.com", "hunter2pass")
    s1 = create_subscription(db, _sub(u.id))
    sched = PluginScheduler(sink=_noop_sink)
    register_digest_jobs(sched, db, _runner)
    assert sched._scheduler.get_job(f"digest:{s1.id}") is not None


def test_reschedule_removes_job_when_disabled(db):
    u = register(db, "a@b.com", "hunter2pass")
    s1 = create_subscription(db, _sub(u.id))
    sched = PluginScheduler(sink=_noop_sink)
    register_digest_jobs(sched, db, _runner)
    set_enabled(db, s1.id, False)
    reschedule(sched, db, _runner, s1.id)
    assert sched._scheduler.get_job(f"digest:{s1.id}") is None
