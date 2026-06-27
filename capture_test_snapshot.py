"""
Capture live MT5 state into a JSON snapshot for TEST replay mode.

Usage:
    python capture_test_snapshot.py
    python capture_test_snapshot.py --output test_data/my_session.json
    python capture_test_snapshot.py --positions 3
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import MetaTrader5 as mt5
import pandas as pd

from config import BASE_DIR, MT5, UI

logger = logging.getLogger(__name__)

DEFAULT_OUTPUT = BASE_DIR / "test_data" / "default_snapshot.json"


def _pack_rates(rates) -> list[dict]:
    if rates is None:
        return []
    df = pd.DataFrame(rates)
    rows: list[dict] = []
    for _, row in df.iterrows():
        rows.append(
            {
                "time": int(row["time"]),
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"]),
                "tick_volume": float(row.get("tick_volume", 0)),
                "real_volume": float(row.get("real_volume", 0)),
                "spread": float(row.get("spread", 0)),
            }
        )
    return rows


def _select_symbol(candidates: tuple[str, ...]) -> str | None:
    for name in candidates:
        if not name:
            continue
        if mt5.symbol_info(name) is not None and mt5.symbol_select(name, True):
            return name
    return None


def _synthetic_positions(symbol: str, bid: float, ask: float, count: int) -> list[dict]:
    if count <= 0:
        return []
    positions: list[dict] = []
    templates = [
        (0, bid - 8.5, bid - 15.0, bid + 25.0, 0.05),
        (1, ask + 6.0, ask + 12.0, ask - 20.0, 0.03),
        (0, bid - 3.0, bid - 10.0, bid + 15.0, 0.02),
    ]
    for i in range(min(count, len(templates))):
        pos_type, entry, sl, tp, vol = templates[i]
        current = bid if pos_type == 0 else ask
        positions.append(
            {
                "ticket": 990001 + i,
                "symbol": symbol,
                "volume": vol,
                "profit": 0.0,
                "sl": sl,
                "tp": tp,
                "price_open": entry,
                "price_current": current,
                "type": pos_type,
            }
        )
    return positions


def capture(output: Path, m1_bars: int, positions: int) -> bool:
    kwargs: dict = {}
    if MT5.path:
        kwargs["path"] = MT5.path

    if not mt5.initialize(**kwargs):
        logger.error("MT5 initialize failed: %s", mt5.last_error())
        return False

    try:
        if MT5.login and MT5.password and MT5.server:
            if not mt5.login(MT5.login, MT5.password, MT5.server):
                logger.error("MT5 login failed: %s", mt5.last_error())
                return False

        gold = _select_symbol((MT5.symbol, "XAUUSD", "GOLD"))
        if not gold:
            logger.error("Gold symbol not found")
            return False

        dxy = _select_symbol((MT5.dxy_symbol, "USDX", "DXY", "USDIDX")) or ""
        if dxy:
            mt5.symbol_select(dxy, True)

        acc = mt5.account_info()
        info = mt5.symbol_info(gold)
        tick = mt5.symbol_info_tick(gold)
        if acc is None or info is None or tick is None:
            logger.error("Missing account/symbol/tick data")
            return False

        spread = (tick.ask - tick.bid) / info.point if info.point else 15.0

        live_positions = mt5.positions_get(symbol=gold) or []
        if live_positions:
            pos_rows = [
                {
                    "ticket": int(p.ticket),
                    "symbol": p.symbol,
                    "volume": float(p.volume),
                    "profit": float(p.profit),
                    "sl": float(p.sl),
                    "tp": float(p.tp),
                    "price_open": float(p.price_open),
                    "price_current": float(p.price_current),
                    "type": int(p.type),
                }
                for p in live_positions
            ]
        else:
            pos_rows = _synthetic_positions(gold, float(tick.bid), float(tick.ask), positions)

        snapshot = {
            "meta": {
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "symbol": gold,
                "dxy_symbol": dxy,
                "source": "mt5_capture",
            },
            "symbol_params": {
                "tick_value": float(info.trade_tick_value),
                "tick_size": float(info.trade_tick_size),
                "volume_min": float(info.volume_min),
                "volume_max": float(info.volume_max),
                "volume_step": float(info.volume_step),
            },
            "account": {
                "login": int(acc.login),
                "company": acc.company,
                "balance": float(acc.balance),
                "equity": float(acc.equity),
                "margin": float(acc.margin),
                "free_margin": float(acc.margin_free),
            },
            "positions": pos_rows,
            "market_seed": {
                "bid": float(tick.bid),
                "ask": float(tick.ask),
                "spread_points": float(spread),
            },
            "rates": {
                "m1": _pack_rates(mt5.copy_rates_from_pos(gold, mt5.TIMEFRAME_M1, 0, m1_bars)),
                "m5": _pack_rates(mt5.copy_rates_from_pos(gold, mt5.TIMEFRAME_M5, 0, m1_bars)),
                "m15": _pack_rates(mt5.copy_rates_from_pos(gold, mt5.TIMEFRAME_M15, 0, max(200, m1_bars // 3))),
                "h1": _pack_rates(mt5.copy_rates_from_pos(gold, mt5.TIMEFRAME_H1, 0, 100)),
                "dxy_m5": _pack_rates(mt5.copy_rates_from_pos(dxy, mt5.TIMEFRAME_M5, 0, m1_bars))
                if dxy
                else [],
            },
            "replay": {
                "start_index": min(UI.chart_bars_m1, max(60, m1_bars // 3)),
                "speed_bars_per_sec": 0.5,
                "loop": True,
                "spread_spike_every": 45,
                "spread_spike_multiplier": 2.2,
            },
        }

        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        logger.info(
            "Saved %s — M1=%d bars, positions=%d",
            output,
            len(snapshot["rates"]["m1"]),
            len(pos_rows),
        )
        return True
    finally:
        mt5.shutdown()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    parser = argparse.ArgumentParser(description="Capture MT5 snapshot for TEST replay mode")
    parser.add_argument("--output", "-o", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--bars", type=int, default=300, help="M1/M5 bars to capture")
    parser.add_argument(
        "--positions",
        type=int,
        default=2,
        help="Synthetic test positions if none open on account",
    )
    args = parser.parse_args()

    ok = capture(args.output.resolve(), args.bars, args.positions)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
