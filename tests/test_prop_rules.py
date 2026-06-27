import pytest

from prop_rules import PropState, save_state, load_state, compute_drawdowns


def test_prop_state_persist(tmp_path, monkeypatch):
    import prop_rules

    path = tmp_path / "prop_state.json"
    monkeypatch.setattr(prop_rules, "PROP_STATE_PATH", path)
    state = PropState("2026-06-27", 100_000, 100_000, 0)
    save_state(state)
    loaded = load_state(50_000)
    assert loaded.daily_start_equity == 100_000


def test_trailing_drawdown():
    state = PropState("2026-06-27", 100_000, 105_000, 0)
    dd = compute_drawdowns(103_000, state)
    assert dd.trailing_drawdown_usd == 2000
