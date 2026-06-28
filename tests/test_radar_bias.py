import pandas as pd

from layouts.renderers import (
    _compute_liquidity_balance,
    _effective_market_bias,
    _resolve_radar_display,
)
from signal_lab import SignalItem, SignalLabSnapshot
from user_insights import ScalpPlan


def _lab(direction_signals: list[SignalItem]) -> SignalLabSnapshot:
    return SignalLabSnapshot(
        headline="Test",
        regime="TREND",
        signals=direction_signals,
    )


def _plan(direction: str = "NEUTRAL", gate: str = "POČKEJ") -> ScalpPlan:
    return ScalpPlan(
        gate_action=gate,
        gate_tone="wait",
        direction=direction,
        direction_tone="long",
        scalp_hint="",
        spread_pts=10.0,
        spread_vs_median=1.0,
        spread_ok=True,
        atr_m1=1.0,
        lot=0.0,
        risk_usd=0.0,
        risk_pct=1.0,
        sl_points=15.0,
        sl_usd=0.0,
        daily_dd_remaining_usd=500.0,
        daily_dd_remaining_pct=2.0,
        trail_dd_remaining_usd=1000.0,
        trades_until_daily_limit=3,
        golden_window=True,
        next_news_label=None,
        next_news_minutes=None,
        pdh_distance_pct=0.1,
        pdl_distance_pct=0.1,
        reasons=("Spread nad limitem",),
        price_velocity=0.0,
    )


def test_effective_bias_prefers_signal_lab_over_neutral_plan():
    lab = _lab([
        SignalItem("M5 momentum", "BULL", "", "bull"),
        SignalItem("Spread", "12p", "", "bull"),
    ])
    direction, tone, is_gated = _effective_market_bias(_plan("NEUTRAL", "POČKEJ"), lab, None)
    assert direction == "LONG"
    assert tone == "bull"
    assert is_gated is True


def test_radar_display_long_lab_neutral_plan_shows_buy_not_wait():
    lab = _lab([SignalItem("M5 momentum", "BULL", "", "bull")])
    state, _tone, ring_class, is_gated = _resolve_radar_display(_plan("NEUTRAL", "POČKEJ"), lab, None)
    assert state == "BUY"
    assert ring_class == "bull-gated"
    assert is_gated is True


def test_liquidity_balance_long_bias_adds_offset():
    val = _compute_liquidity_balance(None, None, "IN RANGE", "LONG")
    assert val == 15.0
