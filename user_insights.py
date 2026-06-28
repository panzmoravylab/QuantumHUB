"""Uživatelsky srozumitelné výpočty pro HUD — checklist, stav systému, engine panel."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

from config import ACCOUNT, RISK
from compute_log import InsightEntry, ComputeLog
from macro_engine import MacroDaySummary, MacroStatus
from mt5_connector import AccountSnapshot, MarketSnapshot, PositionInfo
from risk_engine import LotSizeResult, NewsEvent, Verdict, VerdictStatus, is_golden_window
from trading_style import StyleGuide, TradingStyle


class CheckStatus(str, Enum):
    OK = "ok"
    WARN = "warn"
    FAIL = "fail"
    NA = "na"


@dataclass(frozen=True)
class CheckItem:
    label: str
    meaning: str
    status: CheckStatus
    hint: str = ""


@dataclass(frozen=True)
class PreNewsChecklist:
    active: bool
    headline: str
    subline: str
    event_title: str
    minutes_until: int | None
    items: tuple[CheckItem, ...]
    ready: bool


@dataclass(frozen=True)
class TradeDecision:
    action: str
    tone: str
    headline: str
    reasons: tuple[str, ...]
    indicator_note: str


@dataclass(frozen=True)
class ScalpPlan:
    gate_action: str
    gate_tone: str
    direction: str
    direction_tone: str
    scalp_hint: str
    spread_pts: float
    spread_vs_median: float
    spread_ok: bool
    atr_m1: float
    lot: float
    risk_usd: float
    risk_pct: float
    sl_points: float
    sl_usd: float
    daily_dd_remaining_usd: float
    daily_dd_remaining_pct: float
    trail_dd_remaining_usd: float
    trades_until_daily_limit: int | None
    golden_window: bool
    next_news_label: str | None
    next_news_minutes: int | None
    pdh_distance_pct: float
    pdl_distance_pct: float
    reasons: tuple[str, ...]
    price_velocity: float = 0.0


@dataclass(frozen=True)
class StatusPill:
    label: str
    value: str
    tone: str
    tooltip: str


@dataclass(frozen=True)
class EnginePanel:
    pills: tuple[StatusPill, ...]
    insights: tuple[InsightEntry, ...]
    footnote: str


PRE_NEWS_SHOW_MINUTES = 90
HIGH_IMPACT = frozenset({"high", "red"})


def _next_high_impact_event(
    events: list[NewsEvent],
    now: datetime,
    tz: ZoneInfo,
    focus_date=None,
) -> NewsEvent | None:
    candidates: list[NewsEvent] = []
    for e in events:
        if e.impact.lower() not in HIGH_IMPACT:
            continue
        if focus_date and e.event_time.astimezone(tz).date() != focus_date:
            continue
        if e.seconds_until < -(RISK.news_buffer_minutes * 60):
            continue
        candidates.append(e)
    if not candidates:
        return None
    return min(candidates, key=lambda x: abs(x.seconds_until))


def build_pre_news_checklist(
    account: AccountSnapshot | None,
    market: MarketSnapshot | None,
    positions: list[PositionInfo],
    verdict: Verdict,
    lot_result: LotSizeResult | None,
    events: list[NewsEvent],
    macro_summary: MacroDaySummary,
    now: datetime | None = None,
) -> PreNewsChecklist:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    focus = macro_summary.focus_date or now.date()
    nxt = _next_high_impact_event(events, now, tz, focus)

    if not nxt:
        return PreNewsChecklist(
            active=False,
            headline="Před-news kontrola",
            subline="Dnes žádná high-impact událost v briefingu — checklist není potřeba.",
            event_title="",
            minutes_until=None,
            items=(),
            ready=True,
        )

    mins = nxt.seconds_until // 60
    in_buffer = abs(nxt.seconds_until) <= RISK.news_buffer_minutes * 60
    show = in_buffer or (0 <= nxt.seconds_until <= PRE_NEWS_SHOW_MINUTES * 60)

    if not show:
        when = nxt.event_time.astimezone(tz).strftime("%H:%M")
        return PreNewsChecklist(
            active=False,
            headline="Před-news kontrola",
            subline=f"Nejbližší riziko: {nxt.title} v {when} — checklist se zapne 90 min předem.",
            event_title=nxt.title,
            minutes_until=mins if mins >= 0 else 0,
            items=(),
            ready=True,
        )

    items: list[CheckItem] = []

    if not account or not account.connected:
        items.append(
            CheckItem(
                "MT5 data",
                "Bez připojení neumím ověřit spread ani pozice.",
                CheckStatus.FAIL,
                "Spusťte MT5 a obnovte HUD.",
            )
        )
    elif market and market.spread_warning:
        items.append(
            CheckItem(
                "Spread",
                "Spread je nad normálem — vstup by byl drahý (slippage).",
                CheckStatus.FAIL,
                f"Aktuálně {market.spread_points:.0f}p · medián {market.spread_median:.0f}p",
            )
        )
    elif market:
        items.append(
            CheckItem(
                "Spread",
                "Náklady vstupu jsou v normě pro XAU.",
                CheckStatus.OK,
                f"{market.spread_points:.0f}p · medián {market.spread_median:.0f}p",
            )
        )

    if positions:
        pl = sum(p.profit for p in positions)
        items.append(
            CheckItem(
                "Expozice",
                "Máte otevřené pozice — před newsem zvažte zmenšení nebo hedge.",
                CheckStatus.WARN,
                f"{len(positions)} poz. · P&L ${pl:+.0f}",
            )
        )
    else:
        items.append(
            CheckItem(
                "Expozice",
                "Nejste v trhu — ideální stav před volatile release.",
                CheckStatus.OK,
                "Flat · 0 pozic",
            )
        )

    if account:
        daily_left = max(0.0, ACCOUNT.daily_drawdown_limit_pct - account.daily_drawdown_pct)
        trail_left = max(0.0, ACCOUNT.trailing_drawdown_limit_pct - account.trailing_drawdown_pct)
        dd_fail = (
            account.daily_drawdown_pct >= ACCOUNT.daily_drawdown_limit_pct * 0.85
            or account.trailing_drawdown_pct >= ACCOUNT.trailing_drawdown_limit_pct * 0.85
        )
        dd_status = CheckStatus.FAIL if dd_fail else CheckStatus.OK
        if dd_fail:
            meaning = "Blízko prop limitu — nový obchod riskuje porušení pravidel."
        else:
            meaning = "Rezerva drawdownu je dostatečná pro plánovaný risk."
        items.append(
            CheckItem(
                "Prop DD",
                meaning,
                dd_status,
                f"Zbývá daily {daily_left:.1f}% · trail {trail_left:.1f}%",
            )
        )

    if lot_result and lot_result.lot_size > 0:
        items.append(
            CheckItem(
                "Velikost lotu",
                "Vypočtený lot odpovídá nastavenému % risku ke SL.",
                CheckStatus.OK,
                lot_result.message,
            )
        )
    elif lot_result:
        items.append(
            CheckItem(
                "Velikost lotu",
                "Lot nejde spočítat — chybí SL nebo data symbolu.",
                CheckStatus.WARN,
                lot_result.message,
            )
        )

    golden = is_golden_window(now)
    items.append(
        CheckItem(
            "Golden Window",
            "14–18h CE(S)T = nejlepší likvidita na Gold.",
            CheckStatus.OK if golden else CheckStatus.WARN,
            "Aktivní" if golden else "Mimo okno — nižší likvidita",
        )
    )

    if verdict.news_blocked or macro_summary.status == MacroStatus.BLOCKED:
        items.append(
            CheckItem(
                "Macro okno",
                "Jste v news bufferu — systém doporučuje neobchodovat.",
                CheckStatus.FAIL,
                f"±{RISK.news_buffer_minutes} min kolem {nxt.title}",
            )
        )
    else:
        items.append(
            CheckItem(
                "Macro okno",
                "Mimo kritické okno kolem dat — ale buďte připraveni.",
                CheckStatus.OK,
                f"Buffer ±{RISK.news_buffer_minutes} min",
            )
        )

    fails = sum(1 for i in items if i.status == CheckStatus.FAIL)
    warns = sum(1 for i in items if i.status == CheckStatus.WARN)
    ready = fails == 0

    if in_buffer:
        headline = f"⚠ Před / během news · {nxt.title}"
    else:
        headline = f"Příprava na news · {nxt.title}"

    if mins >= 0:
        subline = f"Za {mins} min ({nxt.event_time.astimezone(tz).strftime('%H:%M')} CE(S)T) · "
    else:
        subline = f"Probíhá buffer kolem {nxt.event_time.astimezone(tz).strftime('%H:%M')} · "

    if ready and warns == 0:
        subline += "všechny kontroly OK — stále buďte opatrní u high-impact."
    elif fails:
        subline += f"{fails}× STOP — neobchodovat dokud nevyřešíte."
    else:
        subline += f"{warns}× pozor — zkontrolujte před vstupem."

    return PreNewsChecklist(
        active=True,
        headline=headline,
        subline=subline,
        event_title=nxt.title,
        minutes_until=mins,
        items=tuple(items),
        ready=ready,
    )


def build_trade_decision(
    account: AccountSnapshot | None,
    market: MarketSnapshot | None,
    verdict: Verdict,
    style_guide: StyleGuide | None,
    macro_summary: MacroDaySummary,
    signal_lab,
    connected: bool,
    now: datetime | None = None,
    price_velocity: float = 0.0,
) -> TradeDecision:
    """Jediná otázka: otevřít obchod TEĎ? Doplňuje mezery MT5 indikátoru."""
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    blockers: list[str] = []
    cautions: list[str] = []

    if not connected or not account or not account.connected:
        return TradeDecision(
            action="NE",
            tone="stop",
            headline="Bez MT5 dat",
            reasons=("Připojte MetaTrader 5 — bez live dat nejde rozhodnout.",),
            indicator_note="Indikátor v MT5 běží, ale HUD nevidí spread ani DD.",
        )

    if verdict.status == VerdictStatus.CRITICAL or account.is_critical:
        blockers.append(
            f"Prop DD kritické — daily {account.daily_drawdown_pct:.1f}% / "
            f"trail {account.trailing_drawdown_pct:.1f}%"
        )
    if verdict.news_blocked or macro_summary.status == MacroStatus.BLOCKED:
        blockers.append(f"Macro news buffer ±{RISK.news_buffer_minutes} min — riziko skluzu")
    if verdict.spread_blocked or (market and market.spread_warning):
        spr = f"{market.spread_points:.0f}p" if market else "?"
        blockers.append(f"Spread {spr} nad normálem — drahý vstup")
    if style_guide and style_guide.style == TradingStyle.NO_TRADE:
        blockers.append(style_guide.primary_action or "Režim NO TRADE")
    if verdict.status == VerdictStatus.BLOCKED and not blockers:
        blockers.append("Verdict BLOCKED — podmínky pro vstup nejsou splněny")

    if abs(price_velocity) > 120.0:
        cautions.append("Rozjetý vlak — extrémní rychlost ceny")
    if not is_golden_window(now):
        cautions.append("Mimo Golden Window 14–18h CE(S)T — nižší likvidita")
    if market and market.atr_impulse:
        cautions.append("ATR impulse — cena skáče, počkejte na ustálení")
    if macro_summary.status == MacroStatus.CAUTION:
        cautions.append("Macro CAUTION — zvýšená volatilita kolem dat")
    if style_guide and style_guide.style == TradingStyle.WAIT:
        cautions.append(style_guide.headline or "Režim WAIT — bez clear edge")
    if verdict.status == VerdictStatus.CAUTION and not blockers:
        cautions.append("Verdict CAUTION — obchodujte menší size nebo čekejte")
    if signal_lab and signal_lab.regime and "CHOP" in signal_lab.regime.upper():
        cautions.append(f"Signal Lab: {signal_lab.regime} — slabý směr")

    note_ok = "Indikátor může dát vstup — HUD nevidí žádný blok (spread · macro · prop)."
    note_stop = "Indikátor může dávat signál — HUD říká NE kvůli rizikům, které indikátor neřeší."
    note_wait = "Indikátor má mezery — HUD vidí okolní rizika, raději počkejte na lepší okno."

    if blockers:
        return TradeDecision(
            action="NE",
            tone="stop",
            headline="Neotevírat",
            reasons=tuple(blockers[:4]),
            indicator_note=note_stop,
        )

    if cautions:
        return TradeDecision(
            action="POČKEJ",
            tone="wait",
            headline="Raději počkat",
            reasons=tuple(cautions[:4]),
            indicator_note=note_wait,
        )

    supports: list[str] = []
    if is_golden_window(now):
        supports.append("Golden Window aktivní — nejlepší likvidita")
    if market:
        supports.append(f"Spread {market.spread_points:.0f}p OK · ATR {market.atr:.2f}")
    if style_guide:
        supports.append(f"{style_guide.style.value} · {style_guide.primary_action}")
    if not supports:
        supports.append("Podmínky pro vstup splněny")

    return TradeDecision(
        action="ANO",
        tone="go",
        headline="Okno otevřené",
        reasons=tuple(supports[:3]),
        indicator_note=note_ok,
    )


def _resolve_scalp_direction(
    style_guide: StyleGuide | None,
    gate_action: str,
    indicators=None,
    signal_lab=None,
    trend_brief=None,
) -> tuple[str, str]:
    # Determine the underlying market direction bias based on all displayed info:
    # 1. MTF trend (from style guide)
    # 2. SMT Divergence (from indicators)
    # 3. Signal Lab (regime and direction)
    # 4. Trend Briefing (daily bias and buy/sell strength)
    
    score = 0
    
    # 1. MTF Trend Bias
    if style_guide and style_guide.metrics:
        mtf_dir = style_guide.metrics.mtf_direction
        if mtf_dir == "BULL":
            score += 3
        elif mtf_dir == "MIXED↑":
            score += 1
        elif mtf_dir == "BEAR":
            score -= 3
        elif mtf_dir == "MIXED↓":
            score -= 1

    # 2. SMT Divergence
    if indicators and hasattr(indicators, "dxy_smt_divergence") and indicators.dxy_smt_divergence:
        if indicators.dxy_smt_divergence == "BULLISH_SMT":
            score += 2
        elif indicators.dxy_smt_divergence == "BEARISH_SMT":
            score -= 2

    # 3. Signal Lab
    if signal_lab and hasattr(signal_lab, "direction") and signal_lab.direction:
        if signal_lab.direction == "LONG":
            score += 2
        elif signal_lab.direction == "SHORT":
            score -= 2

    # 4. Trend Briefing Bias
    if trend_brief:
        daily_bias = getattr(trend_brief, "daily_bias", None)
        bias_str = str(daily_bias.value if hasattr(daily_bias, "value") else daily_bias).upper()
        if "BULL" in bias_str:
            score += 1
        elif "BEAR" in bias_str:
            score -= 1
        else:
            buy_pct = getattr(trend_brief, "daily_buy_pct", 50.0) or 50.0
            sell_pct = getattr(trend_brief, "daily_sell_pct", 50.0) or 50.0
            if buy_pct > sell_pct:
                score += 1
            elif sell_pct > buy_pct:
                score -= 1

    # Evaluate final direction from the score
    if score >= 2:
        direction = "LONG"
        direction_tone = "long"
    elif score <= -2:
        direction = "SHORT"
        direction_tone = "short"
    else:
        direction = "NEUTRAL"
        direction_tone = "neutral"

    return direction, direction_tone


def build_scalp_plan(
    account: AccountSnapshot | None,
    market: MarketSnapshot | None,
    verdict: Verdict,
    style_guide: StyleGuide | None,
    macro_summary: MacroDaySummary,
    lot_result: LotSizeResult | None,
    events: list[NewsEvent],
    signal_lab,
    connected: bool,
    now: datetime | None = None,
    indicators=None,
    trend_brief=None,
    price_velocity: float = 0.0,
) -> ScalpPlan:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    decision = build_trade_decision(
        account,
        market,
        verdict,
        style_guide,
        macro_summary,
        signal_lab,
        connected,
        now,
        price_velocity=price_velocity,
    )

    spread_pts = market.spread_points if market else 0.0
    spread_median = market.spread_median if market and market.spread_median > 0 else 1.0
    spread_vs = spread_pts / spread_median if spread_median > 0 else 1.0
    spread_ok = not (market and market.spread_warning) and not verdict.spread_blocked

    daily_limit_usd = ACCOUNT.starting_balance * ACCOUNT.daily_drawdown_limit_pct / 100
    trail_limit_usd = ACCOUNT.starting_balance * ACCOUNT.trailing_drawdown_limit_pct / 100
    daily_dd_usd = account.daily_drawdown_usd if account else 0.0
    trail_dd_usd = account.trailing_drawdown_usd if account else 0.0
    daily_remaining_usd = max(0.0, daily_limit_usd - daily_dd_usd)
    trail_remaining_usd = max(0.0, trail_limit_usd - trail_dd_usd)
    daily_remaining_pct = max(
        0.0,
        ACCOUNT.daily_drawdown_limit_pct - (account.daily_drawdown_pct if account else 0.0),
    )

    risk_usd = lot_result.risk_usd if lot_result else 0.0
    risk_pct = lot_result.risk_pct if lot_result else ACCOUNT.default_risk_pct
    lot = lot_result.lot_size if lot_result else 0.0
    sl_points = lot_result.sl_points if lot_result else 0.0
    sl_usd = risk_usd

    trades_left: int | None = None
    if risk_usd > 0:
        trades_left = max(0, int(math.floor(daily_remaining_usd / risk_usd)))

    direction, direction_tone = _resolve_scalp_direction(
        style_guide, decision.action, indicators, signal_lab, trend_brief
    )

    if style_guide and style_guide.primary_action:
        scalp_hint = style_guide.primary_action
    elif style_guide and style_guide.headline:
        scalp_hint = style_guide.headline
    else:
        scalp_hint = decision.headline

    if len(scalp_hint) > 90:
        scalp_hint = scalp_hint[:87] + "…"

    focus = macro_summary.focus_date or now.date()
    nxt = _next_high_impact_event(events, now, tz, focus)
    news_label: str | None = None
    news_minutes: int | None = None
    if nxt:
        mins = nxt.seconds_until // 60
        in_prep_window = 0 <= nxt.seconds_until <= PRE_NEWS_SHOW_MINUTES * 60
        in_buffer = abs(nxt.seconds_until) <= RISK.news_buffer_minutes * 60
        if in_prep_window or in_buffer:
            news_label = nxt.title
            news_minutes = mins

    pdh_dist = style_guide.metrics.pdh_distance_pct if style_guide else 0.0
    pdl_dist = style_guide.metrics.pdl_distance_pct if style_guide else 0.0

    return ScalpPlan(
        gate_action=decision.action,
        gate_tone=decision.tone,
        direction=direction,
        direction_tone=direction_tone,
        scalp_hint=scalp_hint,
        spread_pts=spread_pts,
        spread_vs_median=round(spread_vs, 2),
        spread_ok=spread_ok,
        atr_m1=market.atr if market else 0.0,
        lot=lot,
        risk_usd=risk_usd,
        risk_pct=risk_pct,
        sl_points=sl_points,
        sl_usd=sl_usd,
        daily_dd_remaining_usd=daily_remaining_usd,
        daily_dd_remaining_pct=daily_remaining_pct,
        trail_dd_remaining_usd=trail_remaining_usd,
        trades_until_daily_limit=trades_left,
        golden_window=is_golden_window(now),
        next_news_label=news_label,
        next_news_minutes=news_minutes,
        pdh_distance_pct=pdh_dist,
        pdl_distance_pct=pdl_dist,
        reasons=decision.reasons[:2],
        price_velocity=price_velocity,
    )


def build_engine_panel(
    account: AccountSnapshot | None,
    market: MarketSnapshot | None,
    verdict: Verdict,
    macro_summary: MacroDaySummary,
    signal_lab,
    compute_log: ComputeLog | None,
    connected: bool,
) -> EnginePanel:
    pills: list[StatusPill] = []

    if connected and account and account.connected:
        pills.append(
            StatusPill(
                "MT5",
                "Připojeno",
                "ok",
                f"Equity ${account.equity:,.0f} · účet live",
            )
        )
    else:
        pills.append(
            StatusPill(
                "MT5",
                "Offline",
                "err",
                "Spusťte MetaTrader 5 — bez něj chybí ceny a pozice.",
            )
        )

    if market and market.spread_warning:
        pills.append(
            StatusPill(
                "Spread",
                "Vysoký",
                "warn",
                f"{market.spread_points:.0f} bodů — vstup dražší než obvykle.",
            )
        )
    elif market:
        pills.append(
            StatusPill(
                "Spread",
                "Normální",
                "ok",
                f"{market.spread_points:.0f}p · medián {market.spread_median:.0f}p",
            )
        )
    else:
        pills.append(StatusPill("Spread", "—", "na", "Čekám na tick data."))

    if macro_summary.status == MacroStatus.BLOCKED:
        pills.append(StatusPill("Macro", "Blok", "err", macro_summary.headline))
    elif macro_summary.status == MacroStatus.CAUTION:
        pills.append(StatusPill("Macro", "Pozor", "warn", macro_summary.headline))
    else:
        pills.append(
            StatusPill(
                "Macro",
                "Klid",
                "ok",
                macro_summary.headline or "Bez high-impact v briefingu.",
            )
        )

    if account:
        worst = max(
            account.daily_drawdown_pct / ACCOUNT.daily_drawdown_limit_pct
            if ACCOUNT.daily_drawdown_limit_pct
            else 0,
            account.trailing_drawdown_pct / ACCOUNT.trailing_drawdown_limit_pct
            if ACCOUNT.trailing_drawdown_limit_pct
            else 0,
        )
        if worst >= 0.85:
            tone, val = "err", "Kritické"
            tip = "Blízko prop limitu — zastavte obchodování."
        elif worst >= 0.5:
            tone, val = "warn", "Pozor"
            tip = f"Daily {account.daily_drawdown_pct:.1f}% · Trail {account.trailing_drawdown_pct:.1f}%"
        else:
            tone, val = "ok", "V bezpečí"
            tip = f"Rezerva daily {ACCOUNT.daily_drawdown_limit_pct - account.daily_drawdown_pct:.1f}%"
        pills.append(StatusPill("Prop DD", val, tone, tip))
    else:
        pills.append(StatusPill("Prop DD", "—", "na", "DD se počítá z MT5 equity."))

    insights: list[InsightEntry] = []
    if compute_log:
        insights = [i for i in compute_log.read_insights() if i.category != "tick"][-6:]

    footnote = (
        "Pills = okamžitý stav · níže poslední změny z Python engine "
        "(ne technický log)."
    )
    return EnginePanel(pills=tuple(pills), insights=tuple(insights[-6:]), footnote=footnote)
