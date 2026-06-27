import pandas as pd
import pytest

from signal_lab import compute_signal_lab


def _make_rates(n: int = 50, base: float = 4000.0) -> pd.DataFrame:
    rows = []
    for i in range(n):
        c = base + i * 0.1
        rows.append({"open": c, "high": c + 1, "low": c - 1, "close": c, "time": pd.Timestamp("2026-06-27") + pd.Timedelta(minutes=i)})
    return pd.DataFrame(rows)


def test_signal_lab_returns_regime():
    m1 = _make_rates(60)
    m5 = _make_rates(30)
    lab = compute_signal_lab(m1, m5, 4005.0, 2.5, 4010.0, 3990.0, 15.0, 12.0)
    assert lab.regime
    assert isinstance(lab.signals, list)


def test_calculate_advanced_metrics():
    from mt5_connector import calculate_advanced_metrics
    m1 = _make_rates(120, base=2300.0)
    res = calculate_advanced_metrics(m1, 2305.0, "Europe/Prague")
    assert "adr_exhaustion_pct" in res
    assert "dist_asian_high" in res
    assert "dist_asian_low" in res
    assert "dist_london_high" in res
    assert "dist_london_low" in res
    assert res["adr_exhaustion_pct"] >= 0.0

