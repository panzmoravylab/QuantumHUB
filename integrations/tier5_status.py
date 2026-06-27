"""Stav Tier 5 modulů pro boot log."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Tier5Status:
    tradingview: bool
    telegram: bool
    order_entry: bool

    def summary(self) -> str:
        parts = []
        if self.tradingview:
            parts.append("TV zóny")
        if self.telegram:
            parts.append("Telegram")
        if self.order_entry:
            parts.append("Order entry")
        if not parts:
            return "připraveno, neaktivní (viz docs/TIER5_ROADMAP.md)"
        return "aktivní: " + ", ".join(parts)


def _env_on(name: str) -> bool:
    return (os.getenv(name) or "").strip().lower() in ("1", "true", "yes", "on")


tier5_status = Tier5Status(
    tradingview=bool((os.getenv("TRADINGVIEW_ZONES_PATH") or "").strip()),
    telegram=bool((os.getenv("TELEGRAM_BOT_TOKEN") or "").strip())
    and bool((os.getenv("TELEGRAM_CHAT_ID") or "").strip()),
    order_entry=_env_on("ORDER_ENTRY_ENABLED"),
)
