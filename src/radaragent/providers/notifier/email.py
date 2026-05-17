from __future__ import annotations

import logging
from email.message import EmailMessage
from typing import Any

import aiosmtplib

from radaragent.config import SMTPConfig
from radaragent.providers.notifier.base import Notifier

logger = logging.getLogger(__name__)


class EmailNotifier(Notifier):
    def __init__(self, cfg: SMTPConfig) -> None:
        self._cfg = cfg

    async def send(self, content: str, channel_config: dict[str, Any]) -> bool:
        to = channel_config.get("to")
        if not to:
            logger.warning("email channel_config missing 'to'; skipping")
            return False
        msg = EmailMessage()
        msg["From"] = self._cfg.from_addr
        msg["To"] = to
        msg["Subject"] = channel_config.get("subject", "RadarAgent 简报")
        msg.set_content(content)
        try:
            await aiosmtplib.send(
                msg,
                hostname=self._cfg.host,
                port=self._cfg.port,
                username=self._cfg.username,
                password=self._cfg.password,
                start_tls=self._cfg.use_tls,
            )
            return True
        except Exception:
            logger.exception("email send to %s failed", to)
            return False
