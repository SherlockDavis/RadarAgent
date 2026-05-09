from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from pathlib import Path

from dotenv import load_dotenv

from radaragent.config import InterestsConfig, Settings, load_interests, load_settings
from radaragent.plugins import SourcePlugin, build_plugin
from radaragent.providers.llm.base import LLMProvider
from radaragent.providers.llm.openai import OpenAILLMProvider
from radaragent.scheduler import PluginScheduler
from radaragent.storage import RawArticle

logger = logging.getLogger(__name__)


def _build_llm_provider(settings: Settings) -> LLMProvider:
    if settings.llm.provider == "openai":
        return OpenAILLMProvider(
            api_key=settings.llm.api_key,
            filter_model=settings.llm.filter_model,
            digest_model=settings.llm.digest_model,
            embedding_model=settings.embedding.model,
            base_url=settings.llm.base_url,
        )
    raise ValueError(f"Phase 1 only supports llm.provider='openai', got {settings.llm.provider!r}")


def _build_plugins(settings: Settings) -> list[SourcePlugin]:
    return [build_plugin(p.type, p.id, p.config) for p in settings.plugins]


def _build_sink(llm: LLMProvider, interests: InterestsConfig):
    """Sink: score each fetched article and print kept ones to the console."""
    threshold = interests.min_relevance_score
    semaphore = asyncio.Semaphore(4)  # cap concurrent LLM calls

    async def score_one(article: RawArticle):
        async with semaphore:
            try:
                return await llm.score_and_summarize(
                    article, interests.profile, interests.output_language
                )
            except Exception:
                logger.exception("LLM scoring failed for %s", article.url)
                return None

    async def sink(plugin: SourcePlugin, articles: list[RawArticle]) -> None:
        if not articles:
            return
        results = await asyncio.gather(*(score_one(a) for a in articles))
        kept = [r for r in results if r is not None and r.relevance_score >= threshold]
        kept.sort(key=lambda r: r.relevance_score, reverse=True)

        print(f"\n=== {plugin.plugin_id}: {len(kept)}/{len(articles)} kept (>= {threshold}) ===")
        for r in kept:
            print(
                f"[{r.relevance_score:.1f}] {r.raw.title}\n"
                f"  {r.key_insight}\n"
                f"  tags: {', '.join(r.tags) if r.tags else '(none)'}\n"
                f"  url:  {r.raw.url}\n"
            )

    return sink


async def _run(once: bool, settings_path: Path, interests_path: Path) -> None:
    settings = load_settings(settings_path)
    interests = load_interests(interests_path)
    if not settings.plugins:
        raise SystemExit("no plugins configured in settings.yaml")

    llm = _build_llm_provider(settings)
    plugins = _build_plugins(settings)
    scheduler = PluginScheduler(sink=_build_sink(llm, interests))
    for plugin in plugins:
        scheduler.register(plugin)

    if once:
        await scheduler.run_once()
        return

    scheduler.start()
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    def _request_stop(*_args: object) -> None:
        logger.info("shutdown signal received")
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


def main() -> None:
    parser = argparse.ArgumentParser(prog="radaragent")
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path("config/settings.yaml"),
        help="path to settings.yaml",
    )
    parser.add_argument(
        "--interests",
        type=Path,
        default=Path("config/interests.yaml"),
        help="path to interests.yaml",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="fetch each plugin once and exit (smoke test)",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
    )
    args = parser.parse_args()

    # Windows console defaults to cp936/GBK and would mojibake the UTF-8 LLM output.
    # Two-sided fix: switch the console's code page to 65001 (UTF-8) AND tell Python
    # to encode its stdout/stderr as UTF-8. Either one alone is insufficient.
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

    asyncio.run(_run(once=args.once, settings_path=args.settings, interests_path=args.interests))


if __name__ == "__main__":
    main()
