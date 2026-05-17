from __future__ import annotations

from fastapi.testclient import TestClient

from radaragent.subscriptions import record_score
from radaragent.web import WebContext


def _setup(client: TestClient) -> None:
    client.post("/register", data={"email": "q@example.com", "password": "supersecret"})
    client.post(
        "/subscriptions",
        data={"name": "S", "interest_profile": "p", "schedule": "0 8 * * *"},
    )


def test_ask_form_and_answer(client: TestClient) -> None:
    _setup(client)
    assert client.get("/ask").status_code == 200
    resp = client.post("/ask", data={"question": "什么新鲜事?"})
    assert resp.status_code == 200
    assert "回答" in resp.text  # no scored articles -> canned answer still rendered


def test_api_query_json(client: TestClient) -> None:
    _setup(client)
    resp = client.post("/api/query", json={"question": "hello"})
    assert resp.status_code == 200
    body = resp.json()
    assert "text" in body and "sources" in body


def test_search_filters(client: TestClient, web_ctx: WebContext) -> None:
    _setup(client)
    record_score(web_ctx.db, "aid-1", 1, 8.0, "quantum computing summary", ["t"], None)

    empty = client.get("/search")
    assert empty.status_code == 200
    assert "quantum computing summary" in empty.text

    hit = client.get("/search", params={"q": "quantum", "min_score": 5})
    assert "quantum computing summary" in hit.text

    miss = client.get("/search", params={"q": "biology"})
    assert "没有匹配的文章" in miss.text

    score_miss = client.get("/search", params={"min_score": 9})
    assert "没有匹配的文章" in score_miss.text
