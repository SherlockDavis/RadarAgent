from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from starlette.responses import Response

from radaragent.service import SearchFilters, ServiceAPI
from radaragent.users import User
from radaragent.web.context import WebContext
from radaragent.web.deps import get_ctx, require_user, templates

router = APIRouter()


def _api(ctx: WebContext) -> ServiceAPI:
    return ServiceAPI(
        ctx.db,
        ctx.store,
        ctx.llm,
        ctx.embedder,
        ctx.settings.digest.history_context_size,
    )


@router.get("/ask", response_class=HTMLResponse)
def ask_form(
    request: Request,
    user: Annotated[User, Depends(require_user)],
) -> Response:
    return templates.TemplateResponse(request, "ask.html", {"user": user})


@router.post("/ask", response_class=HTMLResponse)
async def ask_submit(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    question: Annotated[str, Form()],
) -> Response:
    ctx = get_ctx(request)
    answer = await _api(ctx).query(user.id, question.strip())
    return templates.TemplateResponse(
        request,
        "ask.html",
        {
            "user": user,
            "question": question,
            "answer": answer.text,
            "sources": answer.sources,
        },
    )


class QueryBody(BaseModel):
    question: str


@router.post("/api/query")
async def api_query(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    body: QueryBody,
) -> dict[str, object]:
    ctx = get_ctx(request)
    answer = await _api(ctx).query(user.id, body.question.strip())
    return {"text": answer.text, "sources": answer.sources}


@router.get("/search", response_class=HTMLResponse)
def search(
    request: Request,
    user: Annotated[User, Depends(require_user)],
    q: str = "",
    min_score: float = 0.0,
    source: str = "",
) -> Response:
    ctx = get_ctx(request)
    keywords = [k.strip() for k in q.split(",") if k.strip()]
    results = _api(ctx).search(
        user.id,
        SearchFilters(keywords=keywords, min_score=min_score, source=source or None),
    )
    return templates.TemplateResponse(
        request,
        "search.html",
        {
            "user": user,
            "results": results,
            "q": q,
            "min_score": min_score,
            "source": source,
        },
    )
