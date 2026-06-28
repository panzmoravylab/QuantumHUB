import pandas as pd

import pytest

from datetime import datetime

from zoneinfo import ZoneInfo



from config import RISK

from indicators import IndicatorBundle, TrendBias

from layouts.renderers import trend_sparkline_bars

from trend_brief import build_trend_brief, map_strength, _daily_buy_sell_pct

from trading_style import M1Metrics, StyleGuide, TradingStyle





def _style(mtf_direction: str = "BULL", mtf_score: int = 3) -> StyleGuide:

    return StyleGuide(

        style=TradingStyle.MOMENTUM_TREND,

        headline="Momentum",

        primary_action="Trend long",

        bullets=[],

        metrics=M1Metrics(1.2, 5.0, mtf_score, mtf_direction, 0.5, 0.3, "NORMAL"),

    )





def test_map_strength_range():

    assert 1 <= map_strength(4, 1.5, True) <= 10

    assert map_strength(0, 0.8, False) >= 1





def test_daily_buy_sell_pct_bullish():

    rows = []

    for i in range(10):

        rows.append({"open": 100.0, "close": 101.0, "time": pd.Timestamp("2026-06-27 10:00") + pd.Timedelta(hours=i)})

    df = pd.DataFrame(rows)

    tz = ZoneInfo(RISK.timezone)

    now = datetime(2026, 6, 27, 15, 0, tzinfo=tz)



    class FakeMarket:

        h1_rates = df

        m15_rates = pd.DataFrame()



    buy, sell, dom, src, bar_count = _daily_buy_sell_pct(FakeMarket(), now, tz)

    assert buy > sell

    assert dom == "BUY"

    assert src == "od půlnoci CET"

    assert bar_count == 10





def test_build_trend_brief_strength_delta():

    tz = ZoneInfo(RISK.timezone)

    now = datetime(2026, 6, 27, 15, 0, tzinfo=tz)

    history = [(0.0, 2), (60.0, 3), (120.0, 4), (180.0, 4), (240.0, 4), (300.0, 5)]

    brief = build_trend_brief(None, None, _style(), history, now)

    assert brief.strength_now >= 1

    assert brief.daily_buy_pct + brief.daily_sell_pct <= 100.1

    assert brief.daily_source_tf == "od půlnoci CET"





def test_trend_sparkline_bars_caps_at_30():

    values = tuple(range(1, 41))

    bars = trend_sparkline_bars(values)

    assert len(bars.children) == 30

