from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pydantic import ValidationError
from starlette.responses import Response

from radaragent.subscriptions import (
    Channel,
    Subscription,
    SubscriptionCreate,
    SubscriptionFilter,
    create_subscription,
    delete_subscription,
    get_subscription,
    set_enabled,
)
from radaragent.users import User
from radaragent.web.context import WebContext
from radaragent.web.deps import RedirectException, get_ctx, require_user, templates

router = APIRouter()


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _owned(ctx: WebContext, sub_id: int, user: User) -> Subscription:
    sub = get_subscription(ctx.db, sub_id)
    if sub is None or sub.user_id != user.id:
        raise RedirectException("/")
    return sub


@router.get("/subscriptions/new", response_class=HTMLResponse)
def new_form(
    request: Request,
    user: Annotated[User, Depends(require_user)],
) -> Response:
    return templates.TemplateResponse(
        request, "subscription_new.html", {"user": user, "values": {}}
    )


@router.post("/subscriptions")
def create(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    name: Annotated[str, Form()],
    interest_profile: Annotated[str, Form()],
    schedule: Annotated[str, Form()] = "0 8 * * *",
    fmt: Annotated[str, Form(alias="format")] = "digest",
    email_to: Annotated[str, Form()] = "",
    min_score: Annotated[float, Form()] = 6.0,
    keywords_boost: Annotated[str, Form()] = "",
    keywords_ignore: Annotated[str, Form()] = "",
    source_whitelist: Annotated[str, Form()] = "",
) -> Response:
    ctx = get_ctx(request)
    to_addr = email_to.strip() or user.email
    try:
        data = SubscriptionCreate(
            user_id=user.id,
            name=name.strip(),
            interest_profile=interest_profile.strip(),
            filter=SubscriptionFilter(
                keywords_boost=_csv(keywords_boost),
                keywords_ignore=_csv(keywords_ignore),
                min_score=min_score,
                source_whitelist=_csv(source_whitelist),
            ),
            schedule=schedule.strip(),
            channels=[Channel(type="email", config={"to": to_addr})],
            format=fmt,  # type: ignore[arg-type]
        )
    except ValidationError as exc:
        return templates.TemplateResponse(
            request,
            "subscription_new.html",
            {
                "user": user,
                "error": "; ".join(e["msg"] for e in exc.errors()),
                "values": {
                    "name": name,
                    "interest_profile": interest_profile,
                    "schedule": schedule,
                    "format": fmt,
                    "email_to": email_to,
                    "min_score": min_score,
                    "keywords_boost": keywords_boost,
                    "keywords_ignore": keywords_ignore,
                    "source_whitelist": source_whitelist,
                },
            },
            status_code=400,
        )
    sub = create_subscription(ctx.db, data)
    ctx.reschedule(sub.id)
    return RedirectResponse("/", status_code=303)


@router.post("/subscriptions/{sub_id}/toggle")
def toggle(
    request: Request,
    sub_id: int,
    user: Annotated[User, Depends(require_user)],
) -> Response:
    ctx = get_ctx(request)
    sub = _owned(ctx, sub_id, user)
    set_enabled(ctx.db, sub_id, not sub.enabled)
    ctx.reschedule(sub_id)
    return RedirectResponse("/", status_code=303)


@router.post("/subscriptions/{sub_id}/delete")
def delete(
    request: Request,
    sub_id: int,
    user: Annotated[User, Depends(require_user)],
) -> Response:
    ctx = get_ctx(request)
    _owned(ctx, sub_id, user)
    delete_subscription(ctx.db, sub_id)
    ctx.reschedule(sub_id)
    return RedirectResponse("/", status_code=303)
