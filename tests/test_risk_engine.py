import pytest
from datetime import datetime
from zoneinfo import ZoneInfo

from config import ACCOUNT
from prop_rules import PropState, compute_drawdowns, update_baselines
from risk_engine import calc_lot_size, evaluate_verdict, VerdictStatus


def test_calc_lot_size_below_min_returns_zero():
    result = calc_lot_size(
        equity=1000,
        sl_distance_price=50.0,
        tick_value=1.0,
        tick_size=0.01,
        min_lot=0.01,
        lot_step=0.01,
    )
    assert result.lot_size == 0
    assert "minimem" in result.message.lower()


def test_calc_lot_size_rounds_down():
    result = calc_lot_size(
        equity=100_000,
        sl_distance_price=5.0,
        tick_value=1.0,
        tick_size=0.01,
        min_lot=0.01,
        lot_step=0.01,
        risk_pct=1.0,
    )
    assert result.lot_size >= 0.01
    assert result.lot_size == round(result.lot_size, 2)


def test_prop_rules_daily_reset():
    tz = ZoneInfo("Europe/Prague")
    state = PropState(
        daily_date="2000-01-01",
        daily_start_equity=100_000,
        trailing_max_equity=100_000,
    )
    now = datetime(2026, 6, 27, 10, 0, tzinfo=tz)
    updated = update_baselines(state, 99_000, now)
    assert updated.daily_date == "2026-06-27"
    assert updated.daily_start_equity == 99_000


def test_compute_drawdowns_critical():
    state = PropState(
        daily_date="2026-06-27",
        daily_start_equity=100_000,
        trailing_max_equity=100_000,
    )
    limit = ACCOUNT.daily_drawdown_limit_pct
    equity = 100_000 * (1 - (limit + 0.5) / 100)
    dd = compute_drawdowns(equity, state)
    assert dd.is_critical


def test_verdict_offline_blocked():
    v = evaluate_verdict(None, None, [], datetime.now(ZoneInfo("Europe/Prague")))
    assert v.status == VerdictStatus.BLOCKED
