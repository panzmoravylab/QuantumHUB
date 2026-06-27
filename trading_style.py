"""
M1 XAUUSD trading style engine — translates live data into actionable regime + style.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from config import ACCOUNT, INDICATORS
from indicators import IndicatorBundle, TrendBias
from macro_engine import MacroDaySummary, MacroStatus
from mt5_connector import AccountSnapshot, MarketSnapshot
from risk_engine import Verdict, VerdictStatus


class TradingStyle(str, Enum):
    MOMENTUM_TREND = "MOMENTUM TREND"
    RANGE_SCALP = "RANGE SCALP"
    SQUEEZE_BREAKOUT = "SQUEEZE BREAKOUT"
    WAIT = "WAIT / REDUCE"
    NO_TRADE = "NO TRADE"


@dataclass
class M1Metrics:
    atr_ratio: float
    spread_cost_pct: float
    mtf_score: int
    mtf_direction: str
    pdh_distance_pct: float
    pdl_distance_pct: float
    vol_regime: str


@dataclass
class StyleGuide:
    style: TradingStyle
    headline: str
    primary_action: str
    bullets: list[str]
    metrics: M1Metrics


def _mtf_alignment(mtf: dict[str, TrendBias]) -> tuple[int, str]:
    bulls = sum(1 for b in mtf.values() if b == TrendBias.BULL)
    bears = sum(1 for b in mtf.values() if b == TrendBias.BEAR)
    if bulls >= 3:
        return bulls, "BULL"
    if bears >= 3:
        return bears, "BEAR"
    if bulls > bears:
        return bulls, "MIXED↑"
    if bears > bulls:
        return bears, "MIXED↓"
    return max(bulls, bears), "CHOP"


def _calc_m1_metrics(
    market: MarketSnapshot,
    indicators: IndicatorBundle,
) -> M1Metrics:
    atr_series = indicators.atr_series
    atr_median = float(atr_series.tail(50).median()) if len(atr_series) >= 5 else market.atr
    atr_ratio = market.atr / atr_median if atr_median > 0 else 1.0

    spread_price = market.spread_points * 0.01 if market.spread_points else 0
    spread_cost_pct = (spread_price / market.atr * 100) if market.atr > 0 else 0

    mtf_score, mtf_dir = _mtf_alignment(indicators.mtf_bias)

    bid = market.bid
    pdh_dist = ((indicators.pdh - bid) / bid * 100) if indicators.pdh and bid else 0
    pdl_dist = ((bid - indicators.pdl) / bid * 100) if indicators.pdl and bid else 0

    if atr_ratio >= 1.5 or market.atr_impulse:
        vol_regime = "EXPANSION"
    elif atr_ratio <= 0.7:
        vol_regime = "COMPRESSION"
    else:
        vol_regime = "NORMAL"

    return M1Metrics(
        atr_ratio=round(atr_ratio, 2),
        spread_cost_pct=round(spread_cost_pct, 1),
        mtf_score=mtf_score,
        mtf_direction=mtf_dir,
        pdh_distance_pct=round(pdh_dist, 2),
        pdl_distance_pct=round(pdl_dist, 2),
        vol_regime=vol_regime,
    )


def evaluate_trading_style(
    market: MarketSnapshot | None,
    indicators: IndicatorBundle | None,
    verdict: Verdict,
    macro: MacroDaySummary,
    account: AccountSnapshot | None = None,
) -> StyleGuide:
    if not market or not indicators:
        return StyleGuide(
            style=TradingStyle.WAIT,
            headline="Čekám na data…",
            primary_action="Nech MT5 připojený.",
            bullets=[],
            metrics=M1Metrics(0, 0, 0, "—", 0, 0, "—"),
        )

    metrics = _calc_m1_metrics(market, indicators)

    # Hard blocks
    if macro.status == MacroStatus.BLOCKED or verdict.news_blocked:
        return StyleGuide(
            style=TradingStyle.NO_TRADE,
            headline="Macro zóna — žádné nové vstupy",
            primary_action="Drž se mimo trh do konce macro okna.",
            bullets=[
                macro.headline,
                "Spravuj jen otevřené pozice (SL/TP).",
                "Po release: čekej obrat, ne chase prvního impulsu.",
            ],
            metrics=metrics,
        )

    if verdict.status == VerdictStatus.CRITICAL or (account and account.is_critical):
        return StyleGuide(
            style=TradingStyle.NO_TRADE,
            headline="DD limit — stop trading",
            primary_action="Žádné nové obchody. Dnes končíš.",
            bullets=["Daily drawdown kritický — ForTraders pravidla."],
            metrics=metrics,
        )

    if verdict.spread_blocked or market.spread_warning:
        return StyleGuide(
            style=TradingStyle.WAIT,
            headline="Spread příliš vysoký",
            primary_action="Čekej na normalizaci spreadu před vstupem.",
            bullets=[
                f"Spread {market.spread_points:.0f}p vs medián {market.spread_median:.0f}p.",
                "Vysoký spread = horší R:R na M1 scalpu.",
            ],
            metrics=metrics,
        )

    bullets: list[str] = []
    style = TradingStyle.RANGE_SCALP
    headline = ""
    primary = ""

    if indicators.bb.is_squeeze and metrics.vol_regime == "COMPRESSION":
        style = TradingStyle.SQUEEZE_BREAKOUT
        headline = "BB Squeeze — čeká expanze"
        primary = "Nevstupuj do středu range. Čekej break BB + potvrzení M5."
        bullets = [
            "Squeeze = akumulace. Breakout může být silný ale falešný.",
            "Po breaku: čekej retest nebo M1 close mimo band.",
        ]
    elif metrics.mtf_score >= 3 and metrics.vol_regime != "COMPRESSION":
        direction = metrics.mtf_direction
        style = TradingStyle.MOMENTUM_TREND
        headline = f"Trend alignment {direction} ({metrics.mtf_score}/4 TF)"
        if direction == "BULL":
            primary = "Momentum long — pullback na M1 EMA / bullish FVG, SL pod strukturou."
        elif direction == "BEAR":
            primary = "Momentum short — pullback na M1 EMA / bearish FVG, SL nad strukturou."
        else:
            primary = "Silný bias — obchoduj jen ve směru MTF, ne counter-trend."
        bullets = [
            f"ATR ratio {metrics.atr_ratio:.1f}x — volatilita {metrics.vol_regime.lower()}.",
            f"PDH {metrics.pdh_distance_pct:+.2f}% | PDL {metrics.pdl_distance_pct:+.2f}% od ceny.",
        ]
        corr = indicators.dxy_correlation
        if corr is not None and corr <= INDICATORS.correlation_threshold:
            bullets.append(f"DXY korelace {corr:.2f} — Gold sleduje dolar (potvrzení směru).")
    elif metrics.mtf_direction == "CHOP" or metrics.vol_regime == "COMPRESSION":
        style = TradingStyle.RANGE_SCALP
        headline = "Chop / komprese — range režim"
        primary = "Scalp PDH/PDL a střed range. Malý lot, rychlý TP (1–1.5× ATR)."
        bullets = [
            "Žádné breakout strategie mimo Golden Window.",
            f"Spread/ATR cost {metrics.spread_cost_pct:.0f}% — drž TP krátké.",
        ]
    else:
        style = TradingStyle.RANGE_SCALP
        headline = "Smíšený bias — selektivní vstupy"
        primary = "Obchoduj jen A+ setupy ve směru M5/M15. Jinak čekej."
        bullets = [
            f"MTF: {metrics.mtf_direction} ({metrics.mtf_score}/4 aligned).",
            "Bez 3/4 alignment nechase impulsy.",
        ]

    if market.atr_impulse:
        bullets.insert(0, "ATR impuls aktivní — nechase, čekej 2–3 M1 svíčky ustálení.")
        if style == TradingStyle.MOMENTUM_TREND:
            primary = "Po impulsu: vstup jen na pullback, ne na extrema."

    if not verdict.golden_window_active:
        bullets.append("Mimo Golden Window (14–18 CE(S)T) — sniž aktivitu / lot.")
        if style == TradingStyle.MOMENTUM_TREND:
            style = TradingStyle.WAIT
            headline = "Off-hours — trend risk"
            primary = "Momentum mimo GW = nižší likvidita. Preferuj čekání na GW."

    if macro.status == MacroStatus.CAUTION:
        bullets.append(f"Macro caution: {macro.headline}")

    if metrics.spread_cost_pct > 15:
        bullets.append(f"Spread/ATR {metrics.spread_cost_pct:.0f}% — zvaž menší lot ({ACCOUNT.default_risk_pct * 0.5:.1f}% risk).")

    return StyleGuide(
        style=style,
        headline=headline,
        primary_action=primary,
        bullets=bullets,
        metrics=metrics,
    )
