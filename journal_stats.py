"""Session statistics from trade journal and live account snapshot."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import RISK, TRADE_JOURNAL_PATH
from mt5_connector import AccountSnapshot, PositionInfo


@dataclass(frozen=True)
class SessionStats:
    winrate_pct: float | None
    pnl_today_usd: float
    dd_pct: float
    open_pnl_usd: float
    trades_count: int
    wins: int
    losses: int


def _parse_profit(value: str) -> float | None:
    if not value or value.strip() in ("—", "-", ""):
        return None
    cleaned = value.strip().replace("$", "").replace(",", "").replace("+", "")
    try:
        return float(cleaned)
    except ValueError:
        return None


def _journal_rows_today(path: Path, now: datetime, tz: ZoneInfo) -> list[dict]:
    if not path.exists():
        return []
    today = now.astimezone(tz).date()
    rows: list[dict] = []
    try:
        with open(path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                ts = row.get("timestamp", "")
                if not ts:
                    continue
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=tz)
                    else:
                        dt = dt.astimezone(tz)
                    if dt.date() == today:
                        rows.append(row)
                except ValueError:
                    continue
    except OSError:
        return []
    return rows


def compute_session_stats(
    account: AccountSnapshot | None,
    positions: list[PositionInfo] | None,
    journal_path: Path | None = None,
    now: datetime | None = None,
) -> SessionStats:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    path = journal_path or TRADE_JOURNAL_PATH

    open_pnl = sum(p.profit for p in (positions or []))
    dd_pct = account.daily_drawdown_pct if account else 0.0

    if account:
        pnl_today = account.equity - account.daily_start_balance
    else:
        pnl_today = 0.0

    rows = _journal_rows_today(path, now, tz)
    closed_profits: list[float] = []
    for row in rows:
        evt = (row.get("event") or "").lower()
        if evt not in ("close", "closed", "exit", "deal"):
            profit = _parse_profit(row.get("profit", ""))
            if profit is not None and evt:
                closed_profits.append(profit)
            continue
        profit = _parse_profit(row.get("profit", ""))
        if profit is not None:
            closed_profits.append(profit)

    if not closed_profits:
        for row in rows:
            profit = _parse_profit(row.get("profit", ""))
            if profit is not None:
                closed_profits.append(profit)

    wins = sum(1 for p in closed_profits if p > 0)
    losses = sum(1 for p in closed_profits if p < 0)
    total = wins + losses
    winrate = round(wins / total * 100, 1) if total > 0 else None

    return SessionStats(
        winrate_pct=winrate,
        pnl_today_usd=pnl_today,
        dd_pct=dd_pct,
        open_pnl_usd=open_pnl,
        trades_count=total,
        wins=wins,
        losses=losses,
    )
