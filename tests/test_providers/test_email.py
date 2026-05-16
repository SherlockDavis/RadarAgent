from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from radaragent.config import SMTPConfig
from radaragent.providers.notifier import EmailNotifier


@pytest.fixture
def smtp_cfg() -> SMTPConfig:
    return SMTPConfig(
        host="smtp.x.com",
        port=587,
        username="u",
        password="p",
        use_tls=True,
        from_addr="bot@x.com",
    )


async def test_send_success(smtp_cfg):
    notifier = EmailNotifier(smtp_cfg)
    with patch("radaragent.providers.notifier.email.aiosmtplib.send", new=AsyncMock()) as m:
        ok = await notifier.send("hello body", {"to": "me@x.com"})
    assert ok is True
    assert m.await_count == 1


async def test_send_missing_recipient_returns_false(smtp_cfg):
    notifier = EmailNotifier(smtp_cfg)
    ok = await notifier.send("body", {})
    assert ok is False


async def test_send_smtp_error_returns_false(smtp_cfg):
    notifier = EmailNotifier(smtp_cfg)
    with patch(
        "radaragent.providers.notifier.email.aiosmtplib.send",
        new=AsyncMock(side_effect=RuntimeError("smtp down")),
    ):
        ok = await notifier.send("body", {"to": "me@x.com"})
    assert ok is False
