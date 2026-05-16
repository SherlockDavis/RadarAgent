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
