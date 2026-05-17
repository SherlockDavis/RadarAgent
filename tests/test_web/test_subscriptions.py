from __future__ import annotations

from fastapi.testclient import TestClient

from radaragent.web import WebContext


def _register(client: TestClient) -> None:
    client.post("/register", data={"email": "owner@example.com", "password": "supersecret"})


def test_dashboard_requires_auth(client: TestClient) -> None:
    resp = client.get("/", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/login"


def test_dashboard_empty_state(client: TestClient) -> None:
    _register(client)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "我的订阅" in resp.text
    assert "创建第一个" in resp.text


def test_create_subscription_flow(client: TestClient, web_ctx: WebContext) -> None:
    _register(client)
    resp = client.post(
        "/subscriptions",
        data={
            "name": "AI 前沿",
            "interest_profile": "大模型 / agent / 推理",
            "schedule": "0 8 * * *",
            "format": "digest",
            "min_score": "7",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert web_ctx.rescheduled  # type: ignore[attr-defined]
    page = client.get("/")
    assert "AI 前沿" in page.text


def test_create_subscription_bad_cron(client: TestClient) -> None:
    _register(client)
    resp = client.post(
        "/subscriptions",
        data={
            "name": "x",
            "interest_profile": "y",
            "schedule": "not a cron",
        },
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "cron" in resp.text


def test_toggle_and_delete(client: TestClient) -> None:
    _register(client)
    client.post(
        "/subscriptions",
        data={"name": "S", "interest_profile": "p", "schedule": "0 8 * * *"},
    )
    client.post("/subscriptions/1/toggle", follow_redirects=False)
    page = client.get("/")
    assert "停用" in page.text  # toggled off -> badge shows 停用

    client.post("/subscriptions/1/delete", follow_redirects=False)
    page2 = client.get("/")
    assert "创建第一个" in page2.text


def test_cannot_touch_other_users_subscription(client: TestClient) -> None:
    _register(client)
    client.post(
        "/subscriptions",
        data={"name": "S", "interest_profile": "p", "schedule": "0 8 * * *"},
    )
    client.get("/logout")
    client.post("/register", data={"email": "intruder@example.com", "password": "supersecret"})
    resp = client.post("/subscriptions/1/delete", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"  # bounced, not deleted
