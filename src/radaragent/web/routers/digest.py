from __future__ import annotations

import json
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from radaragent.service.digest import generate_digest
from radaragent.subscriptions import get_digest, get_subscription
from radaragent.users import User
from radaragent.web.context import WebContext
from radaragent.web.deps import RedirectException, get_ctx, require_user, templates

router = APIRouter()


def _owned_sub(ctx: WebContext, sub_id: int, user: User) -> object:
    sub = get_subscription(ctx.db, sub_id)
    if sub is None or sub.user_id != user.id:
        raise RedirectException("/")
    return sub


@router.get("/digest/{sub_id}/{date}", response_class=HTMLResponse)
def digest_detail(
    request: Request,
    sub_id: int,
    date: str,
    user: Annotated[User, Depends(require_user)],
) -> Response:
    ctx = get_ctx(request)
    sub = _owned_sub(ctx, sub_id, user)
    row = get_digest(ctx.db, sub_id, date)
    sources: list[dict[str, str]] = []
    content: str | None = None
    if row is not None:
        content = row["content"]
        for aid in json.loads(row["article_ids_json"]):
            meta = ctx.store.get_metadata(aid)
            if meta:
                sources.append(
                    {"title": str(meta.get("title", aid)), "url": str(meta.get("url", ""))}
                )
    return templates.TemplateResponse(
        request,
        "digest_detail.html",
        {
            "user": user,
            "sub": sub,
            "date": date,
            "content": content,
            "sources": sources,
        },
    )


@router.post("/digest/{sub_id}/{date}/run")
async def digest_run(
    request: Request,
    sub_id: int,
    date: str,
    user: Annotated[User, Depends(require_user)],
) -> Response:
    ctx = get_ctx(request)
    _owned_sub(ctx, sub_id, user)
    # Call the async coroutine directly: ServiceAPI.generate_digest wraps it in
    # asyncio.run(), which cannot nest inside the daemon's running loop.
    await generate_digest(
        ctx.db,
        ctx.store,
        ctx.llm,
        ctx.embedder,
        sub_id,
        date,
        ctx.settings.digest.history_context_size,
    )
    return RedirectResponse(f"/digest/{sub_id}/{date}", status_code=303)
