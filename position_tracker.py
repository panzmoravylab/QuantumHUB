"""Per-ticket MFE/MAE tracking and R-multiple helpers for open positions."""

from __future__ import annotations

import time
from dataclasses import dataclass

import MetaTrader5 as mt5


@dataclass(frozen=True)
class PositionTrackState:
    ticket: int
    open_ts: float
    mfe_r: float
    mae_r: float
    peak_profit_usd: float
    last_r: float | None


def calc_position_r(
    pos_type: int,
    price_open: float,
    sl: float,
    current: float,
) -> float | None:
    """Current unrealized R-multiple (SL-based only, TP not required)."""
    if sl == 0:
        return None
    if pos_type == mt5.ORDER_TYPE_BUY:
        risk = price_open - sl
        current_reward = current - price_open
    else:
        risk = sl - price_open
        current_reward = price_open - current
    if risk <= 0:
        return None
    return round(current_reward / risk, 2)


def calc_sl_distance_pts(pos_type: int, sl: float, current: float) -> float | None:
    if sl == 0:
        return None
    if pos_type == mt5.ORDER_TYPE_BUY:
        return round(abs(current - sl), 2)
    return round(abs(sl - current), 2)


def position_side(pos_type: int) -> str:
    return "BUY" if pos_type == mt5.ORDER_TYPE_BUY else "SELL"


def update_position_tracks(
    positions,
    previous: dict[int, PositionTrackState] | None,
) -> dict[int, PositionTrackState]:
    now = time.time()
    prev = dict(previous or {})
    tracks: dict[int, PositionTrackState] = {}

    for p in positions:
        r = getattr(p, "r_current", None)
        if r is None:
            r = calc_position_r(p.type, p.price_open, p.sl, p.price_current)

        old = prev.get(p.ticket)
        open_ts = old.open_ts if old else now
        mfe_r = old.mfe_r if old else (r or 0.0)
        mae_r = old.mae_r if old else (r or 0.0)
        peak_profit = old.peak_profit_usd if old else p.profit

        if r is not None:
            mfe_r = max(mfe_r, r)
            mae_r = min(mae_r, r)
        peak_profit = max(peak_profit, p.profit)

        tracks[p.ticket] = PositionTrackState(
            ticket=p.ticket,
            open_ts=open_ts,
            mfe_r=round(mfe_r, 2),
            mae_r=round(mae_r, 2),
            peak_profit_usd=round(peak_profit, 2),
            last_r=r,
        )

    return tracks
