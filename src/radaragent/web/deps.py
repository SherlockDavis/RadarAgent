from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import Request
from fastapi.templating import Jinja2Templates

from radaragent.users import get_user

if TYPE_CHECKING:
    from radaragent.users import User
    from radaragent.web.context import WebContext

_TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))


class RedirectException(Exception):
    """Raised by ``require_user`` to bounce unauthenticated requests to /login.

    Handled by an app-level exception handler (HTML redirect) rather than the
    default JSON 401, since these are browser-facing routes.
    """

    def __init__(self, location: str) -> None:
        self.location = location


def get_ctx(request: Request) -> WebContext:
    ctx: WebContext = request.app.state.ctx
    return ctx


def current_user(request: Request) -> User | None:
    """Resolve the session cookie to a User, or None when absent/expired."""
    ctx = get_ctx(request)
    token = request.cookies.get(ctx.settings.web.session_cookie)
    if not token:
        return None
    user_id = ctx.sessions.resolve(token)
    if user_id is None:
        return None
    return get_user(ctx.db, user_id)


def require_user(request: Request) -> User:
    user = current_user(request)
    if user is None:
        raise RedirectException("/login")
    return user
