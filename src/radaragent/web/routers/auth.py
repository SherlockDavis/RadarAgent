from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.responses import Response

from radaragent.users import authenticate, register
from radaragent.web.deps import (
    clear_session_cookie,
    current_user,
    get_ctx,
    set_session_cookie,
    templates,
)

router = APIRouter()


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request) -> Response:
    if current_user(request) is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"user": None})


@router.post("/login")
def login_submit(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
) -> Response:
    ctx = get_ctx(request)
    user = authenticate(ctx.db, email.strip(), password)
    if user is None:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"user": None, "error": "邮箱或密码不正确"},
            status_code=400,
        )
    token = ctx.sessions.create_session(user.id)
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, ctx, token)
    return resp


@router.get("/register", response_class=HTMLResponse)
def register_form(request: Request) -> Response:
    if current_user(request) is not None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "register.html", {"user": None})


@router.post("/register")
def register_submit(
    request: Request,
    email: Annotated[str, Form()],
    password: Annotated[str, Form()],
    output_language: Annotated[str, Form()] = "zh",
) -> Response:
    ctx = get_ctx(request)
    try:
        user = register(ctx.db, email.strip(), password, output_language=output_language.strip())
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "register.html",
            {"user": None, "error": str(exc)},
            status_code=400,
        )
    token = ctx.sessions.create_session(user.id)
    resp = RedirectResponse("/", status_code=303)
    set_session_cookie(resp, ctx, token)
    return resp


@router.get("/logout")
def logout(request: Request) -> Response:
    ctx = get_ctx(request)
    token = request.cookies.get(ctx.settings.web.session_cookie)
    if token:
        ctx.sessions.revoke(token)
    resp = RedirectResponse("/login", status_code=303)
    clear_session_cookie(resp, ctx)
    return resp
