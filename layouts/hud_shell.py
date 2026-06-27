"""Static HUD shell — structure stays fixed, callbacks only update data."""

from __future__ import annotations

from dash import dcc, html

from config import ACCOUNT, UI, HUD_VERSION
from layouts.quadrant_d import build_fusion_chart

_tier = "kompakt"
_chart_default = False


def build_app_layout() -> html.Div:
    return html.Div(
        id="hud-root",
        className="hud-root",
        **{"data-tier": _tier},
        children=[
            dcc.Store(id="active-tf", data="M1"),
            dcc.Store(id="kill-switch-store", data=""),
            dcc.Store(id="kill-arm-store", data={}),
            dcc.Store(id="hud-tier", data=_tier),
            dcc.Store(id="toast-queue", data={"active": {}}),
            dcc.Store(id="toast-dismissed", data=[]),
            dcc.Store(id="position-alert-state", data={}),
            dcc.Store(id="chart-visible", data=_chart_default),
            dcc.Store(id="macro-expand-store", data=False),
            dcc.Store(id="notification-log-store", storage_type="session", data=[]),
            html.Div(id="dummy-browser-notification-output", style={"display": "none"}),
            dcc.Interval(id="refresh-interval", interval=UI.refresh_interval_ms, n_intervals=0),
            html.Header(
                className="hud-header",
                children=[
                    html.Div(
                        className="hud-brand",
                        children=[
                            html.Span("QUANTUM", className="brand-main"),
                            html.Span("HUD", className="brand-sub"),
                        ],
                    ),
                    html.Div(
                        className="hud-header-center",
                        children=[
                            html.Span("XAUUSD", className="chip-symbol"),
                            html.Span(id="hud-account-chip", className="hud-account-chip"),
                            html.Div(id="hud-status-pills", className="hud-status-pills"),
                        ],
                    ),
                    html.Div(
                        className="hud-header-right",
                        children=[
                            html.Span(id="hud-clock", className="hud-clock"),
                            html.Div(
                                className="tier-toggle",
                                style={"display": "none"},
                                children=[
                                    html.Button(
                                        "Kompakt",
                                        id="tier-kompakt-btn",
                                        className="tier-btn active" if _tier == "kompakt" else "tier-btn",
                                        n_clicks=0,
                                    ),
                                    html.Button(
                                        "Příprava",
                                        id="tier-prep-btn",
                                        className="tier-btn active" if _tier == "prep" else "tier-btn",
                                        n_clicks=0,
                                    ),
                                    html.Button(
                                        "Detail",
                                        id="tier-detail-btn",
                                        className="tier-btn active" if _tier == "detail" else "tier-btn",
                                        n_clicks=0,
                                    ),
                                ],
                            ),
                            html.Button(
                                "Skrýt graf" if _chart_default else "Zobrazit graf",
                                id="chart-toggle-btn",
                                className="chart-toggle-btn tier-detail-only",
                            ),
                            html.Span(f"v{HUD_VERSION}", className="hud-build", title="Build verze dashboardu"),
                            html.Span(id="chart-resize-dummy", style={"display": "none"}),
                            html.Span(id="hud-live", className="status-live", children="LIVE"),
                        ],
                    ),
                ],
            ),
            html.Div(id="toast-stack", className="toast-stack", style={"display": "none"}),
            html.Main(
                id="hud-grid",
                className="hud-grid chart-hidden" if not _chart_default else "hud-grid",
                children=[
                    html.Div(
                        id="panel-col-left",
                        className="panel-col-left",
                        children=[
                            html.Section(
                                id="panel-advisor-top",
                                className="panel panel-advisor-top tier-kompakt-only",
                                children=[
                                    html.Div(
                                        className="panel-head",
                                        children=[
                                            html.Span("Advisor", className="panel-title"),
                                            html.Span("PRO", className="panel-badge panel-badge-dim"),
                                        ],
                                    ),
                                    html.Div(id="qb-recommendation", className="advisor-recommendation"),
                                ],
                            ),
                            html.Section(
                                id="panel-a",
                                className="panel panel-a",
                                children=[
                                    html.Div(
                                        className="panel-head",
                                        children=[
                                            html.Span("Účet", className="panel-title"),
                                            html.Span(id="qa-equity", className="panel-badge"),
                                        ],
                                    ),
                                    html.Div(id="qa-mini-stats", className="account-mini-stats-wrap"),
                                    html.Div(id="qa-positions-summary", className="positions-summary-badge"),
                                    html.Div(id="qa-positions", className="position-list"),
                                    html.Div(id="qa-journal", className="journal-wrap tier-detail-only"),
                                    html.Div(
                                        className="panel-foot",
                                        children=[
                                            html.Button("KILL SWITCH", id="kill-switch-btn", className="btn-kill", n_clicks=0),
                                            html.Span(id="kill-switch-msg", className="kill-msg"),
                                        ],
                                    ),
                                ],
                            ),
                            html.Section(
                                id="panel-m1-analytics",
                                className="panel panel-m1-analytics",
                                children=[
                                    html.Div(
                                        className="panel-head m1-analytics-head",
                                        children=[
                                            html.Span("M1 Analytics", className="panel-title"),
                                            html.Span("Signal Lab", className="panel-badge panel-badge-dim"),
                                        ],
                                    ),
                                    html.Div(id="qb-signals", className="signal-lab m1-signals"),
                                    html.Div(
                                        id="qb-metrics",
                                        className="metric-grid m1-metrics tier-detail-only",
                                    ),
                                ],
                            ),
                            html.Section(
                                id="panel-engine-log",
                                className="panel panel-engine-log tier-kompakt-only",
                                children=[
                                    html.Div(
                                        className="panel-head",
                                        children=[
                                            html.Span("Python Engine Logs", className="panel-title"),
                                            html.Span("SYS_OK", className="panel-badge panel-badge-dim"),
                                        ],
                                    ),
                                    html.Div(
                                        className="cmd-wrap",
                                        children=[
                                            html.Div(id="qb-engine-kompakt", className="cmd-slot"),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    html.Section(
                        id="panel-col-center",
                        className="panel panel-col-center",
                        children=[
                            html.Section(
                                id="panel-macro-inline",
                                className="panel panel-macro panel-macro-inline",
                                children=[
                                    html.Div(
                                        className="panel-head macro-head-row",
                                        children=[
                                            html.Span("Macro", className="panel-title"),
                                            html.Span(id="qm-status", className="panel-badge"),
                                            html.Button(
                                                "Rozbalit +7 dní",
                                                id="macro-expand-btn",
                                                className="macro-expand-btn tier-kompakt-only",
                                                n_clicks=0,
                                            ),
                                        ],
                                    ),
                                    html.Div(id="qm-summary", className="macro-summary"),
                                    html.Div(id="qm-checklist", className="macro-checklist tier-prep-only"),
                                    html.Div(id="qm-news", className="macro-events-list tier-prep-only"),
                                ],
                            ),
                            html.Div(id="qb-trade-command", className="center-trade-command"),
                            html.Div(id="qb-style-strip", className="center-style-strip"),
                            html.Div(id="qm-mtf-strip", className="mtf-strip-slot center-mtf-strip"),
                            html.Div(
                                id="qc-timeline-compact",
                                className="timeline-wrap session-timeline tier-kompakt-only",
                            ),
                            html.Div(
                                id="qp-dxy-analysis",
                                className="dxy-analysis-slot tier-kompakt-only",
                            ),
                            html.Div(
                                id="qp-scalp-efficiency",
                                className="scalp-efficiency-slot tier-kompakt-only",
                            ),
                            html.Div(
                                id="qp-trend-brief",
                                className="trend-brief-slot tier-prep-only",
                            ),
                            html.Div(
                                id="qp-trend-brief-kompakt",
                                className="trend-brief-slot tier-kompakt-only",
                            ),
                            html.Section(
                                id="panel-d-compact",
                                className="panel panel-d panel-d-compact",
                                children=[
                                    html.Div(
                                        className="chart-wrap chart-wrap-compact",
                                        children=[
                                            dcc.Graph(
                                                id="fusion-chart-compact",
                                                figure=build_fusion_chart(None, None, "M1"),
                                                config={"displayModeBar": False, "scrollZoom": False, "responsive": True},
                                                style={"height": "100%", "width": "100%"},
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                            html.Section(
                                id="panel-d",
                                className="panel panel-d panel-d-nested tier-detail-only",
                                style={"display": "flex"} if _chart_default else {"display": "none"},
                                children=[
                                    html.Div(
                                        className="panel-head",
                                        children=[
                                            html.Span("Graf", className="panel-title"),
                                            html.Div(
                                                className="tf-group",
                                                children=[
                                                    html.Button("M1", id="tf-m1", className="tf-btn active", n_clicks=0),
                                                    html.Button("M5", id="tf-m5", className="tf-btn", n_clicks=0),
                                                    html.Button("M15", id="tf-m15", className="tf-btn", n_clicks=0),
                                                ],
                                            ),
                                        ],
                                    ),
                                    html.Div(
                                        className="chart-wrap chart-wrap-mini",
                                        children=[
                                            dcc.Graph(
                                                id="fusion-chart",
                                                figure=build_fusion_chart(None, None, "M1"),
                                                config={"displayModeBar": False, "scrollZoom": True, "responsive": True},
                                                style={"height": "100%", "width": "100%"},
                                            ),
                                        ],
                                    ),
                                ],
                            ),
                        ],
                    ),
                    html.Section(
                        id="panel-col-right",
                        className="panel panel-col-right panel-session",
                        children=[
                            html.Div(
                                className="panel-head tier-detail-only",
                                children=[html.Span("Session", className="panel-title")],
                            ),
                            html.Div(id="qc-timeline", className="timeline-wrap session-timeline tier-detail-only"),
                            html.Div(id="qc-next-event", className="session-next-event-wrap tier-detail-only"),
                            html.Div(id="qc-risk-reminder", className="session-risk-wrap tier-detail-only"),
                            html.Div(id="qb-engine-panel", className="engine-panel-slot tier-detail-only"),
                            html.Div(
                                className="cmd-wrap tier-detail-only",
                                children=[html.Div(id="qb-engine", className="cmd-slot")],
                            ),
                            # Kompakt Notification Center
                            html.Section(
                                id="panel-notifications-kompakt",
                                className="panel panel-notifications tier-kompakt-only",
                                children=[
                                    html.Div(
                                        className="panel-head",
                                        children=[
                                            html.Span("NOTIFIKACE", className="panel-title"),
                                            html.Button(
                                                "Vymazat",
                                                id="clear-notifications-btn",
                                                className="btn-clear-log",
                                                n_clicks=0,
                                            ),
                                        ],
                                    ),
                                    html.Div(id="qb-notifications-log", className="notifications-log-list"),
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
