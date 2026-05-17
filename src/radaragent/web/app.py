from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from radaragent.web.deps import RedirectException
from radaragent.web.routers import auth, dashboard, health, subscriptions

if TYPE_CHECKING:
    from radaragent.web.context import WebContext

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(ctx: WebContext) -> FastAPI:
    """Build the FastAPI app bound to the daemon's shared context.

    The app holds no resources of its own: ``ctx`` carries the live DB
    connection, RAG store, providers, session store and the digest-job
    reschedule closure, all owned by the running daemon.
    """
    app = FastAPI(title="RadarAgent", docs_url=None, redoc_url=None)
    app.state.ctx = ctx

    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.exception_handler(RedirectException)
    async def _redirect_handler(_request: Request, exc: RedirectException) -> RedirectResponse:
        return RedirectResponse(exc.location, status_code=303)

    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(dashboard.router)
    app.include_router(subscriptions.router)
    return app
