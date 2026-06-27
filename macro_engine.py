"""
Macro event impact analysis for XAUUSD M1 trading.
Evaluates individual events and aggregates daily macro risk.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from config import MACRO, RISK
from risk_engine import NewsEvent


class MacroStatus(str, Enum):
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    BLOCKED = "BLOCKED"


@dataclass
class EventImpact:
    category: str
    gold_effect: str
    action: str
    trader_note: str


@dataclass
class EnrichedNewsEvent:
    event: NewsEvent
    impact: EventImpact
    local_time: str


@dataclass
class MacroDaySummary:
    status: MacroStatus
    headline: str
    caution_from: datetime | None
    caution_until: datetime | None
    active_now: bool
    recommendations: list[str]
    event_count: int
    focus_date: date | None = None
    focus_label: str = ""


_CZ_WEEKDAYS = (
    "Pondělí",
    "Úterý",
    "Středa",
    "Čtvrtek",
    "Pátek",
    "Sobota",
    "Neděle",
)


def _event_local_date(event: NewsEvent, tz: ZoneInfo) -> date:
    return event.event_time.astimezone(tz).date()


def _next_trading_day(d: date) -> date:
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def _format_focus_label(d: date) -> str:
    return f"{_CZ_WEEKDAYS[d.weekday()]} {d.day}.{d.month}."


def _events_on_date(events: list[NewsEvent], day: date, tz: ZoneInfo) -> list[NewsEvent]:
    return [e for e in events if _event_local_date(e, tz) == day]


def events_on_date(events: list[NewsEvent], day: date, tz: ZoneInfo | None = None) -> list[NewsEvent]:
    tz = tz or ZoneInfo(RISK.timezone)
    return _events_on_date(events, day, tz)


def _day_macro_window_end(events: list[NewsEvent], now: datetime, tz: ZoneInfo) -> datetime | None:
    if not events:
        return None
    buffer = timedelta(minutes=RISK.news_buffer_minutes)
    relevant = [e for e in events if e.impact.lower() in ("high", "red", "medium")]
    if not relevant:
        relevant = events
    return max(e.event_time + buffer for e in relevant).astimezone(tz)


def resolve_macro_focus_date(events: list[NewsEvent], now: datetime | None = None) -> date:
    """Jeden briefing den — po vypršení dnešního okna skok na další obchodní den (Pá→Po)."""
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    if now.tzinfo is None:
        now = now.replace(tzinfo=tz)
    else:
        now = now.astimezone(tz)

    today = now.date()
    if not events:
        nxt = today if today.weekday() < 5 else _next_trading_day(today)
        return nxt

    today_events = _events_on_date(events, today, tz)
    if today_events:
        window_end = _day_macro_window_end(today_events, now, tz)
        has_upcoming_today = any(e.seconds_until > 0 for e in today_events)
        if has_upcoming_today or (window_end and now <= window_end):
            return today

    return _next_trading_day(today)


def analyze_macro_focus(events: list[NewsEvent], now: datetime | None = None) -> MacroDaySummary:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    focus = resolve_macro_focus_date(events, now)
    focus_label = _format_focus_label(focus)
    day_events = _events_on_date(events, focus, tz)

    summary = analyze_macro_day(day_events, now)
    if not day_events:
        headline = f"{focus_label} — bez macro událostí · klidný den"
        recs = [
            f"Plán na {focus_label}: standardní M1 režim, Golden Window 14–18h.",
            "Žádné high-impact release — sleduj spread a Style Guide.",
        ]
        return MacroDaySummary(
            status=MacroStatus.CLEAR,
            headline=headline,
            caution_from=None,
            caution_until=None,
            active_now=False,
            recommendations=recs,
            event_count=0,
            focus_date=focus,
            focus_label=focus_label,
        )

    headline = summary.headline
    if focus_label and not headline.startswith(focus_label):
        headline = f"{focus_label} — {headline}"

    recs = list(summary.recommendations)
    if focus != now.date():
        recs.insert(
            0,
            f"Briefing na {focus_label} (dnes {_format_focus_label(now.date())} už bez macro tlaku).",
        )

    return MacroDaySummary(
        status=summary.status,
        headline=headline,
        caution_from=summary.caution_from,
        caution_until=summary.caution_until,
        active_now=summary.active_now,
        recommendations=recs,
        event_count=summary.event_count,
        focus_date=focus,
        focus_label=focus_label,
    )


_CATEGORY_RULES: list[tuple[tuple[str, ...], EventImpact]] = [
    (
        ("fomc", "fed rate", "interest rate", "rate decision"),
        EventImpact(
            category="Fed policy",
            gold_effect="Extrémní volatilita — směr až po prvním impulsu",
            action="NEOBCHODOVAT",
            trader_note="±30 min: žádné vstupy. Po uvolnění spreadu hledej obrat/false break.",
        ),
    ),
    (
        ("nfp", "non-farm", "payroll", "employment change"),
        EventImpact(
            category="Employment",
            gold_effect="Silná data → USD↑ Gold↓ | Slabá data → Gold↑",
            action="NEOBCHODOVAT",
            trader_note="Impuls často přebije trend. Čekej 15–30 min na ustálení.",
        ),
    ),
    (
        ("cpi", "ppi", "pce", "inflation"),
        EventImpact(
            category="Inflation",
            gold_effect="Vyšší inflace → Gold↑ (dlouhodobě) | krátký impuls obousměrný",
            action="NEOBCHODOVAT",
            trader_note="První reakce často falešná. Sleduj DXY synchron.",
        ),
    ),
    (
        ("gdp", "growth"),
        EventImpact(
            category="Growth",
            gold_effect="Silné GDP → USD↑ tlak na Gold",
            action="OPATRNĚ",
            trader_note="Menší impuls než CPI/NFP. Sniž lot nebo čekej potvrzení.",
        ),
    ),
    (
        ("unemployment", "jobless", "claims"),
        EventImpact(
            category="Labor",
            gold_effect="Slabší práh → Gold↑ | Silný trh práce → Gold↓",
            action="OPATRNĚ",
            trader_note="Střední volatilita. Drž SL širší než normálně.",
        ),
    ),
    (
        ("fed", "powell", "yellen", "fomc minutes", "beige book"),
        EventImpact(
            category="Fed rhetoric",
            gold_effect="Hawkish → Gold↓ | Dovish → Gold↑",
            action="OPATRNĚ",
            trader_note="Rychlé reverze během projevu. Scalp jen s potvrzením.",
        ),
    ),
]


def evaluate_event_impact(title: str) -> EventImpact:
    title_lower = title.lower()
    for keywords, impact in _CATEGORY_RULES:
        if any(kw in title_lower for kw in keywords):
            return impact
    return EventImpact(
        category="Macro",
        gold_effect="Neznámý dopad — očekávej zvýšenou volatilitu",
        action="OPATRNĚ",
        trader_note="Sleduj spread a ATR impuls po release.",
    )


def enrich_events(events: list[NewsEvent], now: datetime | None = None) -> list[EnrichedNewsEvent]:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    enriched: list[EnrichedNewsEvent] = []
    for e in events:
        local = e.event_time.astimezone(tz)
        local_str = local.strftime("%H:%M")
        impact = evaluate_event_impact(e.title)
        enriched.append(EnrichedNewsEvent(event=e, impact=impact, local_time=local_str))
    return enriched


def analyze_macro_day(events: list[NewsEvent], now: datetime | None = None) -> MacroDaySummary:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    buffer = timedelta(minutes=RISK.news_buffer_minutes)

    if not events or events[0].title.startswith(("Calendar Unavailable", "Kalendář nedostupný")):
        return MacroDaySummary(
            status=MacroStatus.CLEAR,
            headline=f"Kalendář prázdný — okno {MACRO.lookahead_days} dní",
            caution_from=None,
            caution_until=None,
            active_now=False,
            recommendations=["Standardní režim — řiď se M1 Analytics a session časem."],
            event_count=0,
        )

    relevant = [e for e in events if e.impact.lower() in ("high", "red")]
    if not relevant:
        relevant = events

    windows: list[tuple[datetime, datetime, NewsEvent]] = []
    for e in relevant:
        start = e.event_time - buffer
        end = e.event_time + buffer
        windows.append((start, end, e))

    caution_from = min(w[0] for w in windows)
    caution_until = max(w[1] for w in windows)
    active_now = caution_from <= now <= caution_until

    no_trade_count = sum(1 for e in relevant if evaluate_event_impact(e.title).action == "NEOBCHODOVAT")
    upcoming = [e for e in relevant if e.seconds_until > 0]
    past = [e for e in relevant if e.seconds_until <= 0]

    if active_now:
        status = MacroStatus.BLOCKED
        blocking = [e for e in relevant if abs(e.seconds_until) <= buffer.total_seconds()]
        titles = ", ".join(e.title[:30] for e in blocking[:2])
        headline = f"MACRO ZÓNA AKTIVNÍ — {titles}"
    elif no_trade_count >= 2:
        status = MacroStatus.CAUTION
        next_evt = upcoming[0] if upcoming else None
        if next_evt:
            mins = max(0, next_evt.seconds_until // 60)
            headline = f"{no_trade_count} high-impact událostí — první za {mins} min"
        else:
            headline = f"{no_trade_count} high-impact událostí dnes — macro den"
    elif upcoming:
        status = MacroStatus.CAUTION
        mins = max(0, upcoming[0].seconds_until // 60)
        headline = f"Macro za {mins} min — připrav se na zvýšenou volatilitu"
    elif past and (now - caution_until).total_seconds() < 1800:
        status = MacroStatus.CAUTION
        headline = "Post-macro fáze — spread a reverze stále možné"
    else:
        status = MacroStatus.CLEAR
        headline = "Macro okno uzavřeno — normální režim"

    recommendations: list[str] = []
    if active_now:
        recommendations.append(
            f"NEOBCHODOVAT do {caution_until.astimezone(tz).strftime('%H:%M')} CE(S)T "
            f"(±{RISK.news_buffer_minutes} min kolem událostí)."
        )
        if no_trade_count >= 2:
            recommendations.append(
                "Více událostí v jednom dni — po uvolnění čekej obrat/false break, ne continuation."
            )
        recommendations.append("Po macro: ověř spread < medián × 1.5 před vstupem.")
    elif status == MacroStatus.CAUTION:
        recommendations.append(
            f"Opatrnost od {caution_from.astimezone(tz).strftime('%H:%M')} "
            f"do {caution_until.astimezone(tz).strftime('%H:%M')} CE(S)T."
        )
        if no_trade_count >= 2:
            recommendations.append("Dnes macro-heavy den — preferuj menší lot a rychlé TP.")
        recommendations.append("Před událostí: žádné nové pozice, jen správa otevřených.")
    else:
        recommendations.append("Macro neblokuje — kombinuj s M1 Style Guide a Golden Window.")

    return MacroDaySummary(
        status=status,
        headline=headline,
        caution_from=caution_from,
        caution_until=caution_until,
        active_now=active_now,
        recommendations=recommendations,
        event_count=len(relevant),
    )
