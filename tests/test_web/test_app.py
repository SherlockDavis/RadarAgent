from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz(client: TestClient) -> None:
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_static_css_served(client: TestClient) -> None:
    resp = client.get("/static/style.css")
    assert resp.status_code == 200
    assert "RadarAgent" not in resp.text  # it's CSS, not the template
    assert "--accent" in resp.text
