"""
Order entry z HUD — stub pro Tier 5. Vypnuto defaultně.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OrderRequest:
    symbol: str
    volume: float
    side: str
    sl: float = 0.0
    tp: float = 0.0


@dataclass(frozen=True)
class OrderResult:
    ok: bool
    message: str
    ticket: int = 0


def is_enabled() -> bool:
    return (os.getenv("ORDER_ENTRY_ENABLED") or "").strip().lower() in ("1", "true", "yes", "on")


def place_order(request: OrderRequest) -> OrderResult:
    if not is_enabled():
        return OrderResult(False, "Order entry vypnuto — nastavte ORDER_ENTRY_ENABLED=true")
    logger.info("Order entry stub: %s %s %.2f", request.side, request.symbol, request.volume)
    return OrderResult(False, "Order entry stub — implementace v Tier 5 follow-up")
