from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path

from dotenv import load_dotenv

from radaragent.config import Settings, load_settings
from radaragent.plugins import build_plugin
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
        return OpenAIEmbeddingProvider(api_key=cfg.api_key, model=cfg.model, base_url=cfg.base_url)
    raise ValueError(f"unknown embedding.provider={cfg.provider!r}")


def _build_rag_store(settings: Settings) -> RAGStore:
    return RAGStore(
        persist_directory=settings.storage.chroma.get("persist_directory", "./data/chroma")
    )


def ensure_admin_user(db: Database) -> None:
    """First-run bootstrap: if no users exist, interactively create the admin."""
    count = db.connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    if count > 0:
        return
    print("首次启动: 创建管理员账号")
    email = input("邮箱: ").strip()
    password = getpass("密码 (≥8 位): ")
    output_language = input("输出语言 [zh]: ").strip() or "zh"
    register(db, email, password, output_language=output_language)
    print(f"管理员 {email} 已创建。")


def _make_digest_runner(
    db: Database,
    store: RAGStore,
    llm: LLMProvider,
    embedder: EmbeddingProvider,
    settings: Settings,
) -> Callable[[int], Awaitable[None]]:
    async def runner(subscription_id: int) -> None:
        date = datetime.now(tz=UTC).date().isoformat()
        try:
            digest = await generate_digest(
                db,
                store,
                llm,
                embedder,
                subscription_id,
                date,
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
    settings = load_settings(args.settings)
    db = Database(settings.storage.sqlite_path)
    db.init_schema()
    llm = _build_llm_provider(settings)
    embedder = _build_embedding_provider(settings)
    store = _build_rag_store(settings)
    date = args.date or datetime.now(tz=UTC).date().isoformat()
    digest = asyncio.run(
        generate_digest(
            db,
            store,
            llm,
            embedder,
            args.subscription,
            date,
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
        "--log-level",
        default="INFO",
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
