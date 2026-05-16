from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from radaragent.plugins.base import SourcePlugin
from radaragent.storage import RawArticle

logger = logging.getLogger(__name__)

ArticleSink = Callable[[SourcePlugin, list[RawArticle]], Awaitable[None]]


class PluginScheduler:
    """Schedules each SourcePlugin independently with cron triggers.

    Errors in one plugin's fetch are logged and isolated; other plugins keep
    running. Each successful fetch hands its articles to the registered sink
    coroutine, which the rest of the pipeline (processor → storage → output)
    consumes.
    """

    def __init__(self, sink: ArticleSink) -> None:
        self._scheduler = AsyncIOScheduler()
        self._sink = sink
        self._plugins: dict[str, SourcePlugin] = {}

    def register(self, plugin: SourcePlugin) -> None:
        if plugin.plugin_id in self._plugins:
            raise ValueError(f"plugin id {plugin.plugin_id!r} already registered")
        trigger = CronTrigger.from_crontab(plugin.get_schedule())
        self._scheduler.add_job(
            self._run_plugin,
            trigger=trigger,
            args=(plugin,),
            id=plugin.plugin_id,
            max_instances=1,
            coalesce=True,
        )
        self._plugins[plugin.plugin_id] = plugin
        logger.info(
            "registered plugin %s with schedule %s", plugin.plugin_id, plugin.get_schedule()
        )

    def add_digest_job(
        self,
        job_id: str,
        cron: str,
        coro_func: Callable[[int], Awaitable[None]],
        sub_id: int,
    ) -> None:
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
        if self._scheduler.get_job(job_id) is not None:
            self._scheduler.remove_job(job_id)

    def start(self) -> None:
        self._scheduler.start()
        logger.info("scheduler started with %d plugin(s)", len(self._plugins))

    def shutdown(self, wait: bool = True) -> None:
        self._scheduler.shutdown(wait=wait)

    async def run_once(self, plugin_id: str | None = None) -> None:
        """Trigger a fetch immediately. Useful for smoke-testing the pipeline."""
        targets = [self._plugins[plugin_id]] if plugin_id else list(self._plugins.values())
        await asyncio.gather(*(self._run_plugin(p) for p in targets))

    async def _run_plugin(self, plugin: SourcePlugin) -> None:
        try:
            articles = await plugin.fetch()
        except Exception:
            logger.exception("plugin %s failed during fetch", plugin.plugin_id)
            return
        logger.info("plugin %s fetched %d article(s)", plugin.plugin_id, len(articles))
        try:
            await self._sink(plugin, articles)
        except Exception:
            logger.exception("sink failed while processing articles from %s", plugin.plugin_id)
