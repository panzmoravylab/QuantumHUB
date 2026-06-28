import MetaTrader5 as mt5
from datetime import datetime
from zoneinfo import ZoneInfo

from config import RISK
from indicators import BBSqueezeResult, IndicatorBundle, TrendBias
from macro_engine import MacroDaySummary, MacroStatus
from mt5_connector import MarketSnapshot, PositionInfo
from position_manager import (
    ACTION_CLOSE,
    ACTION_HOLD,
    ACTION_WATCH,
    evaluate_positions,
    summarize_position_verdicts,
)
from position_tracker import PositionTrackState, calc_position_r, update_position_tracks
from risk_engine import Verdict, VerdictStatus
import pandas as pd


def _pos(
    ticket: int = 1,
    side: int = mt5.ORDER_TYPE_BUY,
    price_open: float = 2650.0,
    sl: float = 2645.0,
    current: float = 2652.0,
    profit: float = 20.0,
) -> PositionInfo:
    r = calc_position_r(side, price_open, sl, current)
    return PositionInfo(
        ticket=ticket,
        symbol="XAUUSD",
        volume=0.05,
        profit=profit,
        sl=sl,
        tp=0.0,
        price_open=price_open,
        price_current=current,
        type=side,
        rrr=r,
        r_current=r,
        sl_distance_pts=abs(current - sl),
        side="BUY" if side == mt5.ORDER_TYPE_BUY else "SELL",
    )


def _market(atr: float = 4.0) -> MarketSnapshot:
    empty = pd.DataFrame(columns=["time", "open", "high", "low", "close"])
    return MarketSnapshot(
        symbol="XAUUSD",
        bid=2652.0,
        ask=2652.2,
        spread_points=20.0,
        spread_median=18.0,
        spread_warning=False,
        last_m1_bar=None,
        m1_rates=empty,
        m5_rates=empty,
        m15_rates=empty,
        h1_rates=empty,
        dxy_m5_rates=empty,
        atr=atr,
        atr_impulse=False,
        current_candle_range=1.0,
    )


def _indicators(m5: TrendBias = TrendBias.BULL, m15: TrendBias = TrendBias.BULL) -> IndicatorBundle:
    empty = pd.Series(dtype=float)
    bb = BBSqueezeResult(
        upper=empty,
        middle=empty,
        lower=empty,
        bandwidth=empty,
        is_squeeze=False,
        squeeze_threshold=0.0,
    )
    return IndicatorBundle(
        atr=4.0,
        atr_series=pd.Series([4.0]),
        bb=bb,
        mtf_bias={"M1": TrendBias.BULL, "M5": m5, "M15": m15, "H1": TrendBias.BULL},
        pdh=2660.0,
        pdl=2640.0,
        fvg_zones=[],
        dxy_correlation=0.0,
    )


def test_calc_position_r_without_tp():
    r = calc_position_r(mt5.ORDER_TYPE_BUY, 2650.0, 2645.0, 2652.5)
    assert r == 0.5


def test_near_sl_recommends_close():
    pos = _pos(current=2645.3, profit=-50.0)
    verdicts = evaluate_positions(
        [pos],
        {},
        _market(),
        _indicators(m5=TrendBias.BEAR, m15=TrendBias.BEAR),
        None,
        None,
        None,
        None,
    )
    assert verdicts[0].action == ACTION_CLOSE


def test_aligned_pullback_is_watch_or_hold():
    pos = _pos(current=2649.0, profit=-5.0)
    track = PositionTrackState(ticket=1, open_ts=0, mfe_r=0.2, mae_r=-0.2, peak_profit_usd=5, last_r=-0.2)
    verdicts = evaluate_positions(
        [pos],
        {1: track},
        _market(),
        _indicators(),
        None,
        None,
        None,
        None,
    )
    assert verdicts[0].action in (ACTION_WATCH, ACTION_HOLD)


def test_critical_verdict_forces_close():
    pos = _pos(profit=10.0)
    verdict = Verdict(
        status=VerdictStatus.CRITICAL,
        messages=["DD limit"],
        golden_window_active=True,
        news_blocked=False,
        spread_blocked=False,
    )
    verdicts = evaluate_positions([pos], {}, _market(), _indicators(), None, None, verdict, None)
    assert verdicts[0].action == ACTION_CLOSE


def test_tracker_updates_mfe_mae():
    pos = _pos(current=2655.0)
    t1 = update_position_tracks([pos], {})
    pos2 = _pos(current=2648.0)
    t2 = update_position_tracks([pos2], t1)
    assert t2[1].mfe_r >= 1.0
    assert t2[1].mae_r <= 0


def test_summarize_verdicts():
    pos = _pos()
    verdicts = evaluate_positions([pos], {}, _market(), _indicators(), None, None, None, None)
    summary = summarize_position_verdicts(verdicts)
    assert "DRŽET" in summary or "KOREKCE" in summary


def test_buy_aligned_high_trend_pct():
    from dataclasses import replace

    from trend_brief import TrendBrief
    from signal_lab import SignalItem, SignalLabSnapshot
    from trading_style import M1Metrics, StyleGuide, TradingStyle

    brief = TrendBrief(
        daily_dominant="BUY",
        daily_buy_pct=60.0,
        daily_sell_pct=40.0,
        daily_source_tf="M1",
        daily_bar_count=10,
        now_direction="BUY",
        strength_now=9,
        strength_prev=7,
        strength_delta=2,
        strength_source_tf="M1",
        strength_history=(7, 8, 9),
        mtf={},
    )
    lab = SignalLabSnapshot(
        headline="Momentum",
        regime="TREND",
        signals=[
            SignalItem("M5 momentum", "BULL", "", "bull"),
            SignalItem("Efficiency (20)", "0.62", "", "bull"),
        ],
    )
    style = StyleGuide(
        style=TradingStyle.MOMENTUM_TREND,
        headline="Trend",
        primary_action="Long pullbacks",
        bullets=[],
        metrics=M1Metrics(1.2, 5.0, 4, "BULL", 0.5, 0.3, "NORMAL"),
    )
    market = replace(_market(atr=4.0), current_candle_range=3.8, atr_impulse=True)
    pos = _pos()
    verdicts = evaluate_positions(
        [pos], {}, market, _indicators(), lab, style, None, None, trend_brief=brief
    )
    assert verdicts[0].trend_alignment_pct >= 85
    assert verdicts[0].trend_alignment_label == "ULTRA SILNÝ TREND"


def test_buy_mtf_against_low_trend_pct():
    pos = _pos()
    verdicts = evaluate_positions(
        [pos],
        {},
        _market(),
        _indicators(m5=TrendBias.BEAR, m15=TrendBias.BEAR),
        None,
        None,
        None,
        None,
    )
    assert verdicts[0].trend_alignment_pct <= 35
