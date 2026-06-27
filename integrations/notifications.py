"""
Telegram / externí notifikace — stub pro Tier 5.
"""

from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request

logger = logging.getLogger(__name__)


def notify(title: str, body: str, channel: str = "telegram") -> bool:
    if channel != "telegram":
        logger.debug("Unsupported notify channel: %s", channel)
        return False
    token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        logger.debug("Telegram not configured")
        return False
    text = f"{title}\n{body}"
    url = (
        f"https://api.telegram.org/bot{token}/sendMessage?"
        + urllib.parse.urlencode({"chat_id": chat_id, "text": text})
    )
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            return resp.status == 200
    except OSError as exc:
        logger.warning("Telegram notify failed: %s", exc)
        return False
