"""
MT5 Signal Lab — vlastní analytické výpočty pro M1 XAUUSD (fáze 1).
Čte OHLC z MT5 snapshotu, vrací jednoduché signály pro dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass
class SignalItem:
    label: str
    value: str
    hint: str
    tone: str = "neutral"  # bull | bear | warn | neutral


@dataclass
class M1Verdict:
    direction: str  # LONG | SHORT | NEUTRAL | WAIT
    headline: str
    key_signals: list[SignalItem]


_KEY_LABELS = (
    "M5 momentum",
    "Spread",
    "Tick volume",
    "Efficiency (20)",
    "Od PDH",
    "Od PDL",
    "Denní range / ATR",
)


def pick_key_signals(signals: list[SignalItem], limit: int = 4) -> list[SignalItem]:
    picked: list[SignalItem] = []
    by_label = {s.label: s for s in signals}
    for label in _KEY_LABELS:
        if label in by_label:
            picked.append(by_label[label])
        if len(picked) >= limit:
            return picked
    for s in signals:
        if s not in picked:
            picked.append(s)
        if len(picked) >= limit:
            break
    return picked


def synthesize_m1_verdict(lab: SignalLabSnapshot | None) -> M1Verdict:
    if not lab or not lab.signals:
        return M1Verdict("WAIT", "Čekám na M1 data z MT5", [])

    bulls = sum(1 for s in lab.signals if s.tone == "bull")
    bears = sum(1 for s in lab.signals if s.tone == "bear")
    keys = pick_key_signals(lab.signals, 4)

    if lab.regime in ("SWEEP", "EXTENDED"):
        return M1Verdict("WAIT", lab.headline, keys)

    m5 = next((s for s in lab.signals if s.label == "M5 momentum"), None)
    if m5 and m5.value == "BULL" and bulls >= bears:
        direction = "LONG"
    elif m5 and m5.value == "BEAR" and bears >= bulls:
        direction = "SHORT"
    elif bulls >= bears + 2:
        direction = "LONG"
    elif bears >= bulls + 2:
        direction = "SHORT"
    else:
        direction = "NEUTRAL"

    return M1Verdict(direction, lab.headline, keys)


@dataclass
class SignalLabSnapshot:
    headline: str
    regime: str
    signals: list[SignalItem]


def _efficiency_ratio(closes: pd.Series, period: int = 20) -> float | None:
    if len(closes) < period + 1:
        return None
    tail = closes.tail(period + 1)
    change = abs(float(tail.iloc[-1] - tail.iloc[0]))
    noise = float(tail.diff().abs().sum())
    if noise <= 0:
        return 0.0
    return round(change / noise, 2)


def _session_range_atr(m1: pd.DataFrame, atr: float) -> float | None:
    if m1.empty or atr <= 0 or "time" not in m1.columns:
        return None
    today = m1["time"].dt.date.iloc[-1]
    today_df = m1[m1["time"].dt.date == today]
    if today_df.empty:
        return None
    range_pts = float(today_df["high"].max() - today_df["low"].min())
    return round(range_pts / atr, 2)


def compute_signal_lab(
    m1: pd.DataFrame,
    m5: pd.DataFrame,
    bid: float,
    atr: float,
    pdh: float | None,
    pdl: float | None,
    spread_pts: float,
    spread_median: float,
) -> SignalLabSnapshot:
    signals: list[SignalItem] = []

    if m1.empty or atr <= 0 or bid <= 0:
        return SignalLabSnapshot(
            headline="Čekám na M1 data z MT5",
            regime="—",
            signals=[],
        )

    last = m1.iloc[-1]
    body = abs(float(last["close"] - last["open"]))
    full_range = float(last["high"] - last["low"])
    body_pct = round((body / full_range * 100) if full_range > 0 else 0, 0)

    session_atr = _session_range_atr(m1, atr)
    if session_atr is not None:
        tone = "warn" if session_atr >= 1.8 else "neutral"
        signals.append(
            SignalItem(
                "Denní range / ATR",
                f"{session_atr:.1f}×",
                "Kolik ATR už dnes urazil trh — nad 1.8× = vyčerpaný den",
                tone,
            )
        )

    if pdh is not None:
        dist = bid - pdh
        signals.append(
            SignalItem(
                "Od PDH",
                f"{dist:+.0f} pts",
                "Nad PDH = breakout | pod = resistance test",
                "bull" if dist > 0 else "bear",
            )
        )
    if pdl is not None:
        dist = bid - pdl
        signals.append(
            SignalItem(
                "Od PDL",
                f"{dist:+.0f} pts",
                "Pod PDL = breakdown | nad = support hold",
                "bear" if dist < 0 else "bull",
            )
        )

    # Liquidity sweep: wick beyond PDH/PDL but close back inside
    if pdh is not None and float(last["high"]) > pdh and float(last["close"]) < pdh:
        signals.append(
            SignalItem(
                "Sweep PDH",
                "DETEKOVÁNO",
                "Wick nad včerejní high + close pod → možný short / fade",
                "warn",
            )
        )
    if pdl is not None and float(last["low"]) < pdl and float(last["close"]) > pdl:
        signals.append(
            SignalItem(
                "Sweep PDL",
                "DETEKOVÁNO",
                "Wick pod včerejní low + close nad → možný long / fade",
                "warn",
            )
        )

    er = _efficiency_ratio(m1["close"])
    if er is not None:
        regime = "TREND" if er >= 0.45 else "CHOP"
        signals.append(
            SignalItem(
                "Efficiency (20)",
                f"{er:.2f}",
                "Trend >0.45 | Chop <0.35 — jak čistý je pohyb",
                "bull" if er >= 0.45 else "warn",
            )
        )
    else:
        regime = "—"

    if "real_volume" in m1.columns and m1["real_volume"].sum() > 0:
        vol = m1["real_volume"].astype(float)
    elif "tick_volume" in m1.columns:
        vol = m1["tick_volume"].astype(float)
    else:
        vol = None

    if vol is not None and vol.sum() > 0:
        avg = float(vol.tail(20).mean())
        last_vol = float(vol.iloc[-1])
        if avg > 0:
            vol_ratio = round(last_vol / avg, 2)
            signals.append(
                SignalItem(
                    "Tick volume",
                    f"{vol_ratio:.1f}× avg",
                    "Impuls >1.5× | Vyčerpání <0.6×",
                    "warn" if vol_ratio >= 1.5 else "neutral",
                )
            )

    if not m5.empty and len(m5) >= 6:
        c = m5["close"].tail(6)
        slope = float(c.iloc[-1] - c.iloc[0])
        m5_bias = "BULL" if slope > atr * 0.3 else "BEAR" if slope < -atr * 0.3 else "FLAT"
        signals.append(
            SignalItem(
                "M5 momentum",
                m5_bias,
                "Krátkodobý směr posledních 6 M5 svíček",
                "bull" if m5_bias == "BULL" else "bear" if m5_bias == "BEAR" else "neutral",
            )
        )

    spread_ratio = spread_pts / spread_median if spread_median > 0 else 1.0
    signals.append(
        SignalItem(
            "Spread",
            f"{spread_pts:.0f}p",
            f"vs medián {spread_median:.0f}p — execution cost",
            "warn" if spread_ratio > 1.5 else "neutral",
        )
    )

    signals.append(
        SignalItem(
            "M1 tělo svíčky",
            f"{body_pct:.0f}%",
            "Malé tělo = indecision | velké = impuls",
            "warn" if body_pct < 25 and full_range > atr * 0.5 else "neutral",
        )
    )

    # Headline synthesis
    sweeps = sum(1 for s in signals if "Sweep" in s.label)
    if sweeps:
        headline = "Liquidity sweep — čekej reakci, ne chase"
        regime = "SWEEP"
    elif er is not None and er >= 0.45:
        headline = "Trendový režim — obchoduj pullbacky ve směru M5"
        regime = "TREND"
    elif session_atr is not None and session_atr >= 1.8:
        headline = "Denní range rozšířený — sniž lot / čekej novou session"
        regime = "EXTENDED"
    else:
        headline = "Normální režim — kombinuj se Style Guide"
        regime = regime if regime != "—" else "NORMAL"

    return SignalLabSnapshot(headline=headline, regime=regime, signals=signals)
