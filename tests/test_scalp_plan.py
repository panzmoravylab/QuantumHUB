import pandas as pd
import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from config import ACCOUNT, RISK
from macro_engine import MacroDaySummary, MacroStatus
from mt5_connector import AccountSnapshot, MarketSnapshot
from risk_engine import LotSizeResult, Verdict, VerdictStatus
from trading_style import M1Metrics, StyleGuide, TradingStyle
from user_insights import build_scalp_plan

_EMPTY_DF = pd.DataFrame()


def _account(**kwargs) -> AccountSnapshot:
    defaults = dict(
        login=1,
        company="Test",
        balance=25_000,
        equity=25_000,
        margin=0,
        free_margin=25_000,
        daily_start_balance=25_000,
        daily_drawdown_usd=0,
        daily_drawdown_pct=0,
        trailing_max_equity=25_000,
        trailing_drawdown_usd=0,
        trailing_drawdown_pct=0,
        is_critical=False,
        connected=True,
    )
    defaults.update(kwargs)
    return AccountSnapshot(**defaults)


def _market(**kwargs) -> MarketSnapshot:
    defaults = dict(
        symbol="XAUUSD",
        bid=2650.0,
        ask=2650.25,
        spread_points=25,
        spread_median=20,
        spread_warning=False,
        last_m1_bar=None,
        m1_rates=_EMPTY_DF,
        m5_rates=_EMPTY_DF,
        m15_rates=_EMPTY_DF,
        h1_rates=_EMPTY_DF,
        dxy_m5_rates=_EMPTY_DF,
        atr=3.0,
        atr_impulse=False,
        current_candle_range=1.0,
    )
    defaults.update(kwargs)
    return MarketSnapshot(**defaults)


def _style(mtf_direction: str = "BULL") -> StyleGuide:
    return StyleGuide(
        style=TradingStyle.MOMENTUM_TREND,
        headline="Momentum",
        primary_action="Trend long na M1 pullbackech",
        bullets=[],
        metrics=M1Metrics(1.0, 5.0, 3, mtf_direction, 0.5, 0.3, "NORMAL"),
    )


def _macro_clear() -> MacroDaySummary:
    return MacroDaySummary(
        status=MacroStatus.CLEAR,
        headline="Klidný den",
        caution_from=None,
        caution_until=None,
        active_now=False,
        recommendations=[],
        event_count=0,
        focus_date=None,
    )


def _lot() -> LotSizeResult:
    return LotSizeResult(
        risk_pct=1.0,
        risk_usd=250.0,
        sl_points=450,
        lot_size=0.12,
        message="0.12 lot @ 1% risk",
    )


def test_scalp_plan_spread_block():
    now = datetime(2026, 6, 27, 15, 0, tzinfo=ZoneInfo(RISK.timezone))
    market = _market(spread_warning=True, spread_points=40)
    verdict = Verdict(
        status=VerdictStatus.BLOCKED,
        messages=["Spread high"],
        golden_window_active=True,
        news_blocked=False,
        spread_blocked=True,
    )
    plan = build_scalp_plan(
        _account(),
        market,
        verdict,
        _style(),
        _macro_clear(),
        _lot(),
        [],
        None,
        True,
        now,
    )
    assert plan.gate_action == "NE"
    assert plan.spread_ok is False
    assert plan.direction == "LONG"


def test_scalp_plan_direction_long():
    now = datetime(2026, 6, 27, 15, 0, tzinfo=ZoneInfo(RISK.timezone))
    verdict = Verdict(
        status=VerdictStatus.CLEAR,
        messages=[],
        golden_window_active=True,
        news_blocked=False,
        spread_blocked=False,
    )
    plan = build_scalp_plan(
        _account(),
        _market(),
        verdict,
        _style("BULL"),
        _macro_clear(),
        _lot(),
        [],
        None,
        True,
        now,
    )
    assert plan.gate_action == "ANO"
    assert plan.direction == "LONG"
    assert plan.spread_ok is True


def test_scalp_plan_dd_budget_trades():
    now = datetime(2026, 6, 27, 15, 0, tzinfo=ZoneInfo(RISK.timezone))
    daily_limit = ACCOUNT.starting_balance * ACCOUNT.daily_drawdown_limit_pct / 100
    used = daily_limit / 2
    account = _account(
        daily_drawdown_usd=used,
        daily_drawdown_pct=ACCOUNT.daily_drawdown_limit_pct / 2,
    )
    verdict = Verdict(
        status=VerdictStatus.CLEAR,
        messages=[],
        golden_window_active=True,
        news_blocked=False,
        spread_blocked=False,
    )
    plan = build_scalp_plan(
        account,
        _market(),
        verdict,
        _style(),
        _macro_clear(),
        _lot(),
        [],
        None,
        True,
        now,
    )
    assert plan.daily_dd_remaining_usd == pytest.approx(daily_limit - used)
    expected_trades = int((daily_limit - used) // 250.0)
    assert plan.trades_until_daily_limit == expected_trades


def test_scalp_plan_extreme_velocity_caution():
    now = datetime(2026, 6, 27, 15, 0, tzinfo=ZoneInfo(RISK.timezone))
    verdict = Verdict(
        status=VerdictStatus.CLEAR,
        messages=[],
        golden_window_active=True,
        news_blocked=False,
        spread_blocked=False,
    )
    # Test with extreme velocity (150.0) -> should trigger "Rozjetý vlak" caution and force POČKEJ (wait)
    plan = build_scalp_plan(
        _account(),
        _market(),
        verdict,
        _style(),
        _macro_clear(),
        _lot(),
        [],
        None,
        True,
        now,
        price_velocity=150.0
    )
    assert plan.gate_action == "POČKEJ"
    assert any("Rozjetý vlak" in r for r in plan.reasons)

