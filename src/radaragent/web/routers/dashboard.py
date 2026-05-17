from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from starlette.responses import Response

from radaragent.subscriptions import (
    list_subscriptions_for_user,
    recent_digests_for_user,
)
from radaragent.users import User
from radaragent.web.deps import get_ctx, require_user, templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(
    request: Request,
    user: Annotated[User, Depends(require_user)],
) -> Response:
    ctx = get_ctx(request)
    subscriptions = list_subscriptions_for_user(ctx.db, user.id)
    digests = recent_digests_for_user(ctx.db, user.id, limit=10)
    return templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "user": user,
            "subscriptions": subscriptions,
            "digests": [dict(d) for d in digests],
        },
    )
