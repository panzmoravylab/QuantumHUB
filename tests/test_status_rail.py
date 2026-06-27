from status_rail import build_status_rail
from user_insights import ScalpPlan


def _minimal_plan(gate: str = "NE", reasons: tuple = ("Spread vysoký",)) -> ScalpPlan:
    return ScalpPlan(
        gate_action=gate,
        gate_tone="stop",
        direction="NEUTRAL",
        direction_tone="muted",
        scalp_hint="",
        spread_pts=30.0,
        spread_vs_median=2.0,
        spread_ok=False,
        atr_m1=1.0,
        lot=0.0,
        risk_usd=0.0,
        risk_pct=1.0,
        sl_points=0.0,
        sl_usd=0.0,
        daily_dd_remaining_usd=500.0,
        daily_dd_remaining_pct=2.0,
        trail_dd_remaining_usd=1000.0,
        trades_until_daily_limit=None,
        golden_window=False,
        next_news_label=None,
        next_news_minutes=None,
        pdh_distance_pct=0.0,
        pdl_distance_pct=0.0,
        reasons=reasons,
    )


def test_status_rail_max_three():
    plan = _minimal_plan()
    chips = build_status_rail(
        ["KRITICKÉ DD limit"],
        None,
        plan,
        None,
        None,
        None,
        None,
    )
    assert len(chips) <= 3


def test_status_rail_deduplicates_mimo_gw():
    plan = _minimal_plan(gate="POČKEJ", reasons=("Počkej na spread",))
    chips = build_status_rail([], None, plan, None, None, None, None)
    labels = [c.label.upper() for c in chips]
    assert labels.count("MIMO GW") <= 1
