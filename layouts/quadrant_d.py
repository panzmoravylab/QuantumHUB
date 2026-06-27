"""Fusion chart — responsive candlestick with SMC overlays."""

from __future__ import annotations

import plotly.graph_objects as go

from config import UI
from indicators import FVGZone, IndicatorBundle


def _chart_layout() -> dict:
    return dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(8,12,20,0.95)",
        margin=dict(l=8, r=48, t=8, b=24),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.04)",
            linecolor="rgba(255,255,255,0.08)",
            tickcolor="#64748b",
            tickfont=dict(size=10, color="#64748b"),
            rangeslider=dict(visible=False),
            showspikes=True,
            spikethickness=1,
            spikecolor=UI.neon_cyan,
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.04)",
            linecolor="rgba(255,255,255,0.08)",
            tickcolor="#64748b",
            tickfont=dict(size=10, color="#64748b"),
            side="right",
            showspikes=True,
            spikethickness=1,
            spikecolor=UI.neon_cyan,
        ),
        showlegend=False,
        hovermode="x unified",
        hoverlabel=dict(bgcolor="#111827", font_size=11, font_color="#e2e8f0"),
    )


def build_fusion_chart(df, indicators: IndicatorBundle | None, timeframe: str = "M1") -> go.Figure:
    fig = go.Figure()

    if df is None or df.empty:
        fig.add_annotation(
            text="Awaiting MT5 feed…",
            xref="paper",
            yref="paper",
            x=0.5,
            y=0.5,
            showarrow=False,
            font=dict(color="#475569", size=13, family="Inter"),
        )
        fig.update_layout(**_chart_layout(), xaxis_visible=False, yaxis_visible=False, height=None)
        fig.update_layout(autosize=True)
        return fig

    fig.add_trace(
        go.Candlestick(
            x=df["time"],
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            increasing=dict(line=dict(color="#00ffcc", width=1), fillcolor="rgba(0,255,204,0.85)"),
            decreasing=dict(line=dict(color="#ff3366", width=1), fillcolor="rgba(255,51,102,0.85)"),
            whiskerwidth=0.5,
            name=timeframe,
        )
    )

    if indicators:
        bb = indicators.bb
        if not bb.upper.empty:
            fig.add_trace(
                go.Scatter(
                    x=df["time"],
                    y=bb.upper,
                    line=dict(color="rgba(0,255,204,0.25)", width=1),
                    hoverinfo="skip",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=df["time"],
                    y=bb.lower,
                    line=dict(color="rgba(0,255,204,0.25)", width=1),
                    fill="tonexty",
                    fillcolor="rgba(0,255,204,0.04)",
                    hoverinfo="skip",
                )
            )

        if indicators.pdh is not None:
            fig.add_hline(
                y=indicators.pdh,
                line=dict(dash="dot", color="#f59e0b", width=1),
                annotation=dict(text="PDH", font=dict(size=9, color="#f59e0b"), bgcolor="rgba(0,0,0,0)"),
            )
        if indicators.pdl is not None:
            fig.add_hline(
                y=indicators.pdl,
                line=dict(dash="dot", color="#a78bfa", width=1),
                annotation=dict(text="PDL", font=dict(size=9, color="#a78bfa"), bgcolor="rgba(0,0,0,0)"),
            )

        for zone in indicators.fvg_zones[-6:]:
            _add_fvg(fig, zone)

        if indicators.bb.is_squeeze:
            fig.add_annotation(
                text="SQUEEZE",
                xref="paper",
                yref="paper",
                x=0.01,
                y=0.99,
                showarrow=False,
                font=dict(color=UI.neon_cyan, size=9),
                bgcolor="rgba(0,255,204,0.12)",
                borderpad=4,
            )

    fig.update_layout(**_chart_layout(), uirevision=timeframe, autosize=True, height=None)
    return fig


def _add_fvg(fig: go.Figure, zone: FVGZone) -> None:
    color = "rgba(0,255,204,0.12)" if zone.direction == "bullish" else "rgba(255,51,102,0.12)"
    fig.add_shape(
        type="rect",
        x0=zone.start_time,
        x1=zone.end_time,
        y0=zone.bottom,
        y1=zone.top,
        fillcolor=color,
        line=dict(width=0),
        layer="below",
    )
