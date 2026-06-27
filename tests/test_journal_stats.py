import csv
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from config import RISK
from journal_stats import compute_session_stats
from mt5_connector import AccountSnapshot, PositionInfo


def _account(equity: float = 25180.0, daily_start: float = 25000.0) -> AccountSnapshot:
    return AccountSnapshot(
        login=1,
        company="Test",
        balance=25000.0,
        equity=equity,
        margin=100.0,
        free_margin=24900.0,
        daily_start_balance=daily_start,
        daily_drawdown_usd=0.0,
        daily_drawdown_pct=0.8,
        trailing_max_equity=25200.0,
        trailing_drawdown_usd=20.0,
        trailing_drawdown_pct=0.08,
        is_critical=False,
        connected=True,
    )


def test_compute_session_stats_pnl_and_open(tmp_path: Path):
    tz = ZoneInfo(RISK.timezone)
    now = datetime(2026, 6, 27, 15, 0, tzinfo=tz)
    journal = tmp_path / "journal.csv"
    with open(journal, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp", "event", "symbol", "profit"])
        w.writeheader()
        w.writerow({"timestamp": "2026-06-27T10:00:00", "event": "close", "symbol": "XAUUSD", "profit": "+120"})
        w.writerow({"timestamp": "2026-06-27T11:00:00", "event": "close", "symbol": "XAUUSD", "profit": "-40"})

    positions = [
        PositionInfo(
            ticket=1,
            symbol="XAUUSD",
            type=0,
            volume=0.1,
            profit=42.0,
            price_open=2650.0,
            price_current=2654.2,
            sl=0,
            tp=0,
            rrr=1.2,
        )
    ]
    stats = compute_session_stats(_account(), positions, journal_path=journal, now=now)

    assert stats.pnl_today_usd == pytest.approx(180.0)
    assert stats.open_pnl_usd == pytest.approx(42.0)
    assert stats.winrate_pct == pytest.approx(50.0)
    assert stats.trades_count == 2
    assert stats.wins == 1
    assert stats.losses == 1
