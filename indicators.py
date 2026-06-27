"""
Technical indicators: ATR, Bollinger Bands, FVG, PDH/PDL, MTF bias, DXY correlation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from config import INDICATORS


class TrendBias(str, Enum):
    BULL = "BULL"
    BEAR = "BEAR"
    NEUTRAL = "NEUTRAL"


@dataclass
class FVGZone:
    direction: str  # "bullish" | "bearish"
    top: float
    bottom: float
    start_time: pd.Timestamp
    end_time: pd.Timestamp


@dataclass
class BBSqueezeResult:
    upper: pd.Series
    middle: pd.Series
    lower: pd.Series
    bandwidth: pd.Series
    is_squeeze: bool
    squeeze_threshold: float


@dataclass
class IndicatorBundle:
    atr: float
    atr_series: pd.Series
    bb: BBSqueezeResult
    fvg_zones: list[FVGZone]
    pdh: float | None
    pdl: float | None
    mtf_bias: dict[str, TrendBias]
    dxy_correlation: float | None
    dxy_smt_divergence: str | None = None
    dxy_momentum_dir: str | None = None


def calc_atr(df: pd.DataFrame, period: int = INDICATORS.atr_period) -> tuple[float, pd.Series]:
    """Calculate ATR value and full series."""
    if df.empty or len(df) < 2:
        empty = pd.Series(dtype=float)
        return 0.0, empty

    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr_series = tr.rolling(window=period, min_periods=1).mean()
    current = float(atr_series.iloc[-1]) if len(atr_series) else 0.0
    return current, atr_series


def calc_bollinger_bands(
    df: pd.DataFrame,
    period: int = INDICATORS.bb_period,
    std_dev: float = INDICATORS.bb_std,
) -> BBSqueezeResult:
    """Bollinger Bands with squeeze detection (lowest 10th percentile bandwidth)."""
    if df.empty:
        empty = pd.Series(dtype=float)
        return BBSqueezeResult(empty, empty, empty, empty, False, 0.0)

    close = df["close"]
    middle = close.rolling(window=period, min_periods=1).mean()
    std = close.rolling(window=period, min_periods=1).std().fillna(0)
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    bandwidth = (upper - lower) / middle.replace(0, np.nan)
    bandwidth = bandwidth.fillna(0)

    threshold = float(np.percentile(bandwidth.dropna(), INDICATORS.bb_squeeze_percentile)) if len(bandwidth) > 5 else 0.0
    is_squeeze = bool(len(bandwidth) and bandwidth.iloc[-1] <= threshold and threshold > 0)

    return BBSqueezeResult(
        upper=upper,
        middle=middle,
        lower=lower,
        bandwidth=bandwidth,
        is_squeeze=is_squeeze,
        squeeze_threshold=threshold,
    )


def detect_fvg(df: pd.DataFrame, lookback: int = 50) -> list[FVGZone]:
    """
    Detect Fair Value Gaps (3-candle imbalance structures).
    Bullish FVG: candle_1 high < candle_3 low
    Bearish FVG: candle_1 low > candle_3 high
    """
    zones: list[FVGZone] = []
    if len(df) < 3:
        return zones

    subset = df.tail(lookback).reset_index(drop=True)
    for i in range(len(subset) - 2):
        c1 = subset.iloc[i]
        c3 = subset.iloc[i + 2]

        # Bullish FVG
        if c1["high"] < c3["low"]:
            zones.append(
                FVGZone(
                    direction="bullish",
                    top=float(c3["low"]),
                    bottom=float(c1["high"]),
                    start_time=c1["time"] if "time" in c1 else pd.Timestamp.now(),
                    end_time=c3["time"] if "time" in c3 else pd.Timestamp.now(),
                )
            )

        # Bearish FVG
        if c1["low"] > c3["high"]:
            zones.append(
                FVGZone(
                    direction="bearish",
                    top=float(c1["low"]),
                    bottom=float(c3["high"]),
                    start_time=c1["time"] if "time" in c1 else pd.Timestamp.now(),
                    end_time=c3["time"] if "time" in c3 else pd.Timestamp.now(),
                )
            )

    return zones[-8:]  # keep recent zones only for chart clarity


def calc_pdh_pdl(df: pd.DataFrame) -> tuple[float | None, float | None]:
    """Previous Day High / Low from intraday or daily data."""
    if df.empty or "time" not in df.columns:
        return None, None

    df = df.copy()
    df["date"] = df["time"].dt.date
    dates = sorted(df["date"].unique())
    if len(dates) < 2:
        return None, None

    prev_day = df[df["date"] == dates[-2]]
    if prev_day.empty:
        return None, None

    return float(prev_day["high"].max()), float(prev_day["low"].min())


def _ema_slope_bias(df: pd.DataFrame, period: int = INDICATORS.mtf_ema_period) -> TrendBias:
    if len(df) < period + 2:
        return TrendBias.NEUTRAL

    close = df["close"]
    ema = close.ewm(span=period, adjust=False).mean()
    slope = float(ema.iloc[-1] - ema.iloc[-3])
    price = float(close.iloc[-1])
    ema_val = float(ema.iloc[-1])

    if slope > 0 and price > ema_val:
        return TrendBias.BULL
    if slope < 0 and price < ema_val:
        return TrendBias.BEAR
    return TrendBias.NEUTRAL


def calc_mtf_bias(
    m1: pd.DataFrame,
    m5: pd.DataFrame,
    m15: pd.DataFrame,
    h1: pd.DataFrame,
) -> dict[str, TrendBias]:
    """Multi-timeframe trend bias using EMA slope."""
    return {
        "M1": _ema_slope_bias(m1),
        "M5": _ema_slope_bias(m5),
        "M15": _ema_slope_bias(m15),
        "H1": _ema_slope_bias(h1),
    }


def calc_dxy_correlation(
    xau_df: pd.DataFrame,
    dxy_df: pd.DataFrame,
    period: int = INDICATORS.correlation_period,
) -> float | None:
    """Rolling correlation between XAUUSD and DXY closes (expect negative)."""
    if xau_df.empty or dxy_df.empty:
        return None

    xau = xau_df[["time", "close"]].copy().rename(columns={"close": "xau"})
    dxy = dxy_df[["time", "close"]].copy().rename(columns={"close": "dxy"})

    merged = pd.merge_asof(
        xau.sort_values("time"),
        dxy.sort_values("time"),
        on="time",
        direction="nearest",
        tolerance=pd.Timedelta("10min"),
    ).dropna()

    if len(merged) < period:
        return None

    corr = merged["xau"].tail(period).corr(merged["dxy"].tail(period))
    return float(corr) if not np.isnan(corr) else None


def build_indicator_bundle(
    m1: pd.DataFrame,
    m5: pd.DataFrame,
    m15: pd.DataFrame,
    h1: pd.DataFrame,
    dxy_m5: pd.DataFrame,
) -> IndicatorBundle:
    """Aggregate all indicators for dashboard consumption."""
    atr, atr_series = calc_atr(m1)
    bb = calc_bollinger_bands(m1)
    fvg = detect_fvg(m1)
    pdh, pdl = calc_pdh_pdl(m1 if len(m1) > 100 else h1)
    mtf = calc_mtf_bias(m1, m5, m15, h1)
    corr = calc_dxy_correlation(m5, dxy_m5)
    
    # Calculate SMT Divergence and DXY Momentum direction
    smt_div, dxy_mom = calc_smt_divergence(m5, dxy_m5)

    return IndicatorBundle(
        atr=atr,
        atr_series=atr_series,
        bb=bb,
        fvg_zones=fvg,
        pdh=pdh,
        pdl=pdl,
        mtf_bias=mtf,
        dxy_correlation=corr,
        dxy_smt_divergence=smt_div,
        dxy_momentum_dir=dxy_mom,
    )


def calc_smt_divergence(
    xau_df: pd.DataFrame,
    dxy_df: pd.DataFrame,
    period: int = 3
) -> tuple[str, str]:
    """
    Calculate SMT Divergence based on momentum of XAUUSD and DXY.
    Returns (divergence_type, dxy_direction)
    """
    if xau_df is None or dxy_df is None or xau_df.empty or dxy_df.empty:
        return "NORMAL", "NEUTRAL"

    # Merge closing prices
    xau = xau_df[["time", "close"]].copy().rename(columns={"close": "xau"})
    dxy = dxy_df[["time", "close"]].copy().rename(columns={"close": "dxy"})

    import pandas as pd
    merged = pd.merge_asof(
        xau.sort_values("time"),
        dxy.sort_values("time"),
        on="time",
        direction="nearest",
        tolerance=pd.Timedelta("10min"),
    ).dropna()

    if len(merged) < period + 1:
        return "NORMAL", "NEUTRAL"

    # Calculate ROC over the period (typically 3-period)
    xau_last = float(merged["xau"].iloc[-1])
    xau_prev = float(merged["xau"].iloc[-1 - period])
    xau_roc = xau_last - xau_prev

    dxy_last = float(merged["dxy"].iloc[-1])
    dxy_prev = float(merged["dxy"].iloc[-1 - period])
    dxy_roc = dxy_last - dxy_prev

    dxy_dir = "BULL" if dxy_roc > 0 else "BEAR" if dxy_roc < 0 else "NEUTRAL"

    # SMT Divergence logic
    # Normally XAU and DXY are negatively correlated.
    # If they are BOTH rising (positive correlation on momentum):
    if dxy_roc > 0 and xau_roc > 0:
        return "BULLISH_SMT", dxy_dir
    # If they are BOTH falling:
    elif dxy_roc < 0 and xau_roc < 0:
        return "BEARISH_SMT", dxy_dir
    
    return "NORMAL", dxy_dir
