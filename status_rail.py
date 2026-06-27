"""Unified status rail — prioritized alert chips for the HUD header area."""

from __future__ import annotations

from dataclasses import dataclass

from indicators import IndicatorBundle
from macro_engine import MacroDaySummary, MacroStatus
from mt5_connector import MarketSnapshot
from risk_engine import Verdict, VerdictStatus
from trading_style import StyleGuide, TradingStyle
from user_insights import ScalpPlan


@dataclass(frozen=True)
class StatusChip:
    label: str
    priority: int  # 0 = critical, 1 = wait, 2 = info
    tone: str  # critical | wait | info


def _shorten(text: str, max_len: int = 32) -> str:
    text = text.strip()
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def build_status_rail(
    alerts: list[str],
    verdict: Verdict | None,
    plan: ScalpPlan | None,
    style_guide: StyleGuide | None,
    macro_summary: MacroDaySummary | None,
    market: MarketSnapshot | None,
    indicators: IndicatorBundle | None,
    max_items: int = 3,
) -> list[StatusChip]:
    chips: list[StatusChip] = []
    seen: set[str] = set()

    def add(label: str, priority: int, tone: str) -> None:
        key = label.upper()
        if key in seen:
            return
        seen.add(key)
        chips.append(StatusChip(label=_shorten(label), priority=priority, tone=tone))

    for alert in alerts:
        upper = alert.upper()
        if any(k in upper for k in ("KRITICK", "CRITICAL", "BLOK", "STOP", "ANOMÁL")):
            add(alert.replace("[", "").replace("]", "").strip(), 0, "critical")
        elif "POZOR" in upper or "WARN" in upper:
            add(alert, 1, "wait")

    if verdict:
        if verdict.status in (VerdictStatus.CRITICAL, VerdictStatus.BLOCKED):
            msg = verdict.messages[0] if verdict.messages else verdict.status.value
            add(_shorten(msg, 28), 0, "critical")
        elif verdict.status == VerdictStatus.CAUTION and verdict.messages:
            add(_shorten(verdict.messages[0], 28), 1, "wait")

    if plan:
        if plan.gate_action == "NE":
            reason = plan.reasons[0] if plan.reasons else "Neobchodovat"
            add(_shorten(reason, 28), 0, "critical")
        elif plan.gate_action == "POČKEJ":
            reason = plan.reasons[0] if plan.reasons else "Počkej"
            add(_shorten(reason, 28), 1, "wait")

    if verdict and not verdict.golden_window_active:
        add("Mimo GW", 1, "wait")

    if macro_summary and macro_summary.status == MacroStatus.CAUTION:
        add(macro_summary.headline or "Macro CAUTION", 1, "wait")

    if style_guide and style_guide.style == TradingStyle.WAIT:
        add(style_guide.headline or "WAIT / REDUCE", 1, "wait")

    if market and market.spread_warning:
        add(f"Spread {market.spread_points:.0f}p", 2, "info")

    if market and market.atr_impulse:
        add("ATR impulse", 2, "info")

    if indicators and indicators.bb.is_squeeze:
        add("BB squeeze", 2, "info")

    chips.sort(key=lambda c: c.priority)
    return chips[:max_items]
