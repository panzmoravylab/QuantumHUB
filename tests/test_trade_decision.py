import pandas as pd
from dash import html

from layouts.renderers import (
    render_header_account_chip,
    render_header_status_pills,
    render_trade_decision_hero,
    resolve_decision_state,
)
from macro_engine import MacroDaySummary, MacroStatus
from mt5_connector import AccountSnapshot, MarketSnapshot
from risk_engine import Verdict, VerdictStatus
from user_insights import ScalpPlan

_EMPTY_DF = pd.DataFrame()


def _plan(gate: str, direction: str = "NEUTRAL", reasons: tuple[str, ...] = ()) -> ScalpPlan:
    return ScalpPlan(
        gate_action=gate,
        gate_tone="go",
        direction=direction,
        direction_tone="long" if direction == "LONG" else "short",
        scalp_hint="",
        spread_pts=10.0,
        spread_vs_median=1.0,
        spread_ok=True,
        atr_m1=1.0,
        lot=0.12,
        risk_usd=250.0,
        risk_pct=1.0,
        sl_points=15.0,
        sl_usd=250.0,
        daily_dd_remaining_usd=500.0,
        daily_dd_remaining_pct=2.0,
        trail_dd_remaining_usd=1000.0,
        trades_until_daily_limit=3,
        golden_window=True,
        next_news_label=None,
        next_news_minutes=None,
        pdh_distance_pct=0.1,
        pdl_distance_pct=0.1,
        reasons=reasons,
    )


def test_resolve_buy_on_ano_long():
    state, tone = resolve_decision_state(_plan("ANO", "LONG"))
    assert state == "BUY"
    assert tone == "long"


def test_resolve_sell_on_ano_short():
    state, tone = resolve_decision_state(_plan("ANO", "SHORT"))
    assert state == "SELL"
    assert tone == "short"


def test_resolve_wait_on_pockej():
    state, tone = resolve_decision_state(_plan("POČKEJ"))
    assert state == "WAIT"
    assert tone == "wait"


def test_resolve_hold_on_ne():
    state, tone = resolve_decision_state(_plan("NE"))
    assert state == "HOLD"
    assert tone == "muted"


def test_decision_hero_includes_gate_reason():
    plan = _plan("POČKEJ", reasons=("Spread nad limitem",))
    hero = render_trade_decision_hero(None, plan, None, None, None)
    assert isinstance(hero, html.Div)
    html_str = str(hero)
    assert "dh-gate-reason" in html_str
    assert "Spread nad limitem" in html_str


def test_header_account_chip_shows_equity_and_dd():
    account = AccountSnapshot(
        login=1,
        company="Test",
        balance=100_000.0,
        equity=105_000.0,
        margin=0.0,
        free_margin=105_000.0,
        daily_start_balance=100_000.0,
        daily_drawdown_usd=500.0,
        daily_drawdown_pct=1.2,
        trailing_max_equity=105_000.0,
        trailing_drawdown_usd=0.0,
        trailing_drawdown_pct=0.5,
        is_critical=False,
        connected=True,
    )
    chip = render_header_account_chip(account)
    assert "105,000" in chip
    assert "1.2%" in chip


def test_header_status_pills_include_gate_and_mt5():
    account = AccountSnapshot(
        login=1,
        company="Test",
        balance=100_000.0,
        equity=100_000.0,
        margin=0.0,
        free_margin=100_000.0,
        daily_start_balance=100_000.0,
        daily_drawdown_usd=0.0,
        daily_drawdown_pct=0.0,
        trailing_max_equity=100_000.0,
        trailing_drawdown_usd=0.0,
        trailing_drawdown_pct=0.0,
        is_critical=False,
        connected=True,
    )
    market = MarketSnapshot(
        symbol="XAUUSD",
        bid=2650.0,
        ask=2650.18,
        spread_points=18.0,
        spread_median=15.0,
        spread_warning=False,
        last_m1_bar=None,
        m1_rates=_EMPTY_DF,
        m5_rates=_EMPTY_DF,
        m15_rates=_EMPTY_DF,
        h1_rates=_EMPTY_DF,
        dxy_m5_rates=_EMPTY_DF,
        atr=2.5,
        atr_impulse=False,
        current_candle_range=1.0,
    )
    macro = MacroDaySummary(
        status=MacroStatus.CLEAR,
        headline="Volno",
        caution_from=None,
        caution_until=None,
        active_now=False,
        recommendations=[],
        event_count=0,
    )
    verdict = Verdict(
        status=VerdictStatus.CLEAR,
        messages=["OK"],
        golden_window_active=True,
        news_blocked=False,
        spread_blocked=False,
    )
    plan = _plan("ANO", "LONG")
    pills = render_header_status_pills(account, market, macro, verdict, plan, connected=True)
    html_str = str(pills)
    assert "MT5 OK" in html_str
    assert "ANO" in html_str
    assert "GW" in html_str
