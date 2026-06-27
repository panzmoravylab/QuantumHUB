"""
Risk engine: drawdown tracking, lot sizing, contextual rule engine (The Verdict).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from zoneinfo import ZoneInfo

from config import ACCOUNT, INDICATORS, RISK
from mt5_connector import AccountSnapshot, MarketSnapshot


class VerdictStatus(str, Enum):
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    BLOCKED = "BLOCKED"
    CRITICAL = "CRITICAL"


@dataclass
class NewsEvent:
    title: str
    currency: str
    impact: str
    event_time: datetime
    seconds_until: int


@dataclass
class SessionInfo:
    name: str
    start_hour: int
    end_hour: int
    active: bool


@dataclass
class Verdict:
    status: VerdictStatus
    messages: list[str]
    golden_window_active: bool
    news_blocked: bool
    spread_blocked: bool


@dataclass
class LotSizeResult:
    risk_pct: float
    risk_usd: float
    sl_points: float
    lot_size: float
    message: str


def calc_lot_size(
    equity: float,
    sl_distance_price: float,
    tick_value: float,
    tick_size: float,
    risk_pct: float = ACCOUNT.default_risk_pct,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
    lot_step: float = 0.01,
) -> LotSizeResult:
    """
    Calculate position size based on % risk and SL distance.
    sl_distance_price: absolute price distance to stop loss.
    """
    if sl_distance_price <= 0 or tick_size <= 0 or tick_value <= 0:
        return LotSizeResult(
            risk_pct=risk_pct,
            risk_usd=0,
            sl_points=0,
            lot_size=0,
            message="Neplatný SL nebo symbol info",
        )

    risk_usd = equity * (risk_pct / 100)
    sl_ticks = sl_distance_price / tick_size
    risk_per_lot = sl_ticks * tick_value
    raw_lots = risk_usd / risk_per_lot if risk_per_lot else 0

    steps = int(raw_lots / lot_step) if lot_step > 0 else 0
    lots = round(min(max_lot, steps * lot_step), 2)

    if lots < min_lot:
        return LotSizeResult(
            risk_pct=risk_pct,
            risk_usd=round(risk_usd, 2),
            sl_points=round(sl_ticks, 1),
            lot_size=0,
            message="Lot pod minimem brokera — snižte risk nebo SL",
        )

    return LotSizeResult(
        risk_pct=risk_pct,
        risk_usd=round(risk_usd, 2),
        sl_points=round(sl_ticks, 1),
        lot_size=lots,
        message=f"{risk_pct}% risk @ SL → {lots} lotů (${risk_usd:.0f} risk)",
    )


def get_session_timeline(now: datetime | None = None) -> list[SessionInfo]:
    """Return trading session states (UTC hours)."""
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    utc_hour = now.astimezone(ZoneInfo("UTC")).hour

    sessions = [
        SessionInfo("Asian", 0, 8, 0 <= utc_hour < 8),
        SessionInfo("London", 8, 16, 8 <= utc_hour < 16),
        SessionInfo("New York", 13, 22, 13 <= utc_hour < 22),
    ]
    return sessions


def is_golden_window(now: datetime | None = None) -> bool:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    local = now.astimezone(tz)
    return RISK.golden_window_start_hour <= local.hour < RISK.golden_window_end_hour


def evaluate_verdict(
    account: AccountSnapshot | None,
    market: MarketSnapshot | None,
    news_events: list[NewsEvent] | None = None,
    now: datetime | None = None,
) -> Verdict:
    """Contextual rule engine — The Verdict."""
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    messages: list[str] = []
    status = VerdictStatus.CLEAR

    if account is None or not account.connected:
        return Verdict(
            status=VerdictStatus.BLOCKED,
            messages=["[OFFLINE] MT5 není připojen — žádné live data."],
            golden_window_active=False,
            news_blocked=False,
            spread_blocked=False,
        )

    golden = is_golden_window(now)
    news_blocked = False
    spread_blocked = False

    if account and account.is_critical:
        status = VerdictStatus.CRITICAL
        messages.append("[KRITICKÉ] Denní drawdown blízko limitu — zastavte obchodování.")

    if account and account.trailing_drawdown_pct >= ACCOUNT.trailing_drawdown_limit_pct:
        status = VerdictStatus.CRITICAL
        messages.append(
            f"[KRITICKÉ] Trailing DD {account.trailing_drawdown_pct:.1f}% "
            f"(limit {ACCOUNT.trailing_drawdown_limit_pct}%)"
        )
    elif account and account.trailing_drawdown_pct >= ACCOUNT.trailing_drawdown_limit_pct * 0.8:
        if status != VerdictStatus.CRITICAL:
            status = VerdictStatus.CAUTION
        messages.append(
            f"[POZOR] Trailing DD {account.trailing_drawdown_pct:.1f}% "
            f"(limit {ACCOUNT.trailing_drawdown_limit_pct}%)"
        )

    if market and market.spread_warning:
        spread_blocked = True
        status = VerdictStatus.BLOCKED
        messages.append("[BLOK] Vysoký spread — transakční náklady nad normálem.")

    if market and market.atr_impulse:
        if status == VerdictStatus.CLEAR:
            status = VerdictStatus.CAUTION
        messages.append("[POZOR] ATR impulz — skok volatility.")

    buffer = timedelta(minutes=RISK.news_buffer_minutes)
    if news_events:
        for event in news_events:
            if event.impact.lower() in ("high", "red"):
                event_local = event.event_time.astimezone(tz)
                delta = abs((event_local - now.astimezone(tz)).total_seconds())
                if delta <= buffer.total_seconds():
                    news_blocked = True
                    status = VerdictStatus.BLOCKED
                    messages.append(
                        f"[BLOK] Makro událost: {event.title}. Riziko skluzu."
                    )
                    break

    if not golden:
        if status == VerdictStatus.CLEAR:
            status = VerdictStatus.CAUTION
        messages.append(
            "[NÍZKÁ LIKVIDITA] Mimo golden window — spíš chop/akumulace než breakout."
        )
    else:
        messages.append("[GOLDEN WINDOW] 14:00–18:00 CE(S)T — optimální likvidita zlata.")

    if not messages:
        messages.append("[VOLNO] Vše v pořádku — exekuce povolena.")

    return Verdict(
        status=status,
        messages=messages,
        golden_window_active=golden,
        news_blocked=news_blocked,
        spread_blocked=spread_blocked,
    )


def session_progress_pct(now: datetime | None = None) -> float:
    """24h cycle progress 0-100 for session timeline bar."""
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    local = now.astimezone(tz)
    seconds = local.hour * 3600 + local.minute * 60 + local.second
    return (seconds / 86400) * 100


def golden_window_progress(now: datetime | None = None) -> tuple[float, float]:
    """Return start/end pct on 24h bar for golden window highlight."""
    start_pct = (RISK.golden_window_start_hour / 24) * 100
    end_pct = (RISK.golden_window_end_hour / 24) * 100
    return start_pct, end_pct
