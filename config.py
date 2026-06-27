"""Central configuration for Quantum HUD Trading Dashboard."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from mt5_finder import find_mt5_terminal

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)

TRADE_JOURNAL_PATH = LOGS_DIR / "trade_journal.csv"


@dataclass(frozen=True)
class MT5Config:
    path: str | None
    login: int | None
    password: str | None
    server: str | None
    expected_account: int | None
    expected_company: str
    symbol: str
    dxy_symbol: str


@dataclass(frozen=True)
class AccountConfig:
    starting_balance: float = 25_000.0
    daily_drawdown_limit_pct: float = 3.0
    trailing_drawdown_limit_pct: float = 6.0
    default_risk_pct: float = 1.0


@dataclass(frozen=True)
class IndicatorConfig:
    atr_period: int = 14
    atr_impulse_multiplier: float = 2.5
    bb_period: int = 20
    bb_std: float = 2.0
    bb_squeeze_percentile: float = 10.0
    mtf_ema_period: int = 21
    correlation_period: int = 20
    correlation_threshold: float = -0.7


@dataclass(frozen=True)
class RiskConfig:
    spread_warning_multiplier: float = 1.5
    spread_median_window: int = 100
    news_buffer_minutes: int = 30
    golden_window_start_hour: int = 14
    golden_window_end_hour: int = 18
    timezone: str = "Europe/Prague"


@dataclass(frozen=True)
class MacroConfig:
    lookback_hours: int = 24
    lookahead_days: int = 7
    max_events_display: int = 24
    max_events_focus_day: int = 5
    ff_cache_ttl_sec: int = 3600


@dataclass(frozen=True)
class UIConfig:
    refresh_interval_ms: int = 1000
    chart_bars_m1: int = 120
    chart_bars_m5: int = 120
    chart_bars_m15: int = 80
    hud_tier_default: str = "trade"
    neon_cyan: str = "#00FFCC"
    neon_red: str = "#FF3366"
    bg_dark: str = "#0A0E17"
    panel_bg: str = "#111827"


@dataclass(frozen=True)
class TestConfig:
    snapshot_path: Path
    m1_bar_seconds: float  # wall-clock seconds per replayed M1 bar
    replay_speed: float  # optional multiplier on top of m1_bar_seconds
    replay_loop: bool
    scenario: str


@dataclass(frozen=True)
class SafetyConfig:
    auto_kill_on_critical: bool = False
    kill_confirm_clicks: int = 2
    kill_confirm_seconds: float = 3.0
    sl_mode: str = "atr"
    sl_atr_multiplier: float = 1.5
    sl_points: float = 0.0
    sl_pct: float = 0.0
    slippage_warn_points: float = 5.0


def _resolve_mt5_path() -> str | None:
    env_path = os.getenv("MT5_PATH", "").strip()
    if env_path and Path(env_path).exists():
        return env_path
    found = find_mt5_terminal()
    return str(found) if found else None


def _env_float(name: str, default: float) -> float:
    raw = (os.getenv(name) or "").strip().replace("_", "").replace(",", "")
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


HUD_VERSION = "0.14.0"

HUD_MODE = (os.getenv("HUD_MODE") or "live").strip().lower()


def _env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


MT5 = MT5Config(
    path=_resolve_mt5_path(),
    login=int(os.getenv("MT5_LOGIN")) if os.getenv("MT5_LOGIN") else None,
    password=os.getenv("MT5_PASSWORD") or None,
    server=os.getenv("MT5_SERVER") or None,
    expected_account=int(os.getenv("MT5_EXPECTED_ACCOUNT"))
    if os.getenv("MT5_EXPECTED_ACCOUNT")
    else None,
    expected_company=os.getenv("MT5_EXPECTED_COMPANY", "ForTraders"),
    symbol=os.getenv("SYMBOL", "XAUUSD"),
    dxy_symbol=os.getenv("DXY_SYMBOL", "USDX"),
)

ACCOUNT = AccountConfig(
    starting_balance=_env_float("STARTING_BALANCE", 25_000.0),
)
INDICATORS = IndicatorConfig()
RISK = RiskConfig()
MACRO = MacroConfig()
def _env_tier(name: str, default: str) -> str:
    raw = (os.getenv(name) or default).strip().lower()
    if raw in ("trade", "obchod"):
        return "trade"
    if raw in ("prep", "priprava", "příprava"):
        return "prep"
    if raw in ("detail", "detaily"):
        return "detail"
    return default


UI = UIConfig(
    hud_tier_default=_env_tier("HUD_TIER", "trade"),
)
TEST = TestConfig(
    snapshot_path=BASE_DIR / (os.getenv("TEST_SNAPSHOT") or "test_data/default_snapshot.json"),
    m1_bar_seconds=_env_float("TEST_M1_BAR_SECONDS", 30.0),
    replay_speed=_env_float("TEST_REPLAY_SPEED", 1.0),
    replay_loop=_env_bool("TEST_REPLAY_LOOP", True),
    scenario=(os.getenv("TEST_SCENARIO") or "healthy").strip().lower(),
)
SAFETY = SafetyConfig(
    auto_kill_on_critical=_env_bool("AUTO_KILL_ON_CRITICAL", False),
    kill_confirm_clicks=int(_env_float("KILL_CONFIRM_CLICKS", 2)),
    kill_confirm_seconds=_env_float("KILL_CONFIRM_SECONDS", 3.0),
    sl_mode=(os.getenv("SL_MODE") or "atr").strip().lower(),
    sl_atr_multiplier=_env_float("SL_ATR_MULTIPLIER", 1.5),
    sl_points=_env_float("SL_POINTS", 0.0),
    sl_pct=_env_float("SL_PCT", 0.0),
    slippage_warn_points=_env_float("SLIPPAGE_WARN_POINTS", 5.0),
)

DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
