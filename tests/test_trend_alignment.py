from indicators import TrendBias
from position_manager import (
    ACTION_HOLD,
    ACTION_WATCH,
    _calc_trend_alignment,
)
from tests.test_position_manager import _indicators, _market, _pos
from trend_brief import TrendBrief


def test_trend_pct_ultra_strong_when_all_signals_align():
    brief = TrendBrief(
        daily_dominant="BUY",
        daily_buy_pct=70.0,
        daily_sell_pct=30.0,
        daily_source_tf="M1",
        daily_bar_count=12,
        now_direction="BUY",
        strength_now=9,
        strength_prev=8,
        strength_delta=1,
        strength_source_tf="M1",
        strength_history=(8, 9),
        mtf={},
    )
    pct, label = _calc_trend_alignment(
        "BUY",
        True,
        "LONG",
        brief,
        0.8,
        None,
        ACTION_HOLD,
        _market(),
        _indicators(),
        None,
        None,
        None,
    )
    assert pct >= 70
    assert label in ("SILNÝ TREND", "ULTRA SILNÝ TREND")


def test_trend_pct_ultra_requires_full_alignment():
    from dataclasses import replace

    from signal_lab import SignalItem, SignalLabSnapshot
    from trading_style import M1Metrics, StyleGuide, TradingStyle

    brief = TrendBrief(
        daily_dominant="BUY",
        daily_buy_pct=70.0,
        daily_sell_pct=30.0,
        daily_source_tf="M1",
        daily_bar_count=12,
        now_direction="BUY",
        strength_now=10,
        strength_prev=9,
        strength_delta=1,
        strength_source_tf="M1",
        strength_history=(9, 10),
        mtf={},
    )
    lab = SignalLabSnapshot(
        headline="Trend",
        regime="TREND",
        signals=[SignalItem("M5 momentum", "BULL", "", "bull")],
    )
    style = StyleGuide(
        style=TradingStyle.MOMENTUM_TREND,
        headline="Trend",
        primary_action="Long",
        bullets=[],
        metrics=M1Metrics(1.2, 5.0, 4, "BULL", 0.5, 0.3, "NORMAL"),
    )
    market = replace(_market(), current_candle_range=3.5, atr_impulse=True)
    pct, label = _calc_trend_alignment(
        "BUY",
        True,
        "LONG",
        brief,
        1.2,
        None,
        ACTION_HOLD,
        market,
        _indicators(),
        lab,
        style,
        None,
    )
    assert pct >= 85
    assert label == "ULTRA SILNÝ TREND"


def test_trend_pct_weak_when_mtf_against():
    pct, label = _calc_trend_alignment(
        "BUY",
        False,
        "SHORT",
        None,
        -0.2,
        None,
        ACTION_WATCH,
        _market(),
        _indicators(m5=TrendBias.BEAR, m15=TrendBias.BEAR),
        None,
        None,
        None,
    )
    assert pct <= 35
    assert label in ("KOREKCE — SLABÁ PODPORA", "TRH PROTI POZICI")
