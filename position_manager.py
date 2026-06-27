"""Per-position hold / close advisory engine."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5

from config import RISK
from indicators import IndicatorBundle, TrendBias
from macro_engine import MacroDaySummary, MacroStatus
from mt5_connector import MarketSnapshot, PositionInfo
from position_tracker import PositionTrackState
from risk_engine import Verdict, VerdictStatus
from signal_lab import SignalLabSnapshot, synthesize_m1_verdict
from trading_style import StyleGuide, TradingStyle
from user_insights import CheckItem, CheckStatus

ACTION_CLOSE = "ZAVŘÍT"
ACTION_PROTECT = "CHRÁNIT"
ACTION_WATCH = "KOREKCE"
ACTION_HOLD = "DRŽET"

_ACTION_ORDER = {ACTION_CLOSE: 0, ACTION_PROTECT: 1, ACTION_WATCH: 2, ACTION_HOLD: 3}
_TONE_MAP = {
    ACTION_CLOSE: "close",
    ACTION_PROTECT: "protect",
    ACTION_WATCH: "watch",
    ACTION_HOLD: "hold",
}


@dataclass(frozen=True)
class PositionVerdict:
    ticket: int
    side: str
    volume: float
    profit: float
    r_current: float | None
    action: str
    tone: str
    headline: str
    reasons: tuple[str, ...]
    metrics: tuple[CheckItem, ...]
    confidence: int
    position: PositionInfo


def _mtf_direction(indicators: IndicatorBundle | None, tfs: tuple[str, ...] = ("M5", "M15")) -> str:
    if not indicators:
        return "NEUTRAL"
    mtf = indicators.mtf_bias
    bulls = sum(1 for tf in tfs if mtf.get(tf) == TrendBias.BULL)
    bears = sum(1 for tf in tfs if mtf.get(tf) == TrendBias.BEAR)
    if bulls > bears:
        return "BULL"
    if bears > bulls:
        return "BEAR"
    return "NEUTRAL"


def _is_aligned(side: str, mtf_dir: str) -> bool:
    if mtf_dir == "NEUTRAL":
        return True
    if side == "BUY" and mtf_dir == "BULL":
        return True
    if side == "SELL" and mtf_dir == "BEAR":
        return True
    return False


def _macro_caution_soon(macro: MacroDaySummary | None, now: datetime) -> bool:
    if not macro or macro.status != MacroStatus.CAUTION:
        return False
    if macro.caution_from and macro.caution_until:
        tz = ZoneInfo(RISK.timezone)
        local_now = now.astimezone(tz)
        if macro.caution_from <= local_now <= macro.caution_until:
            return True
        delta = (macro.caution_from - local_now).total_seconds()
        return 0 <= delta <= 15 * 60
    return macro.status == MacroStatus.CAUTION


def _build_metrics(
    pos: PositionInfo,
    track: PositionTrackState | None,
    mtf_dir: str,
    aligned: bool,
    macro: MacroDaySummary | None,
    market: MarketSnapshot | None,
) -> tuple[CheckItem, ...]:
    items: list[CheckItem] = []
    r = pos.r_current
    items.append(
        CheckItem(
            "R nyní",
            f"{r:+.2f}R" if r is not None else "—",
            CheckStatus.OK if r and r >= 0 else CheckStatus.WARN if r and r > -0.5 else CheckStatus.FAIL,
        )
    )
    if track:
        items.append(
            CheckItem(
                "MFE / MAE",
                f"{track.mfe_r:+.1f}R / {track.mae_r:+.1f}R",
                CheckStatus.OK,
            )
        )
    if pos.sl_distance_pts is not None and market and market.atr > 0:
        sl_atr = pos.sl_distance_pts / market.atr
        items.append(
            CheckItem(
                "SL vzdálenost",
                f"{pos.sl_distance_pts:.1f} ({sl_atr:.1f}× ATR)",
                CheckStatus.WARN if sl_atr < 0.25 else CheckStatus.OK,
            )
        )
    items.append(
        CheckItem(
            "MTF M5/M15",
            mtf_dir + (" ✓" if aligned else " ✗"),
            CheckStatus.OK if aligned else CheckStatus.WARN,
        )
    )
    macro_label = macro.status.value if macro else "—"
    items.append(
        CheckItem(
            "Macro",
            macro_label,
            CheckStatus.FAIL
            if macro and macro.status == MacroStatus.BLOCKED
            else CheckStatus.WARN
            if macro and macro.status == MacroStatus.CAUTION
            else CheckStatus.OK,
        )
    )
    return tuple(items[:5])


def _evaluate_single(
    pos: PositionInfo,
    track: PositionTrackState | None,
    market: MarketSnapshot | None,
    indicators: IndicatorBundle | None,
    signal_lab: SignalLabSnapshot | None,
    style_guide: StyleGuide | None,
    verdict: Verdict | None,
    macro_summary: MacroDaySummary | None,
    now: datetime,
) -> PositionVerdict:
    side = pos.side or ("BUY" if pos.type == mt5.ORDER_TYPE_BUY else "SELL")
    r = pos.r_current
    mtf_dir = _mtf_direction(indicators)
    aligned = _is_aligned(side, mtf_dir)
    m1 = synthesize_m1_verdict(signal_lab)

    scores: list[tuple[int, str, str, str]] = []  # priority, action, headline, reason

    def add(priority: int, action: str, headline: str, reason: str) -> None:
        scores.append((priority, action, headline, reason))

    if verdict and verdict.status in (VerdictStatus.CRITICAL, VerdictStatus.BLOCKED):
        add(100, ACTION_CLOSE, "Účet v kritické zóně — zavři expozici", verdict.messages[0] if verdict.messages else "DD limit")

    if macro_summary and macro_summary.status == MacroStatus.BLOCKED:
        add(95, ACTION_CLOSE, "Macro blokuje držení", macro_summary.headline or "High-impact okno")

    if r is not None and r <= -0.75:
        add(90, ACTION_CLOSE, "Blízko stopu — thesis na hraně", f"Aktuálně {r:+.2f}R")

    if market and market.atr > 0 and pos.sl_distance_pts is not None:
        if pos.sl_distance_pts < market.atr * 0.25:
            add(88, ACTION_CLOSE, "Cena téměř u stop lossu", f"SL vzdálenost {pos.sl_distance_pts:.1f} (<0.25× ATR)")

    if market and market.spread_warning and pos.profit < 0:
        add(85, ACTION_CLOSE, "Spread vysoký + ztráta", "Exekuce zhoršuje R:R — exit")

    if track and track.mfe_r >= 1.0 and r is not None and r <= 0.4:
        if not aligned:
            add(80, ACTION_CLOSE, "Giveback zisku + MTF proti", f"MFE {track.mfe_r:+.1f}R → nyní {r:+.2f}R")
        else:
            add(70, ACTION_PROTECT, "Vratil profit z maxima", f"MFE {track.mfe_r:+.1f}R → zvaž BE / partial")

    if _macro_caution_soon(macro_summary, now):
        add(65, ACTION_PROTECT, "Macro okno blízko", "Posuň SL na BE nebo zmenši lot")

    if market and market.spread_warning and pos.profit >= 0:
        add(60, ACTION_PROTECT, "Spread nad normálem", "Chraň zisk — ne přidávej")

    if signal_lab and signal_lab.regime == "SWEEP":
        sweep_against = (side == "BUY" and m1.direction == "SHORT") or (side == "SELL" and m1.direction == "LONG")
        if sweep_against or m1.direction == "WAIT":
            add(55, ACTION_WATCH, "Liquidity sweep — ne chase proti", signal_lab.headline)

    if not aligned:
        if r is not None and r < 0:
            add(75, ACTION_CLOSE, "MTF proti směru pozice", f"Long/Short vs M5/M15 {mtf_dir}")
        else:
            add(50, ACTION_WATCH, "Krátkodobý proti-pohyb", f"MTF {mtf_dir} — sleduj SL, zatím korekce")

    if track and track.mae_r > -0.5 and aligned and r is not None and r < 0.3:
        add(40, ACTION_WATCH, "Pullback ve směru trendu", "Drž, ale sleduj — MAE v normě")

    if style_guide and style_guide.style in (TradingStyle.WAIT, TradingStyle.NO_TRADE):
        add(45, ACTION_WATCH, "Režim se změnil", style_guide.headline or style_guide.style.value)

    if r is not None and r >= 0.5 and aligned:
        add(10, ACTION_HOLD, "Trend drží — můžeš v klidu držet", f"+{r:.2f}R · MTF aligned")

    if not scores:
        if aligned:
            add(5, ACTION_HOLD, "Bez silného signálu — drž dle plánu", "Thesis zatím platí")
        else:
            add(30, ACTION_WATCH, "Neutrální kontext", "Sleduj MTF a SL")

    scores.sort(key=lambda x: x[0], reverse=True)
    _, action, headline, top_reason = scores[0]
    reasons = tuple(dict.fromkeys(s[3] for s in scores[:4]))
    confidence = min(100, scores[0][0] + (20 if action == ACTION_CLOSE else 10 if action == ACTION_PROTECT else 0))

    metrics = _build_metrics(pos, track, mtf_dir, aligned, macro_summary, market)

    return PositionVerdict(
        ticket=pos.ticket,
        side=side,
        volume=pos.volume,
        profit=pos.profit,
        r_current=r,
        action=action,
        tone=_TONE_MAP[action],
        headline=headline,
        reasons=reasons,
        metrics=metrics,
        confidence=confidence,
        position=pos,
    )


def evaluate_positions(
    positions: list[PositionInfo],
    tracks: dict[int, PositionTrackState] | None,
    market: MarketSnapshot | None,
    indicators: IndicatorBundle | None,
    signal_lab: SignalLabSnapshot | None,
    style_guide: StyleGuide | None,
    verdict: Verdict | None,
    macro_summary: MacroDaySummary | None,
    now: datetime | None = None,
) -> list[PositionVerdict]:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    tracks = tracks or {}
    results = [
        _evaluate_single(
            pos,
            tracks.get(pos.ticket),
            market,
            indicators,
            signal_lab,
            style_guide,
            verdict,
            macro_summary,
            now,
        )
        for pos in positions
    ]
    results.sort(key=lambda v: (_ACTION_ORDER[v.action], -v.confidence, v.ticket))
    return results


def summarize_position_verdicts(verdicts: list[PositionVerdict]) -> str:
    if not verdicts:
        return "0 pozic"
    counts: dict[str, int] = {}
    for v in verdicts:
        counts[v.action] = counts.get(v.action, 0) + 1
    parts = []
    for action in (ACTION_CLOSE, ACTION_PROTECT, ACTION_WATCH, ACTION_HOLD):
        if counts.get(action):
            parts.append(f"{counts[action]}× {action}")
    return " · ".join(parts)


def close_toast_candidates(verdicts: list[PositionVerdict]) -> list[tuple[str, str]]:
    """Return (toast_key, label) for ZAVŘÍT positions."""
    out: list[tuple[str, str]] = []
    for v in verdicts:
        if v.action != ACTION_CLOSE:
            continue
        r_txt = f"{v.r_current:+.1f}R" if v.r_current is not None else "—R"
        label = f"ZAVŘÍT #{v.ticket} · {v.side} · {r_txt} · {v.headline[:36]}"
        out.append((f"close-{v.ticket}", label))
    return out
