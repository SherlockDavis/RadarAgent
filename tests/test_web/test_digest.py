from __future__ import annotations

from fastapi.testclient import TestClient


def _setup_sub(client: TestClient) -> None:
    client.post("/register", data={"email": "d@example.com", "password": "supersecret"})
    client.post(
        "/subscriptions",
        data={"name": "S", "interest_profile": "p", "schedule": "0 8 * * *"},
    )


def test_digest_detail_empty(client: TestClient) -> None:
    _setup_sub(client)
    resp = client.get("/digest/1/2026-05-17")
    assert resp.status_code == 200
    assert "还没有简报" in resp.text


def test_digest_run_then_view(client: TestClient) -> None:
    _setup_sub(client)
    run = client.post("/digest/1/2026-05-17/run", follow_redirects=False)
    assert run.status_code == 303
    assert run.headers["location"] == "/digest/1/2026-05-17"
    view = client.get("/digest/1/2026-05-17")
    assert view.status_code == 200
    assert "digest of" in view.text  # FakeLLM output


def test_digest_detail_foreign_subscription_bounces(client: TestClient) -> None:
    _setup_sub(client)
    client.get("/logout")
    client.post("/register", data={"email": "e@example.com", "password": "supersecret"})
    resp = client.get("/digest/1/2026-05-17", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
