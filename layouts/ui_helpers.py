"""Shared UI building blocks for Quantum HUD."""

from __future__ import annotations

from dash import html

from config import UI


def quad_header(title: str, meta: str = "", meta_class: str = "quad-meta") -> html.Div:
    return html.Div(
        className="quad-header",
        children=[
            html.Div(title, className="quad-title"),
            html.Div(meta, className=meta_class) if meta else None,
        ],
    )


def kpi_tile(label: str, value: str, sub: str = "", tone: str = "neutral") -> html.Div:
    return html.Div(
        className=f"kpi-tile tone-{tone}",
        children=[
            html.Div(label, className="kpi-label"),
            html.Div(value, className="kpi-value"),
            html.Div(sub, className="kpi-sub") if sub else None,
        ],
    )


def progress_bar(pct: float, limit: float, tone: str = "cyan") -> html.Div:
    width = min(100.0, (pct / limit * 100) if limit else 0)
    return html.Div(
        className="progress-track",
        children=[
            html.Div(
                className=f"progress-fill tone-{tone}",
                style={"width": f"{width}%", "transition": "none"},
            ),
            html.Div(className="progress-limit-mark", style={"left": "85%"}),
        ],
    )


def classify_atr(atr: float, atr_median: float, impulse: bool = False) -> tuple[str, str]:
    """Return (label, tone) for ATR volatility bucket."""
    if impulse:
        return "EXTREME", "red"
    if atr_median <= 0:
        return "STŘEDNÍ", "amber"
    ratio = atr / atr_median
    if ratio >= 1.5:
        return "VYSOKÁ", "red"
    if ratio >= 1.1:
        return "STŘEDNÍ", "amber"
    if ratio <= 0.75:
        return "NÍZKÁ", "cyan"
    return "STŘEDNÍ", "amber"


def prop_dd_card(title: str, pct: float, limit: float, usd_label: str = "") -> html.Div:
    """Prop drawdown s jasným limitem, rezervou a stavem pro rychlou orientaci."""
    if limit <= 0:
        limit = 1.0
    pct_display = round(pct, 1)
    used_ratio = pct / limit
    remaining = max(0.0, limit - pct)

    if used_ratio >= 1.0:
        tone, status = "red", "LIMIT"
        status_tip = "Limit porušen — stop obchodování."
    elif used_ratio >= 0.85:
        tone, status = "red", "STOP"
        status_tip = "85 %+ limitu — okamžitě neobchodovat."
    elif used_ratio >= 0.5:
        tone, status = "amber", "POZOR"
        status_tip = "Polovina limitu — snižte risk."
    else:
        tone, status = "cyan", "OK"
        status_tip = "V bezpečné rezervě prop pravidel."

    return html.Div(
        className=f"dd-card prop-dd tone-{tone}",
        children=[
            html.Div(
                className="dd-card-top",
                children=[
                    html.Div(
                        className="dd-title-wrap",
                        children=[
                            html.Span(title, className="kpi-label"),
                            html.Span(status, className=f"dd-status-tag tag-{tone}", title=status_tip),
                        ],
                    ),
                    html.Span(f"{pct_display:.1f}%", className="dd-pct"),
                ],
            ),
            progress_bar(pct, limit, tone),
            html.Div(
                className="dd-card-mid",
                children=html.Span(
                    f"Využito {pct_display:.1f}% z {limit:.1f}% · zbývá {remaining:.1f}%",
                    className="dd-mid-label",
                ),
            ),
            html.Div(
                className="dd-card-foot",
                children=[
                    html.Span(usd_label) if usd_label else None,
                    html.Span(f"Limit {limit:.1f}%"),
                ],
            ),
        ],
    )


def dd_card(title: str, pct: float, limit: float, usd_label: str = "") -> html.Div:
    return prop_dd_card(title, pct, limit, usd_label)


def alert_chip(text: str, kind: str) -> html.Div:
    return html.Div(text, className=f"alert-chip chip-{kind}")


def mtf_pill(tf: str, bias: str, icon: str) -> html.Div:
    tone = {"BULL": "bull", "BEAR": "bear"}.get(bias, "neutral")
    return html.Div(
        className=f"mtf-pill tone-{tone}",
        children=[
            html.Span(tf, className="mtf-pill-tf"),
            html.Span(f"{icon} {bias}", className="mtf-pill-bias"),
        ],
    )


def verdict_panel(status: str, messages: list[str]) -> html.Div:
    tone = status.lower()
    return html.Div(
        className=f"verdict-panel tone-{tone}",
        children=[
            html.Div(f"VERDICT · {status}", className="verdict-head"),
            html.Ul([html.Li(m) for m in messages], className="verdict-list"),
        ],
    )


def empty_positions_row() -> dict:
    return {"Symbol": "—", "Side": "—", "Lots": "—", "P&L": "—", "RRR": "—"}


TABLE_HEADER = {
    "backgroundColor": "transparent",
    "color": UI.neon_cyan,
    "fontWeight": "600",
    "fontSize": "10px",
    "letterSpacing": "0.08em",
    "textTransform": "uppercase",
    "border": "none",
    "borderBottom": "1px solid rgba(0,255,204,0.15)",
    "padding": "6px 8px",
}

TABLE_CELL = {
    "backgroundColor": "transparent",
    "color": "#CBD5E1",
    "fontSize": "11px",
    "fontFamily": "'JetBrains Mono', monospace",
    "padding": "5px 8px",
    "border": "none",
    "borderBottom": "1px solid rgba(255,255,255,0.04)",
    "textAlign": "left",
}
