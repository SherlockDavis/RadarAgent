from __future__ import annotations

from fastapi.testclient import TestClient


def test_register_sets_session_and_redirects(client: TestClient) -> None:
    resp = client.post(
        "/register",
        data={"email": "me@example.com", "password": "supersecret"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert "ra_session" in resp.cookies


def test_register_rejects_short_password(client: TestClient) -> None:
    resp = client.post(
        "/register",
        data={"email": "x@example.com", "password": "short"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "8" in resp.text


def test_register_rejects_duplicate_email(client: TestClient) -> None:
    client.post("/register", data={"email": "dup@example.com", "password": "supersecret"})
    resp = client.post(
        "/register",
        data={"email": "dup@example.com", "password": "supersecret"},
        follow_redirects=False,
    )
    assert resp.status_code == 400
    assert "registered" in resp.text


def test_login_wrong_password(client: TestClient) -> None:
    client.post("/register", data={"email": "a@example.com", "password": "supersecret"})
    resp = client.post(
        "/login",
        data={"email": "a@example.com", "password": "wrongpass"},
        follow_redirects=False,
    )
    assert resp.status_code == 400


def test_login_then_logout(client: TestClient) -> None:
    client.post("/register", data={"email": "b@example.com", "password": "supersecret"})
    # registering already logged us in; logging in again should still work
    resp = client.post(
        "/login",
        data={"email": "b@example.com", "password": "supersecret"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert "ra_session" in resp.cookies

    out = client.get("/logout", follow_redirects=False)
    assert out.status_code == 303
    assert out.headers["location"] == "/login"


def test_login_form_renders(client: TestClient) -> None:
    resp = client.get("/login")
    assert resp.status_code == 200
    assert "登录" in resp.text
