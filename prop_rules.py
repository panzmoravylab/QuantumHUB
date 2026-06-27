"""
Prop firm drawdown rules — persistent baselines and DD computation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from config import ACCOUNT, LOGS_DIR, RISK

logger = logging.getLogger(__name__)

PROP_STATE_PATH = LOGS_DIR / "prop_state.json"


@dataclass
class PropState:
    daily_date: str
    daily_start_equity: float
    trailing_max_equity: float
    trades_today: int = 0

    @classmethod
    def empty(cls, equity: float) -> PropState:
        today = datetime.now(ZoneInfo(RISK.timezone)).date().isoformat()
        base = equity if equity > 0 else ACCOUNT.starting_balance
        return cls(
            daily_date=today,
            daily_start_equity=base,
            trailing_max_equity=base,
            trades_today=0,
        )


@dataclass
class DrawdownResult:
    daily_start_balance: float
    trailing_max_equity: float
    daily_drawdown_usd: float
    daily_drawdown_pct: float
    trailing_drawdown_usd: float
    trailing_drawdown_pct: float
    is_critical: bool


def load_state(default_equity: float) -> PropState:
    if not PROP_STATE_PATH.exists():
        return PropState.empty(default_equity)
    try:
        raw = json.loads(PROP_STATE_PATH.read_text(encoding="utf-8"))
        return PropState(
            daily_date=str(raw.get("daily_date", "")),
            daily_start_equity=float(raw.get("daily_start_equity", default_equity)),
            trailing_max_equity=float(raw.get("trailing_max_equity", default_equity)),
            trades_today=int(raw.get("trades_today", 0)),
        )
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning("prop_state load failed: %s", exc)
        return PropState.empty(default_equity)


def save_state(state: PropState) -> None:
    try:
        PROP_STATE_PATH.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning("prop_state save failed: %s", exc)


def update_baselines(state: PropState, equity: float, now: datetime | None = None) -> PropState:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    today = now.astimezone(tz).date().isoformat()

    if state.daily_date != today:
        state = PropState(
            daily_date=today,
            daily_start_equity=equity,
            trailing_max_equity=max(state.trailing_max_equity, equity),
            trades_today=0,
        )
    else:
        state.trailing_max_equity = max(state.trailing_max_equity, equity)

    save_state(state)
    return state


def record_trade_open(state: PropState) -> PropState:
    state.trades_today += 1
    save_state(state)
    return state


def compute_drawdowns(equity: float, state: PropState) -> DrawdownResult:
    dd_base = ACCOUNT.starting_balance if ACCOUNT.starting_balance > 0 else equity
    daily_dd_usd = max(0.0, state.daily_start_equity - equity)
    daily_dd_pct = (daily_dd_usd / dd_base * 100) if dd_base else 0.0
    trailing_dd_usd = max(0.0, state.trailing_max_equity - equity)
    trailing_dd_pct = (trailing_dd_usd / dd_base * 100) if dd_base else 0.0
    is_critical = (
        daily_dd_pct >= ACCOUNT.daily_drawdown_limit_pct
        or trailing_dd_pct >= ACCOUNT.trailing_drawdown_limit_pct
    )
    return DrawdownResult(
        daily_start_balance=state.daily_start_equity,
        trailing_max_equity=state.trailing_max_equity,
        daily_drawdown_usd=daily_dd_usd,
        daily_drawdown_pct=daily_dd_pct,
        trailing_drawdown_usd=trailing_dd_usd,
        trailing_drawdown_pct=trailing_dd_pct,
        is_critical=is_critical,
    )
