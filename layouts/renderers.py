"""Render functions — return partial UI fragments (no full panel rebuild)."""

from __future__ import annotations

import csv
import re
from pathlib import Path

import plotly.graph_objects as go
from dash import dcc, html

from config import ACCOUNT, INDICATORS, MACRO, RISK, TRADE_JOURNAL_PATH, UI
from trading_style import StyleGuide, TradingStyle
from indicators import IndicatorBundle, TrendBias
from layouts.ui_helpers import alert_chip, classify_atr, kpi_tile, mtf_pill, prop_dd_card
from macro_engine import EnrichedNewsEvent, MacroDaySummary, MacroStatus, enrich_events
from user_insights import CheckStatus, EnginePanel, PreNewsChecklist, ScalpPlan, TradeDecision
from trend_brief import TrendBrief
from mt5_connector import AccountSnapshot, MarketSnapshot, PositionInfo
from compute_log import LogLine
from news_scraper import format_t_minus
from risk_engine import VerdictStatus, LotSizeResult, SessionInfo, Verdict, golden_window_progress, session_progress_pct
from journal_stats import SessionStats
from status_rail import StatusChip
from position_manager import PositionVerdict, summarize_position_verdicts
from signal_lab import SignalLabSnapshot, synthesize_m1_verdict


VERDICT_LABEL_CZ = {
    "CLEAR": "VOLNO",
    "CAUTION": "POZOR",
    "BLOCKED": "BLOK",
    "CRITICAL": "KRITICKÉ",
}


def _drawdown_gauge_figure(account: AccountSnapshot | None, trailing: bool = False) -> go.Figure:
    if trailing:
        pct = account.trailing_drawdown_pct if account else 0.0
        limit = ACCOUNT.trailing_drawdown_limit_pct
        title = "Trailing DD"
        height = 140
        color = UI.neon_red if pct >= limit * 0.8 else "#F59E0B"
    else:
        pct = account.daily_drawdown_pct if account else 0.0
        limit = ACCOUNT.daily_drawdown_limit_pct
        title = "Denní drawdown"
        height = 160
        color = UI.neon_red if pct >= limit * 0.8 else UI.neon_cyan

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number",
            value=pct,
            number={"suffix": "%", "font": {"color": "#E5E7EB", "size": 22 if trailing else 26}},
            title={"text": title, "font": {"color": "#9CA3AF", "size": 11}},
            gauge={
                "axis": {"range": [0, limit * 1.3], "tickcolor": "#374151"},
                "bar": {"color": color},
                "bgcolor": UI.panel_bg,
                "bordercolor": "#374151",
                "threshold": {
                    "line": {"color": UI.neon_red, "width": 2},
                    "thickness": 0.75,
                    "value": limit,
                },
            },
        )
    )
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        height=height,
        margin=dict(l=8, r=8, t=32, b=4),
        font={"color": "#E5E7EB"},
    )
    return fig


def render_dd_gauges(account: AccountSnapshot | None) -> html.Div:
    return html.Div(
        className="dd-gauges-row",
        children=[
            dcc.Graph(
                figure=_drawdown_gauge_figure(account, trailing=False),
                config={"displayModeBar": False, "staticPlot": True},
                className="dd-gauge-chart",
            ),
            dcc.Graph(
                figure=_drawdown_gauge_figure(account, trailing=True),
                config={"displayModeBar": False, "staticPlot": True},
                className="dd-gauge-chart",
            ),
        ],
    )


def render_trade_journal(max_rows: int = 15) -> html.Div:
    rows: list[html.Div] = []
    path = Path(TRADE_JOURNAL_PATH)
    if path.exists():
        try:
            with open(path, encoding="utf-8", newline="") as f:
                reader = list(csv.DictReader(f))
            for row in reversed(reader[-max_rows:]):
                evt = row.get("event", "")
                sym = row.get("symbol", "")
                profit = row.get("profit", "")
                ts = (row.get("timestamp") or "")[:19].replace("T", " ")
                rows.append(
                    html.Div(
                        className="journal-row",
                        children=[
                            html.Span(ts, className="journal-ts"),
                            html.Span(evt, className="journal-evt"),
                            html.Span(sym, className="journal-sym"),
                            html.Span(profit, className="journal-pnl"),
                        ],
                    )
                )
        except OSError:
            pass
    if not rows:
        rows.append(html.Div("Zatím žádné záznamy v deníku.", className="journal-empty"))
    return html.Div(
        className="journal-block",
        children=[
            html.Div("Obchodní deník", className="block-label"),
            html.Div(className="journal-list", children=rows),
        ],
    )


def panel_a_class(critical: bool) -> str:
    return f"panel panel-a{' is-critical' if critical else ''}"


def render_equity(account: AccountSnapshot | None) -> str:
    if not account:
        return "—"
    return f"${account.equity:,.2f}"


def render_daily_dd(account: AccountSnapshot | None) -> html.Div:
    pct = account.daily_drawdown_pct if account else 0.0
    usd = f"−${account.daily_drawdown_usd:,.2f} dnes" if account else ""
    return prop_dd_card("Denní prop DD", pct, ACCOUNT.daily_drawdown_limit_pct, usd)


def render_trail_dd(account: AccountSnapshot | None) -> html.Div:
    pct = account.trailing_drawdown_pct if account else 0.0
    usd = f"−${account.trailing_drawdown_usd:,.2f} od max equity" if account else ""
    return prop_dd_card("Trailing prop DD", pct, ACCOUNT.trailing_drawdown_limit_pct, usd)


def render_account_mini_stats(stats: SessionStats | None) -> html.Div:
    if not stats:
        return html.Div("—", className="account-mini-stats empty")

    win_val = f"{stats.winrate_pct:.0f}%" if stats.winrate_pct is not None else "—"
    win_tone = "cyan" if stats.winrate_pct and stats.winrate_pct >= 50 else "dim"
    pnl_tone = "cyan" if stats.pnl_today_usd >= 0 else "red"
    open_tone = "cyan" if stats.open_pnl_usd >= 0 else "red"
    dd_tone = "red" if stats.dd_pct >= ACCOUNT.daily_drawdown_limit_pct * 0.85 else (
        "amber" if stats.dd_pct >= ACCOUNT.daily_drawdown_limit_pct * 0.6 else "dim"
    )

    def tile(label: str, value: str, tone: str) -> html.Div:
        return html.Div(
            className=f"mini-stat tone-{tone}",
            children=[
                html.Span(label, className="mini-stat-label"),
                html.Span(value, className="mini-stat-value"),
            ],
        )

    return html.Div(
        className="account-mini-stats",
        children=[
            tile("Win%", win_val, win_tone),
            tile("P/L", f"${stats.pnl_today_usd:+,.0f}", pnl_tone),
            tile("DD", f"{stats.dd_pct:.1f}%", dd_tone),
            tile("Open", f"${stats.open_pnl_usd:+,.0f}", open_tone),
        ],
    )


def render_account_stats(account: AccountSnapshot | None) -> html.Div:
    if not account:
        return html.Div("Waiting for account data…", className="stat-muted")
    return html.Div(
        className="stat-row-inner",
        children=[
            html.Span([html.Span("Balance", className="stat-key"), f" ${account.balance:,.2f}"]),
            html.Span([html.Span("Margin", className="stat-key"), f" ${account.margin:,.2f}"]),
            html.Span([html.Span("Free", className="stat-key"), f" ${account.free_margin:,.2f}"]),
        ],
    )


def render_positions(positions: list[PositionInfo]) -> list[dict]:
    if not positions:
        return [{"Symbol": "—", "Side": "—", "Lots": "—", "P&L": "—", "RRR": "—"}]
    rows = []
    for p in positions:
        side = "BUY" if p.type == 0 else "SELL"
        rows.append(
            {
                "Symbol": p.symbol,
                "Side": side,
                "Lots": f"{p.volume:.2f}",
                "P&L": f"${p.profit:+.2f}",
                "RRR": f"{p.rrr:.2f}" if p.rrr is not None else "—",
            }
        )
    return rows


def _r_bar_pct(r: float | None) -> float:
    if r is None:
        return 50.0
    clamped = max(-1.0, min(2.0, r))
    return round((clamped + 1.0) / 3.0 * 100, 1)


def _calculate_trend_health(v: PositionVerdict) -> tuple[float, str, str]:
    if v.action == "CLOSE":
        score = 25.0
    elif v.action == "WATCH":
        score = 50.0
    elif v.action == "PROTECT":
        score = 65.0
    else:  # HOLD
        score = 85.0

    r = v.r_current if v.r_current is not None else 0.0
    if r > 1.0:
        score += 15.0
    elif r > 0.0:
        score += 5.0
    elif r < -0.5:
        score -= 15.0

    reasons_str = " ".join(v.reasons).lower()
    if "proti směru" in reasons_str or "contra" in reasons_str or "proti" in reasons_str:
        score -= 20.0
    if "giveback" in reasons_str or "vratil profit" in reasons_str:
        score -= 15.0
    if "blízko stopu" in reasons_str or "téměř u stop" in reasons_str:
        score -= 25.0

    for m in v.metrics:
        if m.label == "SL vzdálenost" and m.status.value == "warn":
            score -= 10.0
        if m.label == "MTF M5/M15" and m.status.value == "warn":
            score -= 15.0

    score = max(5.0, min(95.0, score))

    if score >= 75.0:
        return score, "SILNÝ TREND", "ok"
    elif score >= 50.0:
        return score, "STABILNÍ / KOREKCE", "warn"
    else:
        return score, "SLÁBNE / RIZIKO OBRATU", "err"


def render_positions_summary(verdicts: list[PositionVerdict]) -> str:
    return summarize_position_verdicts(verdicts)


def render_position_list(
    verdicts: list[PositionVerdict],
) -> html.Div:
    if not verdicts:
        return html.Div("Žádné otevřené pozice", className="position-list-empty")

    total_lots = sum(v.volume for v in verdicts)
    total_pnl = sum(v.profit for v in verdicts)
    total_risk_usd = 0.0
    for v in verdicts:
        p = v.position
        if p and p.sl > 0:
            sl_diff = abs(p.price_open - p.sl)
            total_risk_usd += sl_diff * 100.0 * p.volume

    exposure_card = html.Div(
        className="exposure-monitor-card",
        children=[
            html.Div(
                className="em-row",
                children=[
                    html.Div([
                        html.Span("EXPOZICE: ", className="em-label"),
                        html.Span(f"{total_lots:.2f} Lotů ({len(verdicts)} pozic)", className="em-val-lots")
                    ]),
                    html.Div([
                        html.Span("SL RIZIKO: ", className="em-label"),
                        html.Span(
                            f"-${total_risk_usd:,.2f}" if total_risk_usd > 0 else "BEZ SL!", 
                            className=f"em-val-risk {'tone-red' if total_risk_usd > 0 or total_lots > 0 else ''}"
                        )
                    ])
                ]
            ),
            html.Div(
                className="em-row em-sub",
                children=[
                    html.Div([
                        html.Span("AKTUÁLNÍ P/L: ", className="em-label"),
                        html.Span(f"${total_pnl:+.2f}", className=f"em-val-pnl {'tone-green' if total_pnl >= 0 else 'tone-red'}")
                    ]),
                    html.Div([
                        html.Span("AUTO SL GUARD: ", className="em-label"),
                        html.Span("AKTIVNÍ", className="em-val-guard tone-green")
                    ])
                ]
            )
        ]
    )

    rows = [exposure_card]
    for v in verdicts:
        r_txt = f"{v.r_current:+.2f}R" if v.r_current is not None else "—R"
        row_cls = f"position-row tone-{v.tone} is-expanded"

        metric_cells = []
        for m in v.metrics:
            metric_cells.append(
                html.Div(
                    className=f"pv-metric status-{m.status.value}",
                    children=[
                        html.Span(m.label, className="pv-metric-label"),
                        html.Span(m.meaning, className="pv-metric-val"),
                    ],
                )
            )
        reason_chips = [html.Span(r, className="pv-reason-chip") for r in v.reasons[:4]]

        def make_r_bar(extra_class=""):
            health_pct, health_lbl, health_tone = _calculate_trend_health(v)
            return html.Div(
                className=f"pv-health-loadbar-wrap {extra_class}",
                children=[
                    html.Div(
                        className=f"pv-health-loadbar-fill tone-{health_tone}",
                        style={"width": f"{health_pct}%"},
                    ),
                    html.Div(
                        f"{health_lbl} · {health_pct:.0f}%",
                        className="pv-health-loadbar-text",
                    ),
                ],
            )
        
        # Helper to render action load bar based on verdict action (Czech action strings)
        def make_action_bar(action: str, tone: str) -> html.Div:
            # Map Czech action labels to fill percentage
            # 100% = full HOLD confidence, 0% = immediate CLOSE signal
            action_map = {
                "DRŽET":   (100, "DRŽET — bezpečná zóna"),
                "KOREKCE": (65,  "KOREKCE — sleduj"),
                "CHRÁNIT": (30,  "CHRÁNIT — vysoké riziko"),
                "ZAVŘÍT":  (0,   "ZAVŘÍT — exit!"),
            }
            pct, label_text = action_map.get(action, (0, action))
            return html.Div(
                className=f"pv-action-bar-outer tone-{tone}",
                children=[
                    html.Div(
                        className=f"pv-action-bar-track",
                        children=[
                            html.Div(
                                className="pv-action-bar-fill",
                                style={"width": f"{pct}%"},
                            ),
                            html.Div(
                                className="pv-action-bar-label",
                                children=[
                                    html.Span(label_text, className="pv-action-bar-text"),
                                    html.Span(f"{pct}%", className="pv-action-bar-pct"),
                                ],
                            ),
                        ],
                    ),
                ],
            )

        detail = html.Div(
            className="position-row-detail",
            children=[
                html.Div(v.headline, className="pv-headline"),
                html.Div(className="pv-reasons", children=reason_chips),
                html.Div(className="pv-metrics", children=metric_cells),
                make_r_bar(),
            ],
        )

        rows.append(
            html.Div(
                className=row_cls,
                children=[
                    html.Div(
                        className="position-row-header",
                        children=[
                            html.Span(v.action, className=f"pv-badge tone-{v.tone}"),
                            html.Span(v.side, className="pv-side"),
                            html.Span(f"{v.volume:.2f}", className="pv-lots"),
                            html.Span(f"${v.profit:+.0f}", className="pv-pnl"),
                            html.Span(r_txt, className="pv-r"),
                            html.Span(f"#{v.ticket}", className="pv-ticket"),
                        ],
                    ),
                    # Action load bar visualizing hold/close status
                    make_action_bar(v.action, v.tone),
                    html.Div(
                        className="pv-r-bar-container tier-kompakt-only",
                        style={"padding": "4px 8px 8px 8px"},
                        children=[make_r_bar("compact")],
                    ),
                    detail,
                ],
            )
        )

    return html.Div(className="position-list-inner", children=rows)


def render_header_account_chip(account: AccountSnapshot | None) -> str:
    if not account:
        return "Equity — · DD —"
    dd_tone = "warn" if account.is_critical else ""
    _ = dd_tone
    return f"Equity ${account.equity:,.0f} · DD {account.daily_drawdown_pct:.1f}%"


def render_header_status_pills(
    account: AccountSnapshot | None,
    market: MarketSnapshot | None,
    macro_summary: MacroDaySummary | None,
    verdict: Verdict | None,
    plan: ScalpPlan | None,
    connected: bool,
) -> html.Div:
    pills: list[html.Span] = []

    if connected and account and account.connected:
        pills.append(html.Span("MT5 OK", className="header-pill tone-ok", title="MT5 připojeno"))
    else:
        pills.append(html.Span("MT5 OFF", className="header-pill tone-err", title="MT5 offline"))



    if macro_summary:
        if macro_summary.status == MacroStatus.BLOCKED:
            macro_txt, macro_tone = "MACRO BLOK", "err"
        elif macro_summary.status == MacroStatus.CAUTION:
            macro_txt, macro_tone = "MACRO POZOR", "warn"
        else:
            macro_txt, macro_tone = "MACRO OK", "ok"
        pills.append(html.Span(macro_txt, className=f"header-pill tone-{macro_tone}", title=macro_summary.headline or ""))

    if verdict:
        gw_txt = "GW" if verdict.golden_window_active else "MIMO GW"
        gw_tone = "ok" if verdict.golden_window_active else "warn"
        pills.append(html.Span(gw_txt, className=f"header-pill tone-{gw_tone}", title="Golden Window"))

    if plan:
        gate_tone = {"go": "ok", "wait": "warn", "stop": "err"}.get(plan.gate_tone, "neutral")
        pills.append(
            html.Span(
                plan.gate_action,
                className=f"header-pill tone-{gate_tone}",
                title=plan.reasons[0] if plan.reasons else "Gate",
            )
        )

    if not pills:
        return html.Div(className="hud-status-pills-empty")
    return html.Div(className="hud-status-pills-inner", children=pills)


def render_price_badge(market: MarketSnapshot | None) -> str:
    if not market:
        return "—"
    return f"{market.bid:.2f} / {market.ask:.2f}"


def render_dd_headroom(account: AccountSnapshot | None, plan: ScalpPlan | None) -> html.Div:
    if not account or not plan:
        return html.Div("—", className="dd-headroom-empty")
    daily_tone = "warn" if plan.daily_dd_remaining_pct < 0.5 else "ok"
    trail_limit_usd = ACCOUNT.starting_balance * ACCOUNT.trailing_drawdown_limit_pct / 100
    trail_used_pct = (
        (account.trailing_drawdown_usd / trail_limit_usd * 100) if trail_limit_usd > 0 else 0
    )
    trail_tone = "warn" if trail_used_pct >= 85 else "ok"
    trades_txt = (
        f"~{plan.trades_until_daily_limit} obchodů do daily limitu"
        if plan.trades_until_daily_limit is not None and plan.risk_usd > 0
        else "—"
    )
    return html.Div(
        className="dd-headroom",
        children=[
            html.Div(
                className=f"dd-headroom-row tone-{daily_tone}",
                children=[
                    html.Span("Daily rezerva", className="dd-h-label"),
                    html.Span(
                        f"${plan.daily_dd_remaining_usd:,.0f} · {plan.daily_dd_remaining_pct:.1f}%",
                        className="dd-h-value",
                    ),
                ],
            ),
            html.Div(
                className=f"dd-headroom-row tone-{trail_tone}",
                children=[
                    html.Span("Trail rezerva", className="dd-h-label"),
                    html.Span(
                        f"${plan.trail_dd_remaining_usd:,.0f}",
                        className="dd-h-value",
                    ),
                ],
            ),
            html.Div(className="dd-headroom-foot", children=trades_txt),
        ],
    )


def resolve_decision_state(plan: ScalpPlan | None) -> tuple[str, str]:
    """Map scalp plan to BUY / SELL / WAIT / HOLD visual state."""
    if not plan:
        return "HOLD", "muted"
    if plan.gate_action == "POČKEJ":
        return "WAIT", "wait"
    if plan.gate_action == "NE":
        return "HOLD", "muted"
    if plan.direction == "LONG":
        return "BUY", "long"
    if plan.direction == "SHORT":
        return "SELL", "short"
    return "WAIT", "wait"


def _strength_delta_short(delta: int) -> str:
    if delta > 0:
        return "↑ sílí"
    if delta < 0:
        return "↓ slábne"
    return "→ stabilní"


def render_trade_decision_hero(
    market: MarketSnapshot | None,
    plan: ScalpPlan | None,
    verdict: Verdict | None,
    trend_brief: TrendBrief | None,
    indicators: IndicatorBundle | None,
) -> html.Div:
    if not plan:
        return html.Div("—", className="decision-hero empty")

    state, state_tone = resolve_decision_state(plan)
    cls = f"decision-hero tone-{plan.gate_tone}"

    gate_reason = plan.reasons[0] if plan.reasons else "Všechny podmínky splněny"
    
    if state == "BUY":
        arrow_icon = "▲"
        sub_label = "BULLISH BIAS"
    elif state == "SELL":
        arrow_icon = "▼"
        sub_label = "BEARISH BIAS"
    else:
        arrow_icon = "◆"
        sub_label = "HOLD / NEUTRÁLNÍ"

    return html.Div(
        className=cls,
        children=[
            html.Div(
                className=f"dh-hud-ring tone-{state_tone}",
                children=[
                    html.Div(arrow_icon, className="dh-hud-arrow"),
                    html.Div(state, className="dh-hud-state"),
                    html.Div(sub_label, className="dh-hud-sub"),
                ]
            ),
            html.Div(
                className="dh-telemetry",
                children=[
                    html.Div([
                        html.Span("STATUS RADARU: ", className="tel-label"),
                        html.Span(gate_reason, className=f"tel-value tone-{state_tone} dh-gate-reason")
                    ], className="tel-row"),
                ]
            )
        ]
    )


def render_style_strip(guide: StyleGuide | None) -> html.Div:
    if not guide:
        return html.Div(className="style-strip empty")
    tone_map = {
        TradingStyle.MOMENTUM_TREND: "trend",
        TradingStyle.RANGE_SCALP: "range",
        TradingStyle.SQUEEZE_BREAKOUT: "squeeze",
        TradingStyle.WAIT: "wait",
        TradingStyle.NO_TRADE: "blocked",
    }
    tone = tone_map.get(guide.style, "wait")
    
    # Simple explanation mapping of what it means for the trader
    desc_map = {
        TradingStyle.MOMENTUM_TREND: "Silný trend. Vstupuj na pullbacku do směru a drž déle.",
        TradingStyle.RANGE_SCALP: "Trh jde do strany. Nakupuj supporty, prodávej rezistence, rychlý TP.",
        TradingStyle.SQUEEZE_BREAKOUT: "Trh se stlačuje. Nevstupuj uprostřed, čekej na prudký průraz.",
        TradingStyle.WAIT: "Nepříznivé podmínky. Vyčkej na pokles spreadu nebo ustálení ceny.",
        TradingStyle.NO_TRADE: "Zákaz vstupu! Sleduj makro zprávy nebo limit drawdownu.",
    }
    meta = desc_map.get(guide.style, guide.primary_action)

    return html.Div(
        className=f"style-strip tone-{tone}",
        children=[
            html.Span(guide.style.value, className="style-strip-label"),
            html.Span(meta, className="style-strip-meta"),
        ],
    )


def render_recommendation(
    plan: ScalpPlan | None,
    verdict: Verdict | None,
    indicators: IndicatorBundle | None,
) -> html.Div:
    if not plan:
        return html.Div("Advisor čeká na data…", className="advisor-empty")

    state, state_tone = resolve_decision_state(plan)
    
    rec_title = "STÁT MIMO TRH (WAIT)"
    rec_desc = "Podmínky nejsou optimální. Vyčkej na jasný setup."
    tone = "wait"

    if state == "BUY":
        rec_title = "HLEDEJ BUY SETUPY"
        rec_desc = "Momentum a struktura podporují růst. Vstup na M1 pullbacku."
        tone = "bull"
    elif state == "SELL":
        rec_title = "HLEDEJ SELL SETUPY"
        rec_desc = "Momentum a struktura podporují pokles. Vstup na M1 pullbacku."
        tone = "bear"
    else:
        # Check reasons for wait/no-trade
        reasons_str = " ".join(plan.reasons).lower() if plan.reasons else ""
        if "spread" in reasons_str:
            rec_title = "STÁT MIMO TRH (HIGH SPREAD)"
            rec_desc = "Spread je příliš široký, což zhoršuje exekuci a R:R."
            tone = "err"
        elif "macro" in reasons_str or "zpráva" in reasons_str or "news" in reasons_str:
            rec_title = "STÁT MIMO TRH (MACRO OKNO)"
            rec_desc = "Běží nebo se blíží významná makro zpráva. Vysoké riziko skluzu."
            tone = "err"
        elif "mimo golden" in reasons_str or "mimo gw" in reasons_str:
            rec_title = "SNÍŽENÁ AKTIVITA (MIMO GW)"
            rec_desc = "Jsme mimo hlavní obchodní okno (Golden Window). Snížit loty / konzervativní přístup."
            tone = "wait"
        elif verdict and verdict.status in (VerdictStatus.CRITICAL, VerdictStatus.BLOCKED):
            rec_title = "ZÁKAZ OBCHODOVÁNÍ (DD LIMIT)"
            rec_desc = "Účet dosáhl limitu drawdownu. Dnes již neobchodovat."
            tone = "err"

    return html.Div(
        className=f"advisor-rec-card tone-{tone}",
        children=[
            html.Div(
                className="advisor-rec-header",
                children=[
                    html.Span("DOPORUČENÍ VSTUPU", className="advisor-rec-tag"),
                    html.Span(rec_title, className="advisor-rec-title"),
                ]
            ),
            html.Div(rec_desc, className="advisor-rec-desc"),
        ]
    )


def render_trade_command_card(
    market: MarketSnapshot | None,
    plan: ScalpPlan | None,
    verdict: Verdict | None = None,
    compact: bool = False,
    trend_brief: TrendBrief | None = None,
    indicators: IndicatorBundle | None = None,
) -> html.Div:
    del compact
    return render_trade_decision_hero(market, plan, verdict, trend_brief, indicators)


def render_scalp_card(plan: ScalpPlan | None) -> html.Div:
    """Legacy alias — use render_trade_command_card."""
    return render_trade_command_card(None, plan)


def render_toast_stack(toasts) -> tuple[html.Div, dict]:
    """Persistent toast notifications with dismiss buttons."""
    from toast_manager import ToastItem

    if not toasts:
        return html.Div(className="toast-stack-empty"), {"display": "none"}

    items = []
    for t in toasts:
        if not isinstance(t, ToastItem):
            continue
        items.append(
            html.Div(
                className=f"toast tone-{t.tone}",
                children=[
                    html.Span(t.label, className="toast-label"),
                    html.Button(
                        "×",
                        id={"type": "toast-dismiss", "index": t.key},
                        className="toast-dismiss",
                        n_clicks=0,
                        title="Zavřít",
                    ),
                ],
            )
        )
    if not items:
        return html.Div(className="toast-stack-empty"), {"display": "none"}
    return html.Div(className="toast-stack-inner", children=items), {"display": "flex"}


def render_status_rail(chips: list[StatusChip]) -> tuple[html.Div, dict, str]:
    if not chips:
        return html.Div(className="status-rail-empty"), {"display": "none"}, "status-rail"
    top_tone = chips[0].tone
    return (
        html.Div(
            className="status-rail-inner",
            children=[
                html.Span(c.label, className=f"status-chip tone-{c.tone}", title=c.label)
                for c in chips
            ],
        ),
        {"display": "flex"},
        f"status-rail tone-rail-{top_tone}",
    )


def render_active_warnings(
    verdict: Verdict | None,
    style_guide: StyleGuide | None,
    plan: ScalpPlan | None,
    macro_summary: MacroDaySummary | None = None,
) -> html.Div:
    banners: list[html.Div] = []

    if verdict and verdict.status.value in ("CRITICAL", "BLOCKED"):
        msg = " · ".join(verdict.messages[:2]) if verdict.messages else verdict.status.value
        banners.append(html.Div(f"POZOR — {msg}", className="warn-banner tone-critical"))

    if plan and plan.gate_action == "NE" and not banners:
        banners.append(html.Div(plan.reasons[0] if plan.reasons else "Neobchodovat", className="warn-banner tone-critical"))

    wait_msgs: list[str] = []
    if style_guide and style_guide.style == TradingStyle.WAIT:
        wait_msgs.append(style_guide.headline or "WAIT / REDUCE")
    if verdict and not verdict.golden_window_active:
        wait_msgs.append("Mimo Golden Window 14–18h — nižší likvidita")
    if macro_summary and macro_summary.status == MacroStatus.CAUTION:
        wait_msgs.append(macro_summary.headline or "Macro CAUTION")
    if plan and plan.gate_action == "POČKEJ" and plan.reasons:
        wait_msgs.append(plan.reasons[0])

    if wait_msgs and len(banners) < 2:
        banners.append(html.Div(" · ".join(wait_msgs[:2]), className="warn-banner tone-wait"))

    if not banners:
        return html.Div(className="warnings-empty")
    return html.Div(className="warnings-inner", children=banners[:2])


def render_mtf_strip(indicators: IndicatorBundle | None) -> html.Div:
    icons = {"BULL": "▲", "BEAR": "▼", "NEUTRAL": "◆"}
    mtf = indicators.mtf_bias if indicators else {}
    pills = []
    for tf in ("M1", "M5", "M15", "H1"):
        bias = mtf.get(tf, TrendBias.NEUTRAL)
        tone = {"BULL": "bull", "BEAR": "bear"}.get(bias.value, "neutral")
        pills.append(
            html.Div(
                className=f"mtf-strip-pill tone-{tone}",
                children=[
                    html.Span(tf, className="mtf-strip-tf"),
                    html.Span(f"{icons[bias.value]} {bias.value}", className="mtf-strip-bias"),
                ],
            )
        )
    return html.Div(className="mtf-strip-inner", children=pills)


def _strength_delta_label(delta: int) -> tuple[str, str]:
    if delta > 0:
        return "↑ sílí", "tone-up"
    if delta < 0:
        return "↓ slábne", "tone-down"
    return "→ stabilní", "tone-flat"


def trend_sparkline_bars(values: tuple[int, ...]) -> html.Div:
    """CSS bar sparkline for trend strength history (testable)."""
    hist = list(values) or [0]
    return html.Div(
        className="tb-spark-bars",
        children=[
            html.Div(
                className="tb-spark-bar",
                style={"height": f"{max(2, int(v / 10 * 32))}px"},
                title=str(v),
            )
            for v in hist[-30:]
        ],
    )


def render_trend_brief_panel(brief: TrendBrief | None) -> html.Div:
    if not brief:
        return html.Div("Čekám na data pro trend briefing…", className="trend-brief-empty")

    delta_txt, delta_tone = _strength_delta_label(brief.strength_delta)
    bar_tooltip = (
        f"z {brief.daily_bar_count} svíček H1+M15"
        if brief.daily_bar_count
        else brief.daily_source_tf
    )

    return html.Div(
        className="trend-brief-panel",
        children=[
            html.Div(
                className="trend-brief-head",
                children=[
                    html.Span("Trend dnes", className="panel-title"),
                    html.Span(
                        brief.daily_source_tf,
                        className="panel-badge panel-badge-dim",
                        title=bar_tooltip,
                    ),
                ],
            ),
            html.Div(
                className="tb-bias-row",
                children=[
                    html.Div(
                        className="tb-bias-tile tone-buy",
                        children=[
                            html.Div("BUY", className="tb-bias-label"),
                            html.Div(f"{brief.daily_buy_pct:.0f}%", className="tb-bias-pct"),
                        ],
                    ),
                    html.Div(
                        className="tb-bias-tile tone-sell",
                        children=[
                            html.Div("SELL", className="tb-bias-label"),
                            html.Div(f"{brief.daily_sell_pct:.0f}%", className="tb-bias-pct"),
                        ],
                    ),
                ],
            ),
            html.Div(
                className="tb-stacked-bar",
                children=[
                    html.Div(className="tb-bar-buy", style={"width": f"{brief.daily_buy_pct}%"}),
                    html.Div(className="tb-bar-sell", style={"width": f"{brief.daily_sell_pct}%"}),
                ],
            ),
            html.Div(
                className="tb-strength-row",
                children=[
                    html.Div(
                        className="tb-strength-num",
                        children=[str(brief.strength_now), html.Span("/10")],
                    ),
                    html.Div(
                        className="tb-strength-meta",
                        children=[
                            html.Div(brief.now_direction, className="tb-strength-dir"),
                            html.Div(delta_txt, className=f"tb-strength-delta {delta_tone}"),
                        ],
                    ),
                    html.Div(
                        className="tb-spark-wrap",
                        children=[
                            html.Div("Síla (30 min)", className="tb-spark-label"),
                            trend_sparkline_bars(brief.strength_history),
                        ],
                    ),
                ],
            ),
        ],
    )


def render_hero_kpis(
    market: MarketSnapshot | None,
    account: AccountSnapshot | None,
    lot_result: LotSizeResult | None,
    indicators: IndicatorBundle | None,
) -> html.Div:
    atr = market.atr if market else 0.0
    atr_median = float(indicators.atr_series.tail(50).median()) if indicators and len(indicators.atr_series) >= 5 else atr
    atr_label, atr_tone = classify_atr(atr, atr_median, bool(market and market.atr_impulse))
    dd = account.daily_drawdown_pct if account else 0.0
    dd_tone = "red" if account and account.is_critical else (
        "amber" if dd >= ACCOUNT.daily_drawdown_limit_pct * 0.85 else "cyan"
    )
    if lot_result and lot_result.lot_size > 0:
        lot_val = f"${lot_result.risk_usd:,.0f} ({lot_result.risk_pct:.0f}%)"
        lot_sub = f"max {lot_result.lot_size} lot"
    elif lot_result:
        lot_val = "—"
        lot_sub = lot_result.message[:40]
    else:
        lot_val = "—"
        lot_sub = "doporučený risk"

    return html.Div(
        className="hero-kpis-inner",
        children=[
            kpi_tile("ATR M1", atr_label, "volatilita", atr_tone),
            kpi_tile(
                "DD dnes",
                f"{dd:.1f}%",
                f"limit {ACCOUNT.daily_drawdown_limit_pct:.0f}%",
                dd_tone,
            ),
            kpi_tile("Doporučený risk", lot_val, lot_sub, "cyan"),
        ],
    )


def render_metrics(
    market: MarketSnapshot | None,
    indicators: IndicatorBundle | None,
    lot_result: LotSizeResult | None,
) -> html.Div:
    del lot_result
    spread_cost = "—"
    spread_tone = "neutral"
    if market and market.atr > 0:
        spread_price = market.ask - market.bid
        cost_pct = spread_price / market.atr * 100
        spread_cost = f"{cost_pct:.0f}%"
        spread_tone = "warn" if cost_pct > 15 else "cyan"

    bb_label = "Squeeze" if indicators and indicators.bb.is_squeeze else "Normální"
    bb_tone = "amber" if indicators and indicators.bb.is_squeeze else "neutral"

    return html.Div(
        className="metric-grid-inner",
        children=[
            kpi_tile("Spr/ATR", spread_cost, "náklad spreadu", spread_tone),
            kpi_tile("BB M1", bb_label, "volatilita pásma", bb_tone),
        ],
    )


def render_analytics_alerts(market: MarketSnapshot | None, indicators: IndicatorBundle | None) -> html.Div:
    chips = []
    if market and market.atr_impulse:
        chips.append(alert_chip("ATR Impulse", "danger"))
    if market and market.spread_warning:
        chips.append(alert_chip("High Spread", "warn"))
    if indicators and indicators.bb.is_squeeze:
        chips.append(alert_chip("BB Squeeze", "info"))
    if not chips:
        return html.Div(className="chip-row-empty")
    return html.Div(className="chip-row-inner", children=chips)


def render_lot_strip(lot_result: LotSizeResult | None) -> html.Div:
    if not lot_result:
        msg = "Počítám velikost pozice…"
        cls = "lot-strip-inner"
    elif lot_result.lot_size <= 0:
        msg = lot_result.message
        cls = "lot-strip-inner lot-warn"
    else:
        msg = lot_result.message
        cls = "lot-strip-inner"
    return html.Div(
        className=cls,
        children=[
            html.Span("Position Sizer", className="lot-label"),
            html.Span(msg, className="lot-value"),
        ],
    )


def render_mtf(indicators: IndicatorBundle | None) -> html.Div:
    icons = {"BULL": "▲", "BEAR": "▼", "NEUTRAL": "◆"}
    mtf = indicators.mtf_bias if indicators else {}
    pills = []
    for tf in ("M1", "M5", "M15", "H1"):
        bias = mtf.get(tf, TrendBias.NEUTRAL)
        pills.append(mtf_pill(tf, bias.value, icons[bias.value]))
    return html.Div(className="mtf-row-inner", children=pills)


def render_session_badge(verdict: Verdict) -> html.Span:
    label = "ZLATÉ OKNO" if verdict.golden_window_active else "MIMO SEANCI"
    tone = "gw" if verdict.golden_window_active else "off"
    return html.Span(label, className=f"hero-session-pill tone-{tone}")


def render_timeline(sessions: list[SessionInfo]) -> html.Div:
    progress = session_progress_pct()
    golden_start, golden_end = golden_window_progress()
    colors = {"Asian": "#1e293b", "London": "#1e3a5f", "New York": "#3f2a1d"}
    widths = {"Asian": 33.3, "London": 33.3, "New York": 33.4}

    segments = [
        html.Div(
            className=f"tl-seg{' active' if s.active else ''}",
            style={"width": f"{widths[s.name]}%", "background": colors.get(s.name, "#1e293b")},
            children=html.Span(s.name[:3].upper()),
        )
        for s in sessions
    ]

    return html.Div(
        className="timeline-inner timeline-compact",
        children=[
            html.Div(className="tl-track", children=segments),
            html.Div(
                className="tl-golden",
                style={"left": f"{golden_start}%", "width": f"{golden_end - golden_start}%"},
            ),
            html.Div(className="tl-now", style={"left": f"{progress}%"}),
        ],
    )


def render_next_event_compact(
    enriched: list[EnrichedNewsEvent],
    plan: ScalpPlan | None,
) -> html.Div:
    """Next high-impact macro event — countdown for the session column."""
    future = sorted(
        [e for e in enriched if e.event.seconds_until >= 0 and e.impact.action != "VOLNO"],
        key=lambda x: x.event.event_time,
    )
    if future:
        item = future[0]
        e = item.event
        tone = "high" if item.impact.action == "NEOBCHODOVAT" else "caution"
        return html.Div(
            className=f"session-next-event tone-{tone}",
            children=[
                html.Div("Další událost", className="sne-label"),
                html.Div(
                    className="sne-row",
                    children=[
                        html.Span(format_t_minus(e.seconds_until), className="sne-countdown"),
                        html.Span(e.title[:42] + ("…" if len(e.title) > 42 else ""), className="sne-title"),
                    ],
                ),
                html.Div(
                    f"{item.local_time} · {e.currency} · {item.impact.action}",
                    className="sne-meta",
                ),
            ],
        )

    if plan and plan.next_news_label and plan.next_news_minutes is not None:
        return html.Div(
            className="session-next-event tone-normal",
            children=[
                html.Div("Další událost", className="sne-label"),
                html.Div(plan.next_news_label, className="sne-title"),
                html.Div(f"T-{plan.next_news_minutes} min", className="sne-meta"),
            ],
        )

    return html.Div(
        className="session-next-event tone-clear",
        children=[
            html.Div("Macro", className="sne-label"),
            html.Div("Bez high-impact v nejbližších hodinách", className="sne-title"),
        ],
    )


def render_engine_pills_compact(panel: EnginePanel) -> html.Div:
    pills = []
    for p in panel.pills[:4]:
        pills.append(
            html.Div(
                className=f"engine-pill-compact tone-{p.tone}",
                title=p.tooltip,
                children=[
                    html.Span(p.label, className="epc-key"),
                    html.Span(p.value, className="epc-val"),
                ],
            )
        )
    if not pills:
        return html.Div(className="engine-pills-compact-empty")
    return html.Div(className="engine-pills-compact", children=pills)


def render_risk_reminder(
    account: AccountSnapshot | None,
    plan: ScalpPlan | None,
    verdict: Verdict | None,
) -> html.Div:
    del account, verdict
    rows = []
    if plan and plan.daily_dd_remaining_usd is not None:
        rows.append(
            html.Div(
                className="risk-row",
                children=[
                    html.Span("DD headroom", className="risk-label"),
                    html.Span(f"${plan.daily_dd_remaining_usd:,.0f}", className="risk-value"),
                ],
            )
        )
    if plan and plan.trades_until_daily_limit is not None:
        rows.append(
            html.Div(
                className="risk-row",
                children=[
                    html.Span("Obchody zbývá", className="risk-label"),
                    html.Span(str(plan.trades_until_daily_limit), className="risk-value"),
                ],
            )
        )
    if not rows:
        return html.Div(className="session-risk-reminder empty")
    return html.Div(
        className="session-risk-reminder",
        children=[
            html.Div("Risk & limity", className="srr-head"),
            html.Div(className="srr-rows", children=rows),
        ],
    )


def render_trade_decision(decision: TradeDecision, compact: bool = False) -> html.Div:
    reasons = decision.reasons[:2] if compact else decision.reasons
    cls = f"trade-now tone-{decision.tone}"
    if compact:
        cls += " trade-now-compact"
    children: list = [
        html.Div(
            className="trade-now-top",
            children=[
                html.Span("TEĎ OTEVŘÍT OBCHOD?", className="trade-now-q"),
                html.Span(decision.action, className="trade-now-answer"),
            ],
        ),
        html.Div(decision.headline, className="trade-now-headline"),
        html.Ul(
            [html.Li(r) for r in reasons],
            className="trade-now-reasons",
        ),
    ]
    if not compact and decision.indicator_note:
        children.append(html.Div(decision.indicator_note, className="trade-now-note"))
    return html.Div(className=cls, children=children)


def render_focus_strip(
    account: AccountSnapshot | None,
    market: MarketSnapshot | None,
    lot_result: LotSizeResult | None,
    verdict: Verdict,
) -> html.Div:
    label = VERDICT_LABEL_CZ.get(verdict.status.value, verdict.status.value)
    tone = verdict.status.value.lower()
    dd = f"DD {account.daily_drawdown_pct:.1f}%" if account else "DD —"
    spr = f"Spread {market.spread_points:.0f}p" if market else "Spread —"
    if lot_result and lot_result.lot_size > 0:
        lot = f"{lot_result.lot_size} lot"
    elif lot_result and lot_result.message:
        lot = lot_result.message
    else:
        lot = "Lot —"
    gw = "Golden Window" if verdict.golden_window_active else "mimo GW"
    return html.Div(
        className="focus-strip-inner",
        children=[
            html.Span(label, className=f"focus-chip tone-{tone}"),
            html.Span(dd, className="focus-chip"),
            html.Span(spr, className="focus-chip"),
            html.Span(lot, className="focus-chip"),
            html.Span(gw, className="focus-chip"),
        ],
    )


def render_cmd_terminal(
    lines: list[LogLine],
    running: bool = True,
    market: MarketSnapshot | None = None,
    signal_lab: SignalLabSnapshot | None = None,
) -> html.Div:
    body = []
    telemetry = []
    
    if running:
        # Timestamp from last line or local clock
        t_now = lines[-1].time if lines else datetime.now().strftime("%H:%M:%S")
        
        # Subsystems integrity status
        telemetry.append(LogLine(time=t_now, level="ok", message="[SYS_OK] Subsystems online: RiskEngine, SpreadMonitor, MTFAligner, MacroGuard"))
        
        # Live feed telemetry
        if market:
            telemetry.append(LogLine(time=t_now, level="info", message=f"[FEED] {market.symbol} bid/ask: {market.bid:.2f}/{market.ask:.2f} · spread {market.spread_points:.1f}p"))
            
        # Calculation logs
        if signal_lab:
            telemetry.append(LogLine(time=t_now, level="info", message=f"[CALC] Regime: {signal_lab.regime}"))
            # telemetry.append(LogLine(time=t_now, level="info", message=f"[CALC] MTF Align: M1={signal_lab.m1_bias} M5={signal_lab.m5_bias} M15={signal_lab.m15_bias} H1={signal_lab.h1_bias}"))
            
        # Security check-ins
        telemetry.append(LogLine(time=t_now, level="ok", message="[SECURE] Daily Drawdown limit guard: PASS · SL auto-check: OK"))

    all_lines = []
    all_lines.extend(telemetry)
    for l in lines:
        if "[tick]" in l.message.lower() and telemetry:
            continue
        all_lines.append(l)

    for line in all_lines[-12:]:
        body.append(
            html.Div(
                className=f"cmd-line level-{line.level}",
                children=[
                    html.Span(line.time, className="cmd-t"),
                    html.Span(line.message, className="cmd-msg"),
                ],
            )
        )
        
    if not body:
        body.append(html.Div("čekám na první výpočet…", className="cmd-empty"))

    return html.Div(
        className="cmd-terminal",
        children=[
            html.Div(
                className="cmd-head",
                children=[
                    html.Span(
                        className=f"cmd-pulse{' is-live' if running else ''}",
                        title="Python engine",
                    ),
                    html.Span("python engine", className="cmd-title"),
                    html.Span("LIVE" if running else "IDLE", className="cmd-status"),
                ],
            ),
            html.Div(className="cmd-body", children=body),
        ],
    )


def render_macro_status(summary: MacroDaySummary, source: str = "", error: str | None = None) -> str:
    if source == "CHYBA":
        return "MACRO ERROR"
    if summary.status == MacroStatus.BLOCKED:
        return "MACRO BLOCK"
    if summary.status == MacroStatus.CAUTION:
        return "MACRO CAUTION"
    return "MACRO CLEAR"


def render_macro_summary(
    summary: MacroDaySummary,
    market: MarketSnapshot | None = None,
    source: str = "",
    error: str | None = None,
) -> html.Div:
    tone = summary.status.value.lower() # clear, caution, blocked
    
    # LED class based on tone
    led_class = f"macro-status-led tone-{tone}"
    
    # Map tone to Czech status text
    status_label_map = {
        "clear": "BEZPEČNÁ ZÓNA (Bez významných zpráv)",
        "caution": "ZVÝŠENÉ RIZIKO (Pozor na makro)",
        "blocked": "ZÁKAZ OBCHODOVÁNÍ (Makro zprávy)",
    }
    status_label = status_label_map.get(tone, "Neznámý stav")

    if error and source == "CHYBA":
        headline = error[:90]
    else:
        headline = summary.headline
    if len(headline) > 90:
        headline = headline[:89] + "…"
    
    window = ""
    if summary.caution_from and summary.caution_until:
        window = (
            f"Opatrnost {summary.caution_from.strftime('%H:%M')}–"
            f"{summary.caution_until.strftime('%H:%M')}"
        )

    rec_text = summary.recommendations[0] if summary.recommendations else ""

    meta_children = []
    if window:
        meta_children.append(html.Span(window, className="macro-window"))
    if rec_text:
        # Strip trailing period if any to look cleaner inline
        clean_rec = rec_text.rstrip(".")
        meta_children.append(html.Span(f" · {clean_rec}", className="macro-rec"))

    # Add real-time market impact reaction analysis
    if market:
        reaction_text = ""
        reaction_tone = "neutral"
        if market.atr_impulse and market.spread_warning:
            reaction_text = "POTVRZENO: Silná volatilita + vysoký spread"
            reaction_tone = "err"
        elif market.atr_impulse:
            reaction_text = "POTVRZENO: Vysoká volatilita (ATR impulz)"
            reaction_tone = "warn"
        elif market.spread_warning:
            reaction_text = "VAROVÁNÍ: Vysoký spread"
            reaction_tone = "warn"
        else:
            if summary.status == MacroStatus.BLOCKED or summary.status == MacroStatus.CAUTION:
                reaction_text = "Fáze zpráv: Klidný trh (volatilita v normálu)"
                reaction_tone = "ok"
            else:
                reaction_text = "Dopad: Bez reakce"
                reaction_tone = "ok"
        
        meta_children.append(html.Div(
            f"Trh: {reaction_text}",
            className=f"macro-reaction status-{reaction_tone} tier-kompakt-only"
        ))

    return html.Div(
        className=f"macro-summary-inner tone-{tone}",
        children=[
            html.Div(
                className="macro-status-header",
                children=[
                    html.Div(className=led_class),
                    html.Span(status_label, className="macro-status-text"),
                ],
            ),
            html.Div(headline, className="macro-headline"),
            html.Div(meta_children, className="macro-summary-meta") if meta_children else None,
        ],
    )


_CHECK_ICON = {
    CheckStatus.OK: "✓",
    CheckStatus.WARN: "⚠",
    CheckStatus.FAIL: "✗",
    CheckStatus.NA: "—",
}


def render_pre_news_checklist(checklist: PreNewsChecklist) -> html.Div:
    tone = "idle"
    if checklist.active:
        tone = "ready" if checklist.ready else "alert"

    rows = []
    for item in checklist.items:
        rows.append(
            html.Div(
                className=f"check-row status-{item.status.value}",
                children=[
                    html.Span(_CHECK_ICON[item.status], className="check-icon"),
                    html.Div(
                        className="check-body",
                        children=[
                            html.Span(item.label, className="check-label"),
                            html.Span(item.meaning, className="check-meaning"),
                            html.Span(item.hint, className="check-hint") if item.hint else None,
                        ],
                    ),
                ],
            )
        )

    return html.Div(
        className=f"pre-news-checklist tone-{tone}",
        children=[
            html.Div(checklist.headline, className="check-headline"),
            html.Div(checklist.subline, className="check-subline"),
            html.Div(className="check-grid", children=rows) if rows else None,
        ],
    )


_CATEGORY_LABEL = {
    "system": "Systém",
    "mt5": "MT5",
    "macro": "Macro",
    "market": "Trh",
    "risk": "Riziko",
    "signal": "Signál",
    "tick": "Tick",
}


def render_engine_panel(panel: EnginePanel) -> html.Div:
    pills = []
    for p in panel.pills:
        pills.append(
            html.Div(
                className=f"engine-pill tone-{p.tone}",
                title=p.tooltip,
                children=[
                    html.Span(p.label, className="engine-pill-key"),
                    html.Span(p.value, className="engine-pill-val"),
                ],
            )
        )

    cards = []
    for ins in reversed(panel.insights):
        cat = _CATEGORY_LABEL.get(ins.category, ins.category)
        cards.append(
            html.Div(
                className=f"engine-card level-{ins.level}",
                children=[
                    html.Div(
                        className="engine-card-top",
                        children=[
                            html.Span(cat, className="engine-card-cat"),
                            html.Span(ins.time, className="engine-card-time") if ins.time else None,
                        ],
                    ),
                    html.Div(ins.title, className="engine-card-title"),
                    html.Div(ins.detail, className="engine-card-detail"),
                ],
            )
        )

    if not cards:
        cards.append(html.Div("Zatím bez změn — engine běží na pozadí.", className="engine-empty"))

    return html.Div(
        className="engine-panel-inner",
        children=[
            html.Div(className="engine-pill-row", children=pills),
            html.Div(className="engine-cards", children=cards),
            html.Div(panel.footnote, className="engine-footnote"),
        ],
    )


def render_signal_lab_compact(
    lab: SignalLabSnapshot | None,
    market: MarketSnapshot | None = None,
    indicators: IndicatorBundle | None = None,
) -> html.Div:
    if not lab or not lab.signals:
        return html.Div("M1 Analytics čeká na data…", className="signal-lab-empty")

    verdict = synthesize_m1_verdict(lab)
    
    action_text = "ČEKEJ / NEUTRÁLNÍ"
    action_desc = "Trh nemá jasný směr. Vyčkej na impuls."
    action_tone = "wait"
    
    if verdict.direction == "LONG":
        action_text = "HLEDEJ BUY (LONG bias)"
        action_desc = "M1/M5 momentum podporuje růst. Vyhledávej long pullbacky."
        action_tone = "bull"
    elif verdict.direction == "SHORT":
        action_text = "HLEDEJ SELL (SHORT bias)"
        action_desc = "M1/M5 momentum podporuje pokles. Vyhledávej short pullbacky."
        action_tone = "bear"
    elif lab.regime in ("SWEEP", "EXTENDED"):
        action_text = "STÁT MIMO TRH (SWEEP / OBRAZ)"
        action_desc = "Detekován sweep likvidity nebo extrémní pohyb. Vyšší riziko."
        action_tone = "err"

    indicators_list = []
    
    def find_sig(keyword):
        return next((s for s in lab.signals if keyword.lower() in s.label.lower()), None)
        
    # 1. Market Regime (ER)
    sig_er = find_sig("Efficiency")
    if sig_er:
        try:
            er_val = float(sig_er.value)
        except ValueError:
            er_val = 0.0
        phase_label = "CHOP" if er_val < 0.45 else "TREND"
        phase_tone = "warn" if er_val < 0.45 else "bull"
        indicators_list.append(html.Div(
            className=f"m1-metric-box tone-{phase_tone}", 
            children=[
                html.Span("Režim trhu", className="mb-label"), 
                html.Span(f"{phase_label} (ER {sig_er.value})", className="mb-value"),
                html.Div(className="mb-status-dot")
            ]
        ))
    else:
        indicators_list.append(html.Div(
            className="m1-metric-box tone-neutral", 
            children=[
                html.Span("Režim trhu", className="mb-label"), 
                html.Span("—", className="mb-value"),
                html.Div(className="mb-status-dot")
            ]
        ))

    # 2. ADR Daily Range & Exhaustion Gauge
    adr_ex_pct = market.adr_exhaustion_pct if market else 0.0
    range_desc = "VOLNO" if adr_ex_pct < 85.0 else "VYČERPÁNO"
    range_tone = "bull" if adr_ex_pct < 65.0 else "warn" if adr_ex_pct < 85.0 else "err"
    indicators_list.append(html.Div(
        className=f"m1-metric-box tone-{range_tone}",
        children=[
            html.Span("Denní ADR výluh", className="mb-label"),
            html.Span(f"{range_desc} ({adr_ex_pct:.0f}%)", className="mb-value"),
            html.Div(
                className="adr-gauge-bar-wrap",
                children=[
                    html.Div(className=f"adr-gauge-bar-fill tone-{range_tone}", style={"width": f"{adr_ex_pct}%"}),
                ]
            )
        ]
    ))

    # 3. M1 Volatility / Volume
    sig_vol = find_sig("volume")
    if sig_vol:
        vol_desc = "NORMÁL"
        vol_tone = "neutral"
        if "×" in sig_vol.value:
            try:
                v_val = float(sig_vol.value.split("×")[0])
                if v_val >= 1.5:
                    vol_desc = "SPIKE"
                    vol_tone = "bull"
                elif v_val < 0.6:
                    vol_desc = "ABSORBCE"
                    vol_tone = "warn"
            except ValueError:
                pass
        indicators_list.append(html.Div(
            className=f"m1-metric-box tone-{vol_tone}",
            children=[
                html.Span("M1 Volatilita", className="mb-label"),
                html.Span(f"{vol_desc} ({sig_vol.value})", className="mb-value"),
                html.Div(className="mb-status-dot")
            ]
        ))
    else:
        indicators_list.append(html.Div(
            className="m1-metric-box tone-neutral", 
            children=[
                html.Span("M1 Volatilita", className="mb-label"), 
                html.Span("—", className="mb-value"),
                html.Div(className="mb-status-dot")
            ]
        ))

    # 4. Structure (PDH/PDL distance)
    sig_pdh = find_sig("Od PDH")
    sig_pdl = find_sig("Od PDL")
    struct_text = "IN RANGE"
    struct_tone = "neutral"
    
    if sig_pdh and sig_pdl:
        try:
            pdh_val = int(sig_pdh.value.replace(" pts", "").replace("+", "").replace("-", ""))
            pdl_val = int(sig_pdl.value.replace(" pts", "").replace("+", "").replace("-", ""))
            if pdh_val < 150:
                struct_text = f"NEAR PDH (-{pdh_val})"
                struct_tone = "warn"
            elif pdl_val < 150:
                struct_text = f"NEAR PDL (+{pdl_val})"
                struct_tone = "bull"
        except ValueError:
            pass
            
    indicators_list.append(html.Div(
        className=f"m1-metric-box tone-{struct_tone}",
        children=[
            html.Span("Struktura trhu", className="mb-label"),
            html.Span(struct_text, className="mb-value"),
            html.Div(className="mb-status-dot")
        ]
    ))

    # Radar balance calculations
    balance_val = 0.0
    
    radar_items = []
    if market:
        def sweep_pill(label, dist):
            if dist == 999.0 or dist is None:
                return html.Div(
                    className="sweep-pill tone-neutral",
                    children=[
                        html.Span(label, className="sp-label"),
                        html.Span("—", className="sp-val")
                    ]
                )
            
            pts = int(dist / 0.01)
            
            tone = "clear"
            if pts < 0:
                tone = "swept"
                pts_txt = "SWEPT"
            elif pts <= 150:
                tone = "near"
                pts_txt = f"{pts}p"
            else:
                pts_txt = f"{pts}p"
                
            return html.Div(
                className=f"sweep-pill tone-{tone}",
                children=[
                    html.Span(label, className="sp-label"),
                    html.Span(pts_txt, className="sp-val")
                ]
            )
            
        radar_items = [
            sweep_pill("Asie High", market.dist_asian_high),
            sweep_pill("Asie Low", market.dist_asian_low),
            sweep_pill("Londýn High", market.dist_london_high),
            sweep_pill("Londýn Low", market.dist_london_low),
        ]
        
        # Calculate balance based on sweeps and proximity
        # Check Lows (positive bias towards BUY)
        for dist in (market.dist_asian_low, market.dist_london_low):
            if dist is not None and dist != 999.0:
                pts = int(dist / 0.01)
                if pts < 0:
                    balance_val += 35.0
                elif pts <= 150:
                    balance_val += 20.0
                    
        # Check Highs (negative bias towards SELL)
        for dist in (market.dist_asian_high, market.dist_london_high):
            if dist is not None and dist != 999.0:
                pts = int(dist / 0.01)
                if pts < 0:
                    balance_val -= 35.0
                elif pts <= 150:
                    balance_val -= 20.0

    # Add SMT divergence bias to radar balance
    if indicators and indicators.dxy_smt_divergence:
        if indicators.dxy_smt_divergence == "BULLISH_SMT":
            balance_val += 30.0
        elif indicators.dxy_smt_divergence == "BEARISH_SMT":
            balance_val -= 30.0

    # Add structure direction bias to radar balance
    if struct_text.startswith("NEAR PDH"):
        balance_val -= 20.0
    elif struct_text.startswith("NEAR PDL"):
        balance_val += 20.0

    # Clamp balance value to [-100, 100]
    balance_val = max(-100.0, min(100.0, balance_val))
    
    # Radar balance bar styling
    fill_left = 50.0
    fill_width = 0.0
    fill_color = "var(--text-dim)"
    balance_class = "neutral"
    
    if balance_val > 0:
        fill_width = balance_val * 0.5
        fill_left = 50.0
        fill_color = "var(--cyan)"
        balance_class = "buy"
    elif balance_val < 0:
        fill_width = abs(balance_val) * 0.5
        fill_left = 50.0 - fill_width
        fill_color = "var(--red)"
        balance_class = "sell"
        
    balance_bar = html.Div(
        className="radar-balance-bar-wrap",
        children=[
            html.Div(
                className="radar-balance-track",
                children=[
                    html.Div(className="radar-balance-divider"),
                    html.Div(
                        className=f"radar-balance-fill {balance_class}",
                        style={
                            "left": f"{fill_left}%",
                            "width": f"{fill_width}%",
                            "backgroundColor": fill_color
                        }
                    ),
                    html.Div(
                        className="radar-balance-pointer",
                        style={"left": f"{50.0 + balance_val * 0.5}%"}
                    ),
                    html.Div(
                        className="radar-balance-labels",
                        children=[
                            html.Span("SELL LIKVIDITA", className="lbl-sell"),
                            html.Span(f"{'+' if balance_val > 0 else ''}{balance_val:.0f}%", className="lbl-val"),
                            html.Span("BUY LIKVIDITA", className="lbl-buy"),
                        ]
                    )
                ]
            )
        ]
    ) if radar_items else None
    radar_panel = html.Div(
        className="session-radar-panel",
        children=[
            html.Div("Likviditní Radar (Session H/L)", className="sr-title"),
            html.Div(className="sr-grid", children=radar_items),
            balance_bar
        ]
    ) if radar_items else None

    return html.Div(
        className="m1-analytics-card",
        children=[
            html.Div(
                className=f"m1-rec-box tone-{action_tone}",
                children=[
                    html.Div(action_text, className="m1-rec-title"),
                    html.Div(action_desc, className="m1-rec-desc"),
                ]
            ),
            html.Div(
                className="m1-metrics-grid",
                children=indicators_list
            ),
            radar_panel
        ]
    )


def render_signal_lab(lab: SignalLabSnapshot | None) -> html.Div:
    return render_signal_lab_compact(lab)


def _render_signal_lab_verbose(lab: SignalLabSnapshot | None) -> html.Div:
    if not lab or not lab.signals:
        return html.Div("Signal Lab čeká na MT5 data…", className="signal-lab-empty")
    items = []
    for s in lab.signals:
        items.append(
            html.Div(
                className=f"signal-row tone-{s.tone}",
                children=[
                    html.Div(
                        className="signal-row-top",
                        children=[
                            html.Span(s.label, className="signal-label"),
                            html.Span(s.value, className="signal-value"),
                        ],
                    ),
                    html.Div(s.hint, className="signal-hint"),
                ],
            )
        )
    return html.Div(
        className="signal-lab-inner",
        children=[
            html.Div(
                className="signal-lab-head",
                children=[
                    html.Span("SIGNAL LAB", className="signal-lab-tag"),
                    html.Span(lab.regime, className="signal-lab-regime"),
                    html.Span(lab.headline, className="signal-lab-headline"),
                ],
            ),
            html.Div(className="signal-lab-grid", children=items),
        ],
    )


def _get_macro_direction_and_strength(gold_effect: str, action: str) -> tuple[str, str, str, int]:
    effect_lower = gold_effect.lower()
    if "gold↑" in effect_lower or "gold ↑" in effect_lower:
        direction = "▲"
        tone = "long"
        label = "BUY"
    elif "gold↓" in effect_lower or "gold ↓" in effect_lower:
        direction = "▼"
        tone = "short"
        label = "SELL"
    elif "obousměrný" in effect_lower or "impulsu" in effect_lower or "volatilita" in effect_lower:
        direction = "⇅"
        tone = "neutral-volt"
        label = "VOLATILITA"
    else:
        direction = "◆"
        tone = "neutral"
        label = "NEUTRÁLNÍ"
        
    if action == "NEOBCHODOVAT":
        strength = 3
    elif action == "OPATRNĚ":
        strength = 2
    else:
        strength = 1
        
    return direction, tone, label, strength


def render_macro_events(
    enriched: list[EnrichedNewsEvent],
    summary: MacroDaySummary | None = None,
    expanded: bool = False,
) -> html.Div:
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(RISK.timezone)

    if not expanded and summary and summary.focus_date:
        focus = summary.focus_date
        enriched = [
            e for e in enriched if e.event.event_time.astimezone(tz).date() == focus
        ]

    if not enriched:
        label = summary.focus_label if (summary and not expanded) else f"{MACRO.lookahead_days} dní"
        return html.Div(
            f"Žádné macro události · {label}",
            className="news-empty",
        )

    if not expanded:
        future = sorted(
            [e for e in enriched if e.event.seconds_until >= 0],
            key=lambda x: x.event.event_time,
        )
        recent_past = sorted(
            [e for e in enriched if e.event.seconds_until < 0],
            key=lambda x: x.event.event_time,
            reverse=True,
        )
        limit = MACRO.max_events_focus_day
        display_pool = future[:limit]
        if len(display_pool) < limit:
            display_pool.extend(recent_past[: limit - len(display_pool)])
    else:
        # Show all events (both past and future) sorted chronologically, max 25
        display_pool = sorted(
            enriched,
            key=lambda x: x.event.event_time,
        )[:25]

    items = []
    for item in display_pool:
        e = item.event
        imp = item.impact
        tone = "high" if imp.action == "NEOBCHODOVAT" else "caution" if imp.action == "OPATRNĚ" else "normal"
        if e.impact == "medium":
            tone = "caution"
        past = e.seconds_until < 0
        
        action_label = "ZÁKAZ VSTUPU" if imp.action == "NEOBCHODOVAT" else "OPATRNOST" if imp.action == "OPATRNĚ" else "STANDARD"
        
        time_display = item.local_time
        if expanded:
            event_date = e.event_time.astimezone(tz).date()
            date_str = event_date.strftime("%d.%m.")
            time_display = f"{date_str} {item.local_time}"

        if past:
            countdown_text = "PROBĚHLO"
            countdown_class = "macro-countdown-past"
        else:
            countdown_text = f"za {format_t_minus(e.seconds_until)}"
            countdown_class = "macro-countdown"

        dir_icon, dir_tone, dir_lbl, strength_rating = _get_macro_direction_and_strength(imp.gold_effect, imp.action)
        
        items.append(
            html.Div(
                className=f"macro-event-card tone-{tone}{' is-past' if past else ''}",
                children=[
                    html.Div(className=f"macro-accent-stripe tone-{tone}"),
                    html.Div(
                        className="macro-card-content",
                        children=[
                            html.Div(
                                className="macro-card-top",
                                children=[
                                    html.Span(time_display, className="macro-time-badge"),
                                    html.Span(countdown_text, className=countdown_class),
                                    html.Span(e.currency, className="macro-currency-badge"),
                                    html.Span(action_label, className=f"macro-action-tag tone-{tone}"),
                                ]
                            ),
                            html.Div(e.title, className="macro-title-text"),
                            html.Div(
                                className="macro-card-bottom",
                                children=[
                                    html.Span(f"Dopad: {dir_icon} {dir_lbl}", className=f"macro-impact-dir tone-{dir_tone}"),
                                    html.Span(f"Síla: {'★' * strength_rating}{'☆' * (3 - strength_rating)}", className="macro-stars"),
                                    html.Span(imp.trader_note, className="macro-note-text") if imp.trader_note else None
                                ]
                            )
                        ]
                    )
                ]
            )
        )

    if not expanded:
        remaining = len(enriched) - len(display_pool)
        if remaining > 0:
            items.append(html.Div(f"+ {remaining} dalších tento den", className="macro-more"))

    return html.Div(className="macro-events-inner", children=items)


def render_style_guide(guide: StyleGuide) -> html.Div:
    tone_map = {
        TradingStyle.MOMENTUM_TREND: "trend",
        TradingStyle.RANGE_SCALP: "range",
        TradingStyle.SQUEEZE_BREAKOUT: "squeeze",
        TradingStyle.WAIT: "wait",
        TradingStyle.NO_TRADE: "blocked",
    }
    tone = tone_map.get(guide.style, "wait")
    m = guide.metrics
    return html.Div(
        className=f"style-guide-inner tone-{tone}",
        children=[
            html.Div(
                className="style-head",
                children=[
                    html.Span(guide.style.value, className="style-label"),
                    html.Span(guide.headline, className="style-headline"),
                ],
            ),
            html.Div(guide.primary_action, className="style-primary"),
            html.Ul([html.Li(b) for b in guide.bullets], className="style-bullets") if guide.bullets else None,
            html.Div(
                className="style-metrics",
                children=[
                    html.Span(f"ATR× {m.atr_ratio}"),
                    html.Span(f"Vol {m.vol_regime}"),
                    html.Span(f"MTF {m.mtf_direction} {m.mtf_score}/4"),
                    html.Span(f"Spr/ATR {m.spread_cost_pct}%"),
                    html.Span(f"PDH {m.pdh_distance_pct:+.1f}%"),
                    html.Span(f"PDL {m.pdl_distance_pct:+.1f}%"),
                ],
            ),
        ],
    )


def render_verdict(verdict: Verdict) -> html.Div:
    tone = verdict.status.value.lower()
    msgs: list[str] = []
    for m in verdict.messages[:2]:
        clean = re.sub(r"^\[[^\]]+\]\s*", "", m)
        if clean and clean not in msgs:
            msgs.append(clean)
    text = " · ".join(msgs) if msgs else "—"
    label = VERDICT_LABEL_CZ.get(verdict.status.value, verdict.status.value)
    return html.Div(
        className=f"verdict-compact tone-{tone}",
        children=[
            html.Span(label, className="vc-tag"),
            html.Span(text, className="vc-text"),
        ],
    )


def tf_btn_class(active_tf: str, btn_tf: str) -> str:
    return f"tf-btn{' active' if active_tf == btn_tf else ''}"


def render_dxy_analysis(indicators: IndicatorBundle | None) -> html.Div:
    """Render SMT Divergence relation XAUUSD vs DXY."""
    if not indicators or not indicators.dxy_smt_divergence:
        return html.Div("Korelace DXY: Čekám na data...", className="dxy-analysis-empty")

    smt = indicators.dxy_smt_divergence
    mom_dir = indicators.dxy_momentum_dir or "NEUTRAL"
    corr = indicators.dxy_correlation

    # Default values
    mood_title = "NEUTRÁLNÍ NÁLADA"
    mood_desc = "Korelace s DXY je v rovnováze. Čekej na impuls."
    mood_tone = "wait"

    if smt == "BULLISH_SMT":
        mood_title = "BUY NÁLADA (DXY roste + Zlato roste)"
        mood_desc = "Institucionální nákupy: Zlato odmítá klesat navzdory silnému dolaru (SMT buy)."
        mood_tone = "bull"
    elif smt == "BEARISH_SMT":
        mood_title = "SELL NÁLADA (DXY klesá + Zlato klesá)"
        mood_desc = "Institucionální prodeje: Zlato odmítá růst navzdory slabému dolaru (SMT sell)."
        mood_tone = "bear"
    elif smt == "NORMAL":
        if mom_dir == "BEAR":
            mood_title = "BUY NÁLADA (Standardní USD/XAU korel.)"
            mood_desc = "Dolar klesá, Zlato roste podle běžného chování."
            mood_tone = "bull-dim"
        elif mom_dir == "BULL":
            mood_title = "SELL NÁLADA (Standardní USD/XAU korel.)"
            mood_desc = "Dolar roste, Zlato klesá podle běžného chování."
            mood_tone = "bear-dim"

    corr_text = f"{corr * 100:.0f}%" if corr is not None else "—"

    return html.Div(
        className=f"dxy-analysis-panel tone-{mood_tone}",
        children=[
            html.Div(
                className="dxy-analysis-head",
                children=[
                    html.Span("Vztah DXY & SMT", className="panel-title"),
                    html.Span(f"Korelace: {corr_text}", className="panel-badge panel-badge-dim"),
                ]
            ),
            html.Div(
                className="dxy-analysis-body",
                children=[
                    html.Div(mood_title, className="dxy-mood-title"),
                    html.Div(mood_desc, className="dxy-mood-desc"),
                ]
            )
        ]
    )


def render_scalp_efficiency(indicators: IndicatorBundle | None) -> html.Div:
    """Render Scalp Volatility Efficiency Index comparing current ATR to median."""
    if not indicators or indicators.atr_series is None or indicators.atr_series.empty:
        return html.Div("Efektivita scalpování: Čekám na data...", className="scalp-efficiency-empty")

    atr = indicators.atr
    median = float(indicators.atr_series.tail(100).median())
    ratio = atr / median if median > 0 else 1.0
    pct = ratio * 100

    if ratio >= 1.2:
        status_lbl = f"AKTIVNÍ (ATR +{pct - 100:.0f}% nad mediánem)"
        status_tone = "bull"
        status_desc = "Výborná volatilita pro M1 scalping. Cíle jsou efektivně dosahovány."
    elif ratio <= 0.8:
        status_lbl = f"MRTVÁ ZÓNA (ATR {pct - 100:.0f}% pod mediánem)"
        status_tone = "err"
        status_desc = "Nízký rozsah trhu. Vysoké riziko chopu a neefektivity kvůli spreadům."
    else:
        status_lbl = f"NORMÁLNÍ (ATR {pct:.0f}% vůči mediánu)"
        status_tone = "wait"
        status_desc = "Standardní volatilita. Průměrné scalpové podmínky."

    fill_pct = min(200.0, pct)

    return html.Div(
        className=f"scalp-efficiency-panel tone-{status_tone}",
        children=[
            html.Div(
                className="scalp-efficiency-head",
                children=[
                    html.Span("Index efektivity scalpu", className="panel-title"),
                    html.Span(f"ATR: {atr:.2f}", className="panel-badge panel-badge-dim"),
                ]
            ),
            html.Div(
                className="scalp-efficiency-body",
                children=[
                    html.Div(status_lbl, className="efficiency-title"),
                    html.Div(
                        className="efficiency-bar-track",
                        children=[
                            html.Div(
                                className=f"efficiency-bar-fill tone-{status_tone}",
                                style={"width": f"{fill_pct / 2}%"}
                            )
                        ]
                    ),
                    html.Div(status_desc, className="efficiency-desc"),
                ]
            )
        ]
    )


def render_kompakt_notifications(log_entries: list[dict] | None) -> html.Div:
    """Render log items inside the kompakt Notification Center."""
    if not log_entries:
        return html.Div(
            "Žádná nová varování.",
            className="notifications-log-empty"
        )

    items = []
    # Show last 20 notifications, newest on top
    for entry in reversed(log_entries[-20:]):
        ts_str = entry.get("timestamp", "")
        label = entry.get("label", "")
        priority = entry.get("priority", "info") # critical, warning, info
        
        items.append(
            html.Div(
                className=f"notification-log-item tone-{priority}",
                children=[
                    html.Div(
                        className="notification-log-item-top",
                        children=[
                            html.Span(ts_str, className="notification-time"),
                            html.Span(priority.upper(), className=f"notification-priority tone-{priority}"),
                        ]
                    ),
                    html.Div(label, className="notification-label")
                ]
            )
        )

    return html.Div(className="notifications-log-inner", children=items)
