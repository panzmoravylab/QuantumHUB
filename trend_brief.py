"""Trend briefing for Příprava tier — daily bias ratio and intraday strength."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd

from config import RISK
from indicators import IndicatorBundle, TrendBias
from mt5_connector import MarketSnapshot
from trading_style import StyleGuide

_DAILY_SOURCE_LABEL = "od půlnoci CET"


@dataclass(frozen=True)
class TrendBrief:
    daily_dominant: str
    daily_buy_pct: float
    daily_sell_pct: float
    daily_source_tf: str
    daily_bar_count: int
    now_direction: str
    strength_now: int
    strength_prev: int
    strength_delta: int
    strength_source_tf: str
    strength_history: tuple[int, ...]
    mtf: dict[str, TrendBias]


def _bars_today(df: pd.DataFrame, now: datetime, tz: ZoneInfo) -> pd.DataFrame:
    if df is None or df.empty or "time" not in df.columns:
        return pd.DataFrame()
    local = df.copy()
    times = pd.to_datetime(local["time"])
    if times.dt.tz is None:
        times = times.dt.tz_localize(tz)
    else:
        times = times.dt.tz_convert(tz)
    today = now.astimezone(tz).date()
    mask = times.dt.date == today
    filtered = local.loc[mask]
    return filtered if not filtered.empty else local.tail(min(12, len(local)))


def _daily_buy_sell_pct(
    market: MarketSnapshot | None,
    now: datetime,
    tz: ZoneInfo,
) -> tuple[float, float, str, str, int]:
    if not market:
        return 50.0, 50.0, "MIXED", _DAILY_SOURCE_LABEL, 0

    h1 = _bars_today(market.h1_rates, now, tz)
    m15 = _bars_today(market.m15_rates, now, tz)
    frames: list[tuple[str, pd.DataFrame]] = []
    if not h1.empty:
        frames.append(("H1", h1))
    if not m15.empty:
        frames.append(("M15", m15))

    if not frames:
        return 50.0, 50.0, "MIXED", _DAILY_SOURCE_LABEL, 0

    bulls = 0
    bears = 0
    bar_count = 0
    for _label, df in frames:
        for _, row in df.iterrows():
            bar_count += 1
            o = float(row.get("open", 0))
            c = float(row.get("close", 0))
            if c > o:
                bulls += 1
            elif c < o:
                bears += 1

    total = bulls + bears
    if total == 0:
        return 50.0, 50.0, "MIXED", _DAILY_SOURCE_LABEL, bar_count

    buy_pct = round(bulls / total * 100, 1)
    sell_pct = round(bears / total * 100, 1)
    if buy_pct >= 55:
        dominant = "BUY"
    elif sell_pct >= 55:
        dominant = "SELL"
    else:
        dominant = "MIXED"
    return buy_pct, sell_pct, dominant, _DAILY_SOURCE_LABEL, bar_count


def map_strength(mtf_score: int, atr_ratio: float, atr_impulse: bool) -> int:
    base = min(10, max(1, int(round(mtf_score * 2.2))))
    if atr_ratio >= 1.4 or atr_impulse:
        base = min(10, base + 2)
    elif atr_ratio <= 0.75:
        base = max(1, base - 1)
    return int(max(1, min(10, base)))


def _now_direction(mtf: dict[str, TrendBias]) -> str:
    bulls = sum(1 for b in mtf.values() if b == TrendBias.BULL)
    bears = sum(1 for b in mtf.values() if b == TrendBias.BEAR)
    if bulls >= 3:
        return "BUY"
    if bears >= 3:
        return "SELL"
    return "NEUTRAL"


def build_trend_brief(
    market: MarketSnapshot | None,
    indicators: IndicatorBundle | None,
    style_guide: StyleGuide | None,
    strength_history: list[tuple[float, int]] | None,
    now: datetime | None = None,
) -> TrendBrief:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)

    buy_pct, sell_pct, dominant, source, bar_count = _daily_buy_sell_pct(market, now, tz)
    mtf = indicators.mtf_bias if indicators else {}
    now_dir = _now_direction(mtf)

    mtf_score = style_guide.metrics.mtf_score if style_guide else 0
    atr_ratio = style_guide.metrics.atr_ratio if style_guide else 1.0
    atr_impulse = bool(market and market.atr_impulse)
    strength_now = map_strength(mtf_score, atr_ratio, atr_impulse)

    history_vals = [s for _t, s in (strength_history or [])]
    strength_prev = history_vals[-6] if len(history_vals) >= 6 else (
        history_vals[0] if history_vals else strength_now
    )
    strength_delta = strength_now - strength_prev

    spark = tuple(history_vals[-30:] if history_vals else [strength_now])

    return TrendBrief(
        daily_dominant=dominant,
        daily_buy_pct=buy_pct,
        daily_sell_pct=sell_pct,
        daily_source_tf=source,
        daily_bar_count=bar_count,
        now_direction=now_dir,
        strength_now=strength_now,
        strength_prev=strength_prev,
        strength_delta=strength_delta,
        strength_source_tf="M5 MTF alignment + ATR",
        strength_history=spark,
        mtf=mtf,
    )
