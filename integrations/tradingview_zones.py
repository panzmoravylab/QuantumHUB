"""
TradingView institutional zones — stub pro Tier 5.

JSON schema (TRADINGVIEW_ZONES_PATH):
[
  {"label": "PDH", "price": 4085.0, "type": "resistance"},
  {"label": "OB", "price": 4060.0, "type": "support", "top": 4065.0, "bottom": 4055.0}
]
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Zone:
    label: str
    price: float
    zone_type: str
    top: float | None = None
    bottom: float | None = None


def load_zones(path: str | Path | None) -> list[Zone]:
    if not path:
        return []
    p = Path(path)
    if not p.exists():
        logger.debug("TradingView zones file missing: %s", p)
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
        zones: list[Zone] = []
        for item in raw:
            zones.append(
                Zone(
                    label=str(item.get("label", "")),
                    price=float(item.get("price", 0)),
                    zone_type=str(item.get("type", "level")),
                    top=float(item["top"]) if item.get("top") is not None else None,
                    bottom=float(item["bottom"]) if item.get("bottom") is not None else None,
                )
            )
        return zones
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("Failed to load TV zones: %s", exc)
        return []
