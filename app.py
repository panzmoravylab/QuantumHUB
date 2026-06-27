"""
Quantum HUD Trading Dashboard — Plotly Dash main entry point.
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dash import ALL, Dash, Input, Output, State, callback, clientside_callback, ClientsideFunction, ctx, html, no_update

from alerts import alert_on_new_critical
from config import HUD_MODE, RISK, SAFETY, UI, HUD_VERSION
from journal_stats import compute_session_stats
from toast_manager import active_toasts, build_toast_candidates, merge_extra_toasts, sync_toast_queue
from position_manager import close_toast_candidates, evaluate_positions
from layouts.hud_shell import build_app_layout
from layouts.quadrant_d import build_fusion_chart
from layouts.renderers import (
    panel_a_class,
    render_account_mini_stats,
    render_cmd_terminal,
    render_engine_panel,
    render_equity,
    render_header_account_chip,
    render_header_status_pills,
    render_metrics,
    render_mtf_strip,
    render_macro_events,
    render_macro_status,
    render_macro_summary,
    render_next_event_compact,
    render_pre_news_checklist,
    render_risk_reminder,
    render_toast_stack,
    render_style_strip,
    render_trade_decision_hero,
    render_trend_brief_panel,
    render_trade_journal,
    render_positions_summary,
    render_position_list,
    render_signal_lab_compact,
    render_timeline,
    render_recommendation,
    tf_btn_class,
)
from trend_brief import build_trend_brief
from mt5_connector import SharedState

if HUD_MODE == "test":
    from test_replay import TestReplayConnector as DataConnector
else:
    from mt5_connector import MT5Connector as DataConnector
from news_scraper import NewsCache, NewsScraperThread, refresh_news_counts
from macro_engine import analyze_macro_day, analyze_macro_focus, enrich_events, events_on_date
from user_insights import build_engine_panel, build_pre_news_checklist, build_scalp_plan
from risk_engine import calc_lot_size, evaluate_verdict, get_session_timeline
from trading_style import evaluate_trading_style

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

state = SharedState()
connector = DataConnector(state)
news_cache = NewsCache()
news_scraper = NewsScraperThread(news_cache, connector, compute_log=state.compute_log)
_boot_label = "TEST režim" if HUD_MODE == "test" else "LIVE režim"
state.compute_log.insight(
    "system",
    "HUD startuje",
    f"Quantum HUD v{HUD_VERSION} · {_boot_label} · web server běží",
    "ok",
)
state.compute_log.cmd("run", f"boot · Quantum HUD v{HUD_VERSION}", "ok")

try:
    from integrations import tier5_status

    state.compute_log.insight("system", "Tier 5 moduly", tier5_status.summary(), "info")
except ImportError:
    pass

MT5_CONNECTED = False
_last_calc_log_ts = 0.0


def _log_calc_snapshot(scalp_plan, verdict, style_guide, account, market, connected) -> None:
    """Pravidelný [calc] řádek v CMD okně — důkaz že Python engine běží."""
    global _last_calc_log_ts
    now_ts = time.monotonic()
    if now_ts - _last_calc_log_ts < 5.0:
        return
    _last_calc_log_ts = now_ts

    gw = "GW" if verdict.golden_window_active else "off-GW"
    spr = f"{market.spread_points:.0f}p" if market else "—"
    dd = f"{account.daily_drawdown_pct:.1f}%" if account else "—"
    style = style_guide.style.value if style_guide else "—"
    level = {"go": "ok", "stop": "err", "wait": "warn"}.get(scalp_plan.gate_tone, "info")
    state.compute_log.cmd(
        "calc",
        f"TEĎ={scalp_plan.gate_action} · {scalp_plan.direction} · {gw} · spr {spr} · DD {dd} · {style}",
        level,
    )
    if connected:
        state.compute_log.cmd("run", "refresh OK · callback · MT5 stream", "ok")


def _bootstrap_data_source() -> None:
    """MT5 / TEST init v pozadí — nesmí blokovat start web serveru."""
    global MT5_CONNECTED
    try:
        MT5_CONNECTED = connector.initialize()
        if MT5_CONNECTED:
            connector.start_streaming(interval=UI.refresh_interval_ms / 1000)
            if HUD_MODE == "test":
                logger.info("Test replay started (background bootstrap)")
            else:
                logger.info("MT5 connected (background bootstrap)")
        else:
            if HUD_MODE == "test":
                logger.warning("Test replay failed — check test_data snapshot")
            else:
                logger.warning("MT5 not connected — dashboard will run in offline mode")
    except Exception:
        MT5_CONNECTED = False
        logger.exception("Data source background bootstrap failed")


news_scraper.start()

app = Dash(
    __name__,
    title="Quantum HUD",
    update_title=None,
    suppress_callback_exceptions=True,
    external_stylesheets=[
        "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap",
    ],
)

app.layout = build_app_layout()


@app.server.after_request
def _prevent_stale_hud_cache(response):
    """After layout/callback changes, avoid serving cached HTML with old Dash dependency graph."""
    ctype = response.content_type or ""
    if "text/html" in ctype or "javascript" in ctype or "json" in ctype:
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
    return response


app.clientside_callback(
    """
    function(visible) {
        if (visible) {
            setTimeout(function() {
                var plot = document.querySelector('#fusion-chart .js-plotly-plot');
                if (plot && window.Plotly) { window.Plotly.Plots.resize(plot); }
            }, 200);
        }
        return '';
    }
    """,
    Output("chart-resize-dummy", "children"),
    Input("chart-visible", "data"),
)


def _sl_distance_price(market) -> float:
    if not market:
        return 0.0
    mode = SAFETY.sl_mode
    if mode == "points" and SAFETY.sl_points > 0:
        params = connector.get_symbol_trade_params()
        tick = params.tick_size if params else 0.01
        return SAFETY.sl_points * tick
    if mode == "pct" and SAFETY.sl_pct > 0:
        return market.bid * (SAFETY.sl_pct / 100)
    return market.atr * SAFETY.sl_atr_multiplier


def _get_lot_result(market, account):
    if not market or not account:
        return None
    sl_dist = _sl_distance_price(market)
    if sl_dist <= 0:
        return None
    params = connector.get_symbol_trade_params()
    if params is None:
        return calc_lot_size(
            equity=account.equity,
            sl_distance_price=sl_dist,
            tick_value=1.0,
            tick_size=0.01,
        )
    return calc_lot_size(
        equity=account.equity,
        sl_distance_price=sl_dist,
        tick_value=params.tick_value,
        tick_size=params.tick_size,
        min_lot=params.volume_min,
        max_lot=params.volume_max,
        lot_step=params.volume_step,
    )


@callback(
    Output("active-tf", "data"),
    Input("tf-m1", "n_clicks"),
    Input("tf-m5", "n_clicks"),
    Input("tf-m15", "n_clicks"),
    State("active-tf", "data"),
    prevent_initial_call=True,
)
def switch_timeframe(_n1, _n2, _n3, current):
    mapping = {"tf-m1": "M1", "tf-m5": "M5", "tf-m15": "M15"}
    return mapping.get(ctx.triggered_id, current)


@callback(
    Output("kill-switch-store", "data"),
    Output("kill-arm-store", "data"),
    Input("kill-switch-btn", "n_clicks"),
    State("kill-arm-store", "data"),
    prevent_initial_call=True,
)
def kill_switch(n_clicks, arm_data):
    if not n_clicks or not connector.is_connected():
        label = "TEST offline" if HUD_MODE == "test" else "MT5 offline"
        return f"{label} — kill switch nedostupný", arm_data or {}

    arm = arm_data or {}
    now = time.time()
    armed = arm.get("armed", False)
    armed_ts = float(arm.get("ts", 0))

    if armed and (now - armed_ts) <= SAFETY.kill_confirm_seconds:
        connector.kill_switch_close_all()
        return state.read()["kill_switch_message"], {"armed": False, "ts": 0}

    return (
        f"Klikněte znovu pro potvrzení ({SAFETY.kill_confirm_seconds:.0f}s)",
        {"armed": True, "ts": now},
    )


@callback(
    Output("chart-visible", "data"),
    Output("chart-toggle-btn", "children"),
    Input("chart-toggle-btn", "n_clicks"),
    State("chart-visible", "data"),
    prevent_initial_call=True,
)
def toggle_chart(_n, visible):
    visible = not bool(visible)
    label = "Skrýt graf" if visible else "Zobrazit graf"
    return visible, label


@callback(
    Output("hud-tier", "data"),
    Output("hud-root", "data-tier"),
    Output("tier-kompakt-btn", "className"),
    Output("tier-prep-btn", "className"),
    Output("tier-detail-btn", "className"),
    Input("tier-kompakt-btn", "n_clicks"),
    Input("tier-prep-btn", "n_clicks"),
    Input("tier-detail-btn", "n_clicks"),
    State("hud-tier", "data"),
    prevent_initial_call=True,
)
def switch_hud_tier(_k, _p, _d, current):
    current = current or "trade"
    triggered = ctx.triggered_id
    if triggered == "tier-kompakt-btn":
        tier = "trade" if current == "kompakt" else "kompakt"
    elif triggered == "tier-prep-btn":
        tier = "trade" if current == "prep" else "prep"
    elif triggered == "tier-detail-btn":
        tier = "trade" if current == "detail" else "detail"
    else:
        tier = current

    def btn_cls(name: str) -> str:
        return "tier-btn active" if tier == name else "tier-btn"

    return tier, tier, btn_cls("kompakt"), btn_cls("prep"), btn_cls("detail")


@callback(
    Output("panel-d", "style"),
    Output("panel-d", "className"),
    Input("chart-visible", "data"),
)
def sync_chart_visibility(visible):
    visible = bool(visible)
    panel_style = {"display": "flex"} if visible else {"display": "none"}
    panel_cls = "panel panel-d panel-d-nested tier-detail-only" if visible else (
        "panel panel-d panel-d-nested tier-detail-only is-hidden"
    )
    return panel_style, panel_cls


@callback(
    Output("toast-dismissed", "data"),
    Input({"type": "toast-dismiss", "index": ALL}, "n_clicks"),
    State("toast-dismissed", "data"),
    State({"type": "toast-dismiss", "index": ALL}, "id"),
    prevent_initial_call=True,
)
def dismiss_toast(_clicks, dismissed, ids):
    dismissed = list(dismissed or [])
    # Only append to dismissed if click count is actually incremented (> 0)
    for click_count, btn_id in zip(_clicks or [], ids or []):
        if click_count and click_count > 0:
            key = btn_id.get("index")
            if key and key not in dismissed:
                dismissed.append(key)
    return dismissed


@callback(
    Output("qm-status", "children"),
    Output("qm-summary", "children"),
    Output("qm-checklist", "children"),
    Output("qm-news", "children"),
    Output("qm-mtf-strip", "children"),
    Output("qp-trend-brief", "children"),
    Output("qp-trend-brief-kompakt", "children"),
    Output("toast-stack", "children"),
    Output("toast-stack", "style"),
    Output("toast-queue", "data"),
    Output("panel-a", "className"),
    Output("qa-equity", "children"),
    Output("qa-mini-stats", "children"),
    Output("qa-positions-summary", "children"),
    Output("qa-positions", "children"),
    Output("position-alert-state", "data"),
    Output("qa-journal", "children"),
    Output("kill-switch-msg", "children"),
    Output("fusion-chart-compact", "figure"),
    Output("fusion-chart", "figure"),
    Output("tf-m1", "className"),
    Output("tf-m5", "className"),
    Output("tf-m15", "className"),
    Output("qb-trade-command", "children"),
    Output("qb-style-strip", "children"),
    Output("qb-signals", "children"),
    Output("qb-metrics", "children"),
    Output("qb-engine-panel", "children"),
    Output("qb-engine", "children"),
    Output("qb-recommendation", "children"),
    Output("qb-engine-kompakt", "children"),
    Output("qc-timeline", "children"),
    Output("qc-timeline-compact", "children"),
    Output("qc-next-event", "children"),
    Output("qc-risk-reminder", "children"),
    Output("hud-account-chip", "children"),
    Output("hud-status-pills", "children"),
    Output("hud-clock", "children"),
    Output("hud-live", "children"),
    Output("hud-live", "className"),
    Output("qp-dxy-analysis", "children"),
    Output("qp-scalp-efficiency", "children"),
    Output("qb-notifications-log", "children"),
    Output("notification-log-store", "data"),
    Input("refresh-interval", "n_intervals"),
    Input("active-tf", "data"),
    Input("kill-switch-store", "data"),
    Input("macro-expand-store", "data"),
    State("chart-visible", "data"),
    State("hud-tier", "data"),
    State("toast-queue", "data"),
    State("toast-dismissed", "data"),
    State("position-alert-state", "data"),
    State("notification-log-store", "data"),
)
def refresh_dashboard(
    _n, active_tf, kill_status, macro_expanded, chart_visible, hud_tier,
    toast_queue, toast_dismissed, position_alert_state, notification_log,
):
    try:
        return _refresh_dashboard_impl(
            _n, active_tf, kill_status, chart_visible, hud_tier,
            toast_queue, toast_dismissed, position_alert_state,
            macro_expanded=macro_expanded,
            notification_log=notification_log,
        )
    except Exception as exc:
        logger.exception("Dashboard refresh failed")
        tf = active_tf or "M1"
        err_msg = f"[ERROR] {type(exc).__name__}: {exc}"
        # Return placeholders for all callback outputs to avoid KeyError
        return (
            "ERROR",                     # qm-status
            err_msg,                     # qm-summary
            err_msg,                     # qm-checklist
            err_msg,                     # qm-news
            no_update,                   # qm-mtf-strip
            no_update,                   # qp-trend-brief
            no_update,                   # qp-trend-brief-kompakt
            html.Div("Chyba dashboardu", className="toast tone-critical"),  # toast-stack children
            {"display": "none"},         # toast-stack style
            {"active": {}},              # toast-queue data
            no_update,                   # panel-a className
            no_update,                   # qa-equity
            no_update,                   # qa-mini-stats
            no_update,                   # qa-positions-summary
            no_update,                   # qa-positions
            no_update,                   # position-alert-state
            no_update,                   # qa-journal
            no_update,                   # kill-switch-msg
            no_update,                   # fusion-chart-compact
            no_update,                   # fusion-chart
            no_update,                   # tf-m1
            no_update,                   # tf-m5
            no_update,                   # tf-m15
            no_update,                   # qb-trade-command
            no_update,                   # qb-style-strip
            no_update,                   # qb-signals
            no_update,                   # qb-metrics
            no_update,                   # qb-engine-panel
            no_update,                   # qb-engine
            no_update,                   # qb-recommendation
            no_update,                   # qb-engine-kompakt
            no_update,                   # qc-timeline
            no_update,                   # qc-timeline-compact
            no_update,                   # qc-next-event
            no_update,                   # qc-risk-reminder
            no_update,                   # hud-account-chip
            no_update,                   # hud-status-pills
            no_update,                   # hud-clock
            no_update,                   # hud-live children
            no_update,                   # hud-live className
            no_update,                   # qp-dxy-analysis
            no_update,                   # qp-scalp-efficiency
            no_update,                   # qb-notifications-log
            no_update,                   # notification-log-store data
        )


def _refresh_dashboard_impl(
    _n,
    active_tf,
    kill_status,
    chart_visible=False,
    hud_tier="trade",
    toast_queue=None,
    toast_dismissed=None,
    position_alert_state=None,
    macro_expanded=False,
    notification_log=None,
):
    tz = ZoneInfo(RISK.timezone)
    now = datetime.now(tz)
    clock = now.strftime("%H:%M:%S")

    data = state.read()
    account = data["account"]
    market = data["market"]
    positions = data["positions"]
    alerts = data["alerts"]

    signal_lab = data.get("signal_lab")

    connected = account.connected if account else connector.is_connected()
    if HUD_MODE == "test":
        live_text = "TEST" if connected else "TEST OFF"
        live_class = "status-live test" if connected else "status-live test offline"
    else:
        live_text = "LIVE" if connected else "OFFLINE"
        live_class = "status-live" if connected else "status-live offline"

    if alerts:
        alert_on_new_critical(alerts)

    indicators = data.get("indicators")
    chart_df = None
    if market:
        if indicators is None:
            from indicators import IndicatorBundle, build_indicator_bundle

            indicators = build_indicator_bundle(
                market.m1_rates,
                market.m5_rates,
                market.m15_rates,
                market.h1_rates,
                market.dxy_m5_rates,
            )
        tf_map = {"M1": market.m1_rates, "M5": market.m5_rates, "M15": market.m15_rates}
        chart_df = tf_map.get(active_tf or "M1", market.m1_rates)

    events, macro_error, macro_source = news_cache.read()
    events = refresh_news_counts(events, now)
    macro_summary = analyze_macro_focus(events, now)
    today_events = events_on_date(events, now.date(), tz)
    today_macro = analyze_macro_day(today_events, now)
    enriched = enrich_events(events, now)
    sessions = get_session_timeline(now)
    verdict = evaluate_verdict(account, market, events, now)
    lot_result = _get_lot_result(market, account)
    style_guide = evaluate_trading_style(market, indicators, verdict, today_macro, account)
    checklist = build_pre_news_checklist(
        account, market, positions, verdict, lot_result, events, macro_summary, now
    )
    scalp_plan = build_scalp_plan(
        account,
        market,
        verdict,
        style_guide,
        macro_summary,
        lot_result,
        events,
        signal_lab,
        connected,
        now,
    )
    _log_calc_snapshot(scalp_plan, verdict, style_guide, account, market, connected)

    trend_brief = build_trend_brief(
        market, indicators, style_guide, state.read_strength_history(), now
    )
    state.record_trend_strength(trend_brief.strength_now)
    trend_brief = build_trend_brief(
        market, indicators, style_guide, state.read_strength_history(), now
    )

    cmd_lines = state.compute_log.read()
    engine_panel = build_engine_panel(
        account,
        market,
        verdict,
        macro_summary,
        signal_lab,
        state.compute_log,
        connected,
    )

    tf = active_tf or "M1"
    critical = account.is_critical if account else False
    ks_msg = kill_status or data.get("kill_switch_message", "")

    tracks = data.get("position_tracks") or state.read_position_tracks()
    position_verdicts = evaluate_positions(
        positions,
        tracks,
        market,
        indicators,
        signal_lab,
        style_guide,
        verdict,
        macro_summary,
        now,
    )

    toast_candidates = build_toast_candidates(
        alerts, verdict, scalp_plan, style_guide, macro_summary, market, indicators
    )
    new_queue = sync_toast_queue(toast_candidates, toast_queue, toast_dismissed)
    close_extras = [(k, label, "critical") for k, label in close_toast_candidates(position_verdicts)]
    new_queue = merge_extra_toasts(new_queue, close_extras, toast_dismissed)
    toasts = active_toasts(new_queue)
    toast_content = None
    toast_style = {"display": "none"}

    new_alert_state = {str(v.ticket): v.action for v in position_verdicts}

    macro_badge = render_macro_status(macro_summary, macro_source, macro_error)
    if macro_source and macro_source != "CHYBA":
        macro_badge = f"{macro_badge} · {macro_source}"
    elif macro_source == "CHYBA":
        macro_badge = f"{macro_badge} · cache/stale"

    compact_chart = build_fusion_chart(market.m1_rates if market else None, indicators, "M1")
    session_stats = compute_session_stats(account, positions, now=now)

    base_tuple = (
        macro_badge,
        render_macro_summary(macro_summary, market, macro_source, macro_error),
        render_pre_news_checklist(checklist),
        render_macro_events(enriched, macro_summary, expanded=macro_expanded),
        render_mtf_strip(indicators),
        render_trend_brief_panel(trend_brief),
        render_trend_brief_panel(trend_brief),  # qp-trend-brief-kompakt
        toast_content,
        toast_style,
        new_queue,
        panel_a_class(critical),
        render_equity(account),
        render_account_mini_stats(session_stats),
        render_positions_summary(position_verdicts),
        render_position_list(position_verdicts),
        new_alert_state,
        render_trade_journal(),
        ks_msg,
        compact_chart,
        build_fusion_chart(chart_df, indicators, tf) if chart_visible else no_update,
        tf_btn_class(tf, "M1"),
        tf_btn_class(tf, "M5"),
        tf_btn_class(tf, "M15"),
        render_trade_decision_hero(market, scalp_plan, verdict, trend_brief, indicators),
        render_style_strip(style_guide),
        render_signal_lab_compact(signal_lab, market, indicators),
        render_metrics(market, indicators, lot_result),
        render_engine_panel(engine_panel),
        render_cmd_terminal(cmd_lines, running=connected, market=market, signal_lab=signal_lab),
        render_recommendation(scalp_plan, verdict, indicators),
        render_cmd_terminal(cmd_lines, running=connected, market=market, signal_lab=signal_lab),
        render_timeline(sessions), # qc-timeline
        render_timeline(sessions), # qc-timeline-compact
        render_next_event_compact(enriched, scalp_plan),
        render_risk_reminder(account, scalp_plan, verdict),
        render_header_account_chip(account),
        render_header_status_pills(
            account, market, macro_summary, verdict, scalp_plan, connected
        ),
        clock,
        live_text,
        live_class,
    )

    # DXY Analysis (SMT) and Scalp Efficiency rendering
    from layouts.renderers import render_dxy_analysis, render_scalp_efficiency, render_kompakt_notifications
    dxy_analysis_html = render_dxy_analysis(indicators)
    scalp_efficiency_html = render_scalp_efficiency(indicators)

    # Notification log updates
    updated_log = list(notification_log or [])
    logged_keys = {item["key"] for item in updated_log}
    
    # 1. Check for position verdict shift to "ZAVŘÍT"
    for v in position_verdicts:
        if v.action == "ZAVŘÍT":
            ticket = v.ticket
            reason_str = v.headline
            label = f"ZAVŘÍT POZICI: Lístek #{ticket} ({v.side} {v.volume} lotů) - {reason_str}"
            key = f"close_{ticket}"
            if key not in logged_keys:
                ts_str = now.strftime("%H:%M:%S")
                updated_log.append({
                    "key": key,
                    "label": label,
                    "priority": "critical",
                    "timestamp": ts_str
                })
                logged_keys.add(key)
                from alerts import send_discord_webhook
                send_discord_webhook(f"🚨 UZAVŘÍT POZICI: #{ticket} - {reason_str}")
                
    # 2. Check for trade opportunity signal (gate_action == "ANO")
    if scalp_plan and scalp_plan.gate_action == "ANO":
        label = f"PŘÍLEŽITOST K VSTUPU: {scalp_plan.direction} na Zlato - {scalp_plan.scalp_hint}"
        key = "opp_" + now.strftime("%Y-%m-%d_%H:%M")
        if key not in logged_keys:
            ts_str = now.strftime("%H:%M:%S")
            updated_log.append({
                "key": key,
                "label": label,
                "priority": "warning",
                "timestamp": ts_str
            })
            logged_keys.add(key)
            from alerts import send_discord_webhook
            send_discord_webhook(f"📈 PŘÍLEŽITOST K VSTUPU: {scalp_plan.direction} - {scalp_plan.scalp_hint}")
            
    # 3. Check for upcoming macro news (< 30 minutes)
    if scalp_plan and scalp_plan.next_news_minutes is not None:
        if scalp_plan.next_news_minutes <= 30 and scalp_plan.next_news_minutes > 0:
            label = f"POZOR MAKRO: Za {scalp_plan.next_news_minutes} min začíná {scalp_plan.next_news_label}!"
            key = f"news_{scalp_plan.next_news_label}_{now.hour}_{now.minute // 5}"
            if key not in logged_keys:
                ts_str = now.strftime("%H:%M:%S")
                updated_log.append({
                    "key": key,
                    "label": label,
                    "priority": "critical",
                    "timestamp": ts_str
                })
                logged_keys.add(key)
                from alerts import send_discord_webhook
                send_discord_webhook(f"⚠️ MAKRO NEWS VÝSTRAHA: {label}")

    notifications_html = render_kompakt_notifications(updated_log)

    return base_tuple + (
        dxy_analysis_html,
        scalp_efficiency_html,
        notifications_html,
        updated_log,
    )


@callback(
    Output("macro-expand-store", "data"),
    Output("macro-expand-btn", "children"),
    Input("macro-expand-btn", "n_clicks"),
    State("macro-expand-store", "data"),
    prevent_initial_call=True,
)
def toggle_macro_expansion(n_clicks, expanded):
    expanded = not expanded
    label = "Sbalit na dnes" if expanded else "Rozbalit +7 dní"
    return expanded, label


@callback(
    Output("notification-log-store", "data", allow_duplicate=True),
    Input("clear-notifications-btn", "n_clicks"),
    prevent_initial_call=True,
)
def clear_notification_log(n_clicks):
    if n_clicks and n_clicks > 0:
        return []
    return no_update


# Clientside callback for native browser notifications
clientside_callback(
    ClientsideFunction(
        namespace="clientside",
        function_name="play_notification"
    ),
    Output("dummy-browser-notification-output", "children"),
    Input("notification-log-store", "data"),
    prevent_initial_call=True
)


def _delayed_bootstrap_data_source() -> None:
    """Po startu serveru — MT5 API blokuje celý proces, nesmí běžet před bind portu."""
    time.sleep(4)
    _bootstrap_data_source()


def main() -> None:
    mode_label = "TEST replay" if HUD_MODE == "test" else "MT5 bootstrap"
    logger.info(
        "Quantum HUD v%s — spoustim web server (%s v pozadi)",
        HUD_VERSION,
        mode_label,
    )
    logger.info("App path: %s", Path(__file__).resolve())
    threading.Thread(
        target=_delayed_bootstrap_data_source,
        daemon=True,
        name="TestBootstrap" if HUD_MODE == "test" else "MT5Bootstrap",
    ).start()
    try:
        app.run(host="127.0.0.1", port=8050, debug=False, threaded=True)
    except KeyboardInterrupt:
        logger.info("Ukonceno uzivatelem (Ctrl+C)")
    finally:
        try:
            connector.stop_streaming()
            connector.shutdown()
            news_scraper.stop()
        except Exception:
            logger.debug("Shutdown cleanup skipped", exc_info=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
