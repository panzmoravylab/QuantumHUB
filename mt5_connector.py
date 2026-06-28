"""
MetaTrader 5 connector — connection, validation, live streaming, shared state.
"""

from __future__ import annotations

import csv
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from config import ACCOUNT, INDICATORS, LOGS_DIR, MACRO, MT5, RISK, SAFETY, TRADE_JOURNAL_PATH, UI
from indicators import IndicatorBundle, build_indicator_bundle, calc_pdh_pdl
from prop_rules import compute_drawdowns, load_state, record_trade_open, update_baselines
from position_tracker import PositionTrackState, calc_position_r, calc_sl_distance_pts, position_side, update_position_tracks
from signal_lab import SignalLabSnapshot, compute_signal_lab

logger = logging.getLogger(__name__)

RELEVANT_MACRO_CURRENCIES = frozenset({"USD", "EUR", "GBP", "XAU", "CHF", "JPY"})

GOLD_SYMBOL_CANDIDATES = ("XAUUSD", "GOLD", "XAUUSD.m", "XAUUSD#", "XAUUSD.")
DXY_SYMBOL_CANDIDATES = ("USDX", "DXY", "USDIDX", "US Dollar Index")


def _macro_relevant_currency(currency: str, importance: int, title: str) -> bool:
    c = (currency or "USD").upper().strip()
    if importance >= 3:
        return c in RELEVANT_MACRO_CURRENCIES or not c
    if importance >= 2:
        return c in ("USD", "EUR")
    return False


@dataclass
class PositionInfo:
    ticket: int
    symbol: str
    volume: float
    profit: float
    sl: float
    tp: float
    price_open: float
    price_current: float
    type: int
    rrr: float | None = None
    r_current: float | None = None
    sl_distance_pts: float | None = None
    side: str = ""


@dataclass
class AccountSnapshot:
    login: int
    company: str
    balance: float
    equity: float
    margin: float
    free_margin: float
    daily_start_balance: float
    daily_drawdown_usd: float
    daily_drawdown_pct: float
    trailing_max_equity: float
    trailing_drawdown_usd: float
    trailing_drawdown_pct: float
    is_critical: bool
    connected: bool
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class SymbolTradeParams:
    tick_value: float
    tick_size: float
    volume_min: float
    volume_max: float
    volume_step: float


@dataclass
class MarketSnapshot:
    symbol: str
    bid: float
    ask: float
    spread_points: float
    spread_median: float
    spread_warning: bool
    last_m1_bar: dict[str, float] | None
    m1_rates: pd.DataFrame
    m5_rates: pd.DataFrame
    m15_rates: pd.DataFrame
    h1_rates: pd.DataFrame
    dxy_m5_rates: pd.DataFrame
    atr: float
    atr_impulse: bool
    current_candle_range: float
    adr_exhaustion_pct: float = 0.0
    current_day_range: float = 0.0
    adr_target: float = 0.0
    dist_asian_high: float = 999.0
    dist_asian_low: float = 999.0
    dist_london_high: float = 999.0
    dist_london_low: float = 999.0
    last_update: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


from compute_log import ComputeLog


@dataclass
class SharedState:
    """Thread-safe shared memory buffer for UI consumption."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    account: AccountSnapshot | None = None
    market: MarketSnapshot | None = None
    positions: list[PositionInfo] = field(default_factory=list)
    alerts: list[str] = field(default_factory=list)
    kill_switch_triggered: bool = False
    kill_switch_message: str = ""
    signal_lab: SignalLabSnapshot | None = None
    indicators: IndicatorBundle | None = None
    bid_history: list[tuple[float, float]] = field(default_factory=list)
    current_velocity: float = 0.0

    def _record_market_price(self, bid: float) -> None:
        now = time.time()
        self.bid_history.append((now, bid))
        cutoff = now - 20.0
        self.bid_history = [(t, b) for t, b in self.bid_history if t >= cutoff]
        
        if len(self.bid_history) < 2:
            self.current_velocity = 0.0
            return
            
        # Target timestamp is 4 seconds ago
        target_ts = now - 4.0
        # Find closest history item
        closest = min(self.bid_history, key=lambda entry: abs(entry[0] - target_ts))
        time_diff = now - closest[0]
        
        if time_diff >= 1.0:
            price_diff = bid - closest[1]
            self.current_velocity = price_diff / 0.01
        else:
            self.current_velocity = 0.0
    compute_log: ComputeLog = field(default_factory=ComputeLog)
    _known_tickets: set[int] = field(default_factory=set)
    trend_strength_history: list[tuple[float, int]] = field(default_factory=list)
    position_tracks: dict[int, PositionTrackState] = field(default_factory=dict)

    def read_position_tracks(self) -> dict[int, PositionTrackState]:
        with self.lock:
            return dict(self.position_tracks)

    def record_trend_strength(self, strength: int, now_ts: float | None = None) -> None:
        now_ts = now_ts or time.monotonic()
        with self.lock:
            if self.trend_strength_history and now_ts - self.trend_strength_history[-1][0] < 55:
                return
            self.trend_strength_history.append((now_ts, int(strength)))
            cutoff = now_ts - 35 * 60
            self.trend_strength_history = [(t, s) for t, s in self.trend_strength_history if t >= cutoff]

    def read_strength_history(self) -> list[tuple[float, int]]:
        with self.lock:
            return list(self.trend_strength_history)

    def update(
        self,
        account: AccountSnapshot | None = None,
        market: MarketSnapshot | None = None,
        positions: list[PositionInfo] | None = None,
        alerts: list[str] | None = None,
        signal_lab: SignalLabSnapshot | None = None,
        indicators: IndicatorBundle | None = None,
    ) -> None:
        with self.lock:
            if account is not None:
                self.account = account
            if market is not None:
                self.market = market
                self._record_market_price(market.bid)
            if positions is not None:
                self.positions = positions
            if alerts is not None:
                self.alerts = alerts
            if signal_lab is not None:
                self.signal_lab = signal_lab
            if indicators is not None:
                self.indicators = indicators

    def read(self) -> dict[str, Any]:
        with self.lock:
            return {
                "account": self.account,
                "market": self.market,
                "positions": list(self.positions),
                "alerts": list(self.alerts),
                "kill_switch_triggered": self.kill_switch_triggered,
                "kill_switch_message": self.kill_switch_message,
                "signal_lab": self.signal_lab,
                "indicators": self.indicators,
                "position_tracks": dict(self.position_tracks),
                "compute_log": self.compute_log.read(),
                "price_velocity": self.current_velocity,
            }


class MT5Connector:
    """Handles MT5 lifecycle, streaming loop, and emergency actions."""

    def __init__(self, state: SharedState | None = None) -> None:
        self.state = state or SharedState()
        self._running = False
        self._thread: threading.Thread | None = None
        self._daily_start_equity: float | None = None
        self._trailing_max_equity: float | None = None
        self._daily_date: datetime | None = None
        self._spread_history: list[float] = []
        self._last_journal_check: float = 0.0
        self._mt5_lock = threading.RLock()
        self._symbol_params: SymbolTradeParams | None = None
        self._connected = False
        self._symbol: str = MT5.symbol
        self._dxy_symbol: str = MT5.dxy_symbol or ""
        self._dxy_available = False
        self._baselines_initialized = False
        self._last_regime: str | None = None
        self._last_dd_critical = False
        self._last_spread_alert = False
        self._last_atr_alert = False
        self._last_tick_log_ts = 0.0
        self._last_reconnect_ts = 0.0
        self._auto_kill_done = False
        self._prop_state = load_state(ACCOUNT.starting_balance)
        self._last_slippage_alert = False

    def get_symbol_trade_params(self) -> SymbolTradeParams | None:
        """Cached symbol info for UI thread — never call mt5 from Dash callbacks."""
        return self._symbol_params

    def is_connected(self) -> bool:
        return self._connected

    def fetch_macro_events(self, now: datetime) -> list:
        """Economic calendar přes MT5 API (musí běžet v MT5 lock)."""
        from risk_engine import NewsEvent
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(RISK.timezone)
        local_now = now.astimezone(tz) if now.tzinfo else now.replace(tzinfo=tz)
        events: list[NewsEvent] = []

        with self._mt5_lock:
            if not mt5.terminal_info():
                return []

            if not hasattr(mt5, "calendar_get"):
                logger.warning(
                    "MetaTrader5 balíček nemá calendar_get — aktualizujte MetaTrader5 pip, "
                    "nebo použijte FF JSON zálohu"
                )
                return []

            start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=2)

            calendar = mt5.calendar_get(start, end)
            if calendar is None:
                logger.warning("MT5 calendar_get failed: %s", mt5.last_error())
                # některé buildy chtějí naive UTC
                calendar = mt5.calendar_get(
                    datetime(start.year, start.month, start.day),
                    datetime(end.year, end.month, end.day, 23, 59),
                )
                if calendar is None:
                    logger.warning("MT5 calendar_get (naive) failed: %s", mt5.last_error())
                    return []

            impact_map = {1: "low", 2: "medium", 3: "high"}
            for item in calendar:
                imp_num = int(getattr(item, "importance", 0) or 0)
                impact = impact_map.get(imp_num, "low")
                title = getattr(item, "event_name", "") or getattr(item, "name", "") or ""
                currency = (getattr(item, "currency", "") or getattr(item, "country", "") or "USD").upper()
                if not _macro_relevant_currency(currency, imp_num, title):
                    continue

                ts = int(getattr(item, "time", 0) or 0)
                if ts <= 0:
                    continue
                event_time = datetime.fromtimestamp(ts, tz=tz)

                events.append(
                    NewsEvent(
                        title=title,
                        currency=currency,
                        impact=impact if impact == "high" else "high" if imp_num >= 3 else impact,
                        event_time=event_time,
                        seconds_until=int((event_time - local_now).total_seconds()),
                    )
                )

        events.sort(key=lambda e: e.event_time)
        today = local_now.date()
        tomorrow = today + timedelta(days=1)
        filtered = [
            e
            for e in events
            if e.event_time.date() <= tomorrow
            and e.impact in ("high", "medium")
        ]
        logger.info("MT5 calendar: %d macro events (MT5)", len(filtered))
        return filtered

    def _cache_symbol_params(self) -> None:
        info = mt5.symbol_info(self._symbol)
        if info is None:
            return
        self._symbol_params = SymbolTradeParams(
            tick_value=float(info.trade_tick_value),
            tick_size=float(info.trade_tick_size),
            volume_min=float(info.volume_min),
            volume_max=float(info.volume_max),
            volume_step=float(info.volume_step),
        )

    def _select_symbol(self, candidates: tuple[str, ...]) -> str | None:
        seen: set[str] = set()
        for name in candidates:
            if not name or name in seen:
                continue
            seen.add(name)
            info = mt5.symbol_info(name)
            if info is not None and mt5.symbol_select(name, True):
                return name
        return None

    # ------------------------------------------------------------------ #
    # Connection
    # ------------------------------------------------------------------ #

    def initialize(self) -> bool:
        """Initialize MT5 terminal connection."""
        with self._mt5_lock:
            return self._initialize_unlocked()

    def _initialize_unlocked(self) -> bool:
        kwargs: dict[str, Any] = {}
        if MT5.path:
            kwargs["path"] = MT5.path
            logger.info("Using MT5 terminal: %s", MT5.path)
        else:
            logger.warning("MT5 path not found — trying default initialize()")

        if not mt5.initialize(**kwargs):
            logger.error("MT5 initialize failed: %s", mt5.last_error())
            return False

        if MT5.login and MT5.password and MT5.server:
            if not mt5.login(MT5.login, MT5.password, MT5.server):
                logger.error("MT5 login failed: %s", mt5.last_error())
                mt5.shutdown()
                return False

        if not self._validate_account():
            return False

        gold_candidates = (MT5.symbol,) + tuple(c for c in GOLD_SYMBOL_CANDIDATES if c != MT5.symbol)
        resolved = self._select_symbol(gold_candidates)
        if not resolved:
            logger.error("Failed to resolve gold symbol (tried %s)", gold_candidates)
            return False
        self._symbol = resolved

        dxy_candidates = tuple(dict.fromkeys([c for c in (MT5.dxy_symbol, *DXY_SYMBOL_CANDIDATES) if c]))
        dxy_resolved = self._select_symbol(dxy_candidates)
        self._dxy_symbol = dxy_resolved or ""
        self._dxy_available = bool(dxy_resolved)
        if not self._dxy_available:
            logger.warning("DXY/USDX symbol not found — correlation gauge disabled")

        self._cache_symbol_params()
        self._connected = True
        logger.info("MT5 connected — symbol %s ready (DXY: %s)", self._symbol, self._dxy_symbol or "N/A")
        self.state.compute_log.insight(
            "mt5",
            "MT5 připojeno",
            f"{self._symbol}"
            + (f" · korelace DXY ({self._dxy_symbol})" if self._dxy_available else ""),
            "ok",
        )
        return True

    def _validate_account(self) -> bool:
        info = mt5.account_info()
        if info is None:
            logger.error("Cannot retrieve account info: %s", mt5.last_error())
            return False

        logger.info(
            "Account: %s | Company: %s | Balance: %.2f | Equity: %.2f",
            info.login,
            info.company,
            info.balance,
            info.equity,
        )

        if MT5.expected_account and info.login != MT5.expected_account:
            logger.warning(
                "Account mismatch: expected %s, got %s",
                MT5.expected_account,
                info.login,
            )

        if MT5.expected_company and MT5.expected_company.lower() not in info.company.lower():
            logger.warning(
                "Company mismatch: expected %s, got %s",
                MT5.expected_company,
                info.company,
            )

        if not self._baselines_initialized:
            self._prop_state = load_state(info.equity)
            self._baselines_initialized = True
        return True

    def shutdown(self) -> None:
        self._running = False
        self._connected = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        with self._mt5_lock:
            mt5.shutdown()
        logger.info("MT5 shutdown complete")

    def reconnect(self) -> bool:
        with self._mt5_lock:
            mt5.shutdown()
            time.sleep(1.0)
            return self._initialize_unlocked()

    # ------------------------------------------------------------------ #
    # Data fetching helpers
    # ------------------------------------------------------------------ #

    def _fetch_rates(self, symbol: str, timeframe: int, count: int) -> pd.DataFrame:
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
        if rates is None or len(rates) == 0:
            return pd.DataFrame()
        df = pd.DataFrame(rates)
        df["time"] = pd.to_datetime(df["time"], unit="s")
        return df

    def _get_spread_points(self, symbol: str) -> tuple[float, float, float]:
        tick = mt5.symbol_info_tick(symbol)
        info = mt5.symbol_info(symbol)
        if tick is None or info is None:
            return 0.0, 0.0, 0.0
        spread = (tick.ask - tick.bid) / info.point if info.point else 0.0
        return tick.bid, tick.ask, spread

    def _calc_atr(self, df: pd.DataFrame, period: int = INDICATORS.atr_period) -> float:
        if len(df) < period + 1:
            return 0.0
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            ),
        )
        if len(tr) < period:
            return float(np.mean(tr)) if len(tr) else 0.0
        return float(np.mean(tr[-period:]))

    def _calc_rrr(self, pos: Any, current: float) -> float | None:
        return calc_position_r(pos.type, pos.price_open, pos.sl, current)

    def _enrich_position(self, p: PositionInfo, current: float) -> PositionInfo:
        r = calc_position_r(p.type, p.price_open, p.sl, current)
        return PositionInfo(
            ticket=p.ticket,
            symbol=p.symbol,
            volume=p.volume,
            profit=p.profit,
            sl=p.sl,
            tp=p.tp,
            price_open=p.price_open,
            price_current=current,
            type=p.type,
            rrr=r,
            r_current=r,
            sl_distance_pts=calc_sl_distance_pts(p.type, p.sl, current),
            side=position_side(p.type),
        )

    def _fetch_positions(self) -> list[PositionInfo]:
        positions = mt5.positions_get(symbol=self._symbol)
        if positions is None:
            return []

        result: list[PositionInfo] = []
        for p in positions:
            tick = mt5.symbol_info_tick(p.symbol)
            current = p.price_current
            if tick is not None:
                current = tick.bid if p.type == mt5.ORDER_TYPE_BUY else tick.ask
            result.append(
                self._enrich_position(
                    PositionInfo(
                        ticket=p.ticket,
                        symbol=p.symbol,
                        volume=p.volume,
                        profit=p.profit,
                        sl=p.sl,
                        tp=p.tp,
                        price_open=p.price_open,
                        price_current=current,
                        type=p.type,
                    ),
                    current,
                )
            )
        return result

    def _build_account_snapshot(self) -> AccountSnapshot:
        info = mt5.account_info()
        if info is None:
            with self.state.lock:
                prev = self.state.account
            if prev:
                return AccountSnapshot(
                    login=prev.login,
                    company=prev.company,
                    balance=prev.balance,
                    equity=prev.equity,
                    margin=prev.margin,
                    free_margin=prev.free_margin,
                    daily_start_balance=prev.daily_start_balance,
                    daily_drawdown_usd=prev.daily_drawdown_usd,
                    daily_drawdown_pct=prev.daily_drawdown_pct,
                    trailing_max_equity=prev.trailing_max_equity,
                    trailing_drawdown_usd=prev.trailing_drawdown_usd,
                    trailing_drawdown_pct=prev.trailing_drawdown_pct,
                    is_critical=prev.is_critical,
                    connected=False,
                )
            return AccountSnapshot(
                login=0,
                company="",
                balance=0,
                equity=0,
                margin=0,
                free_margin=0,
                daily_start_balance=ACCOUNT.starting_balance,
                daily_drawdown_usd=0,
                daily_drawdown_pct=0,
                trailing_max_equity=ACCOUNT.starting_balance,
                trailing_drawdown_usd=0,
                trailing_drawdown_pct=0,
                is_critical=False,
                connected=False,
            )

        if not self._baselines_initialized:
            self._prop_state = load_state(info.equity)
            self._baselines_initialized = True

        self._prop_state = update_baselines(self._prop_state, info.equity)
        dd = compute_drawdowns(info.equity, self._prop_state)

        return AccountSnapshot(
            login=info.login,
            company=info.company,
            balance=info.balance,
            equity=info.equity,
            margin=info.margin,
            free_margin=info.margin_free,
            daily_start_balance=dd.daily_start_balance,
            daily_drawdown_usd=dd.daily_drawdown_usd,
            daily_drawdown_pct=dd.daily_drawdown_pct,
            trailing_max_equity=dd.trailing_max_equity,
            trailing_drawdown_usd=dd.trailing_drawdown_usd,
            trailing_drawdown_pct=dd.trailing_drawdown_pct,
            is_critical=dd.is_critical,
            connected=True,
        )

    def _build_market_snapshot(self) -> MarketSnapshot:
        bid, ask, spread = self._get_spread_points(self._symbol)

        self._spread_history.append(spread)
        if len(self._spread_history) > RISK.spread_median_window:
            self._spread_history = self._spread_history[-RISK.spread_median_window :]

        spread_median = float(np.median(self._spread_history)) if self._spread_history else spread
        spread_warning = spread > spread_median * RISK.spread_warning_multiplier if spread_median else False

        m1 = self._fetch_rates(self._symbol, mt5.TIMEFRAME_M1, UI.chart_bars_m1)
        m5 = self._fetch_rates(self._symbol, mt5.TIMEFRAME_M5, UI.chart_bars_m5)
        m15 = self._fetch_rates(self._symbol, mt5.TIMEFRAME_M15, UI.chart_bars_m15)
        h1 = self._fetch_rates(self._symbol, mt5.TIMEFRAME_H1, 50)
        dxy = (
            self._fetch_rates(self._dxy_symbol, mt5.TIMEFRAME_M5, UI.chart_bars_m5)
            if self._dxy_available
            else pd.DataFrame()
        )

        if bid <= 0 and not m1.empty:
            bid = float(m1.iloc[-1]["close"])
            ask = bid

        atr = self._calc_atr(m1) if not m1.empty else 0.0
        current_range = 0.0
        last_bar: dict[str, float] | None = None
        atr_impulse = False

        if not m1.empty:
            last = m1.iloc[-1]
            current_range = float(last["high"] - last["low"])
            last_bar = {
                "open": float(last["open"]),
                "high": float(last["high"]),
                "low": float(last["low"]),
                "close": float(last["close"]),
            }
            if atr > 0 and current_range > INDICATORS.atr_impulse_multiplier * atr:
                atr_impulse = True

        adv = calculate_advanced_metrics(m1, bid, RISK.timezone)
        return MarketSnapshot(
            symbol=self._symbol,
            bid=bid,
            ask=ask,
            spread_points=spread,
            spread_median=spread_median,
            spread_warning=spread_warning,
            last_m1_bar=last_bar,
            m1_rates=m1,
            m5_rates=m5,
            m15_rates=m15,
            h1_rates=h1,
            dxy_m5_rates=dxy,
            atr=atr,
            atr_impulse=atr_impulse,
            current_candle_range=current_range,
            adr_exhaustion_pct=adv["adr_exhaustion_pct"],
            current_day_range=adv["current_day_range"],
            adr_target=adv["adr_target"],
            dist_asian_high=adv["dist_asian_high"],
            dist_asian_low=adv["dist_asian_low"],
            dist_london_high=adv["dist_london_high"],
            dist_london_low=adv["dist_london_low"],
        )

    def _collect_alerts(self, account: AccountSnapshot, market: MarketSnapshot) -> list[str]:
        alerts: list[str] = []
        if account.is_critical:
            alerts.append("[KRITICKÉ] Blízkost prop limitu — zvažte ukončení obchodů.")
        if market.atr_impulse:
            alerts.append("[ANOMÁLIE] Liquidity sweep / ATR impulz detekován.")
        if market.spread_warning:
            alerts.append("[BARRIER] Vysoké transakční náklady — exekuce pozastavena.")
        if self._last_slippage_alert:
            alerts.append("[SKLUZ] Poslední fill nad tolerancí slippage.")
        return alerts

    # ------------------------------------------------------------------ #
    # Trade journal
    # ------------------------------------------------------------------ #

    def _ensure_journal_header(self) -> None:
        if TRADE_JOURNAL_PATH.exists():
            return
        with open(TRADE_JOURNAL_PATH, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "timestamp",
                    "event",
                    "ticket",
                    "symbol",
                    "volume",
                    "profit",
                    "spread",
                    "atr",
                    "sl",
                    "tp",
                ]
            )

    def _log_journal_event(
        self,
        event: str,
        ticket: int,
        symbol: str,
        volume: float,
        profit: float,
        spread: float,
        atr: float,
        sl: float = 0.0,
        tp: float = 0.0,
    ) -> None:
        self._ensure_journal_header()
        with open(TRADE_JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    datetime.now(timezone.utc).isoformat(),
                    event,
                    ticket,
                    symbol,
                    volume,
                    profit,
                    spread,
                    atr,
                    sl,
                    tp,
                ]
            )

    def _track_position_changes(self, positions: list[PositionInfo], market: MarketSnapshot) -> None:
        current_tickets = {p.ticket for p in positions}
        with self.state.lock:
            known = set(self.state._known_tickets)
        new_tickets = current_tickets - known
        closed_tickets = known - current_tickets

        for p in positions:
            if p.ticket in new_tickets:
                self._prop_state = record_trade_open(self._prop_state)
                self._check_slippage(p)
                self._log_journal_event(
                    "OPEN",
                    p.ticket,
                    p.symbol,
                    p.volume,
                    p.profit,
                    market.spread_points,
                    market.atr,
                    p.sl,
                    p.tp,
                )

        if closed_tickets:
            deals = mt5.history_deals_get(datetime.now().replace(hour=0, minute=0, second=0), datetime.now())
            if deals:
                for ticket in closed_tickets:
                    for d in deals:
                        if d.position_id == ticket or d.order == ticket:
                            self._log_journal_event(
                                "CLOSE",
                                ticket,
                                d.symbol,
                                d.volume,
                                d.profit,
                                market.spread_points,
                                market.atr,
                            )
                            break

        with self.state.lock:
            self.state._known_tickets = current_tickets

    def _check_slippage(self, pos: Any) -> None:
        info = mt5.symbol_info(pos.symbol)
        tick = mt5.symbol_info_tick(pos.symbol)
        if info is None or tick is None or not info.point:
            return
        expected = tick.ask if pos.type == mt5.ORDER_TYPE_BUY else tick.bid
        slip_pts = abs(pos.price_open - expected) / info.point
        if slip_pts > SAFETY.slippage_warn_points:
            self._last_slippage_alert = True
            self.state.compute_log.insight(
                "market",
                "Skluz při fillu",
                f"{slip_pts:.1f} bodů (limit {SAFETY.slippage_warn_points:.0f}p)",
                "warn",
            )
        else:
            self._last_slippage_alert = False

    # ------------------------------------------------------------------ #
    # Kill switch
    # ------------------------------------------------------------------ #

    def kill_switch_close_all(self) -> int:
        """Emergency close all open positions for the configured symbol."""
        with self._mt5_lock:
            return self._kill_switch_close_all_unlocked()

    def _kill_switch_close_all_unlocked(self) -> int:
        positions = mt5.positions_get(symbol=self._symbol)
        if not positions:
            positions = mt5.positions_get()
        if not positions:
            return 0

        closed = 0
        for pos in positions:
            tick = mt5.symbol_info_tick(pos.symbol)
            if tick is None:
                continue

            if pos.type == mt5.ORDER_TYPE_BUY:
                order_type = mt5.ORDER_TYPE_SELL
                price = tick.bid
            else:
                order_type = mt5.ORDER_TYPE_BUY
                price = tick.ask

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": order_type,
                "position": pos.ticket,
                "price": price,
                "deviation": 20,
                "magic": pos.magic,
                "comment": "QUANTUM_HUD_KILL_SWITCH",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }
            result = mt5.order_send(request)
            if result and result.retcode == mt5.TRADE_RETCODE_DONE:
                closed += 1
                logger.warning("Kill switch closed position %s", pos.ticket)
            else:
                logger.error("Kill switch failed for %s: %s", pos.ticket, result)

        with self.state.lock:
            self.state.kill_switch_triggered = True
            self.state.kill_switch_message = f"Kill switch executed — {closed} position(s) closed"
        return closed

    # ------------------------------------------------------------------ #
    # Streaming loop
    # ------------------------------------------------------------------ #

    def _engine_log_tick(
        self,
        account: AccountSnapshot,
        market: MarketSnapshot,
        signal_lab: SignalLabSnapshot,
        alerts: list[str],
    ) -> None:
        log = self.state.compute_log
        if signal_lab.regime != self._last_regime:
            self._last_regime = signal_lab.regime
            log.insight(
                "signal",
                f"Režim · {signal_lab.regime}",
                signal_lab.headline,
                "info",
            )

        critical = account.is_critical
        if critical and not self._last_dd_critical:
            log.insight(
                "risk",
                "Prop DD — kritická zóna",
                f"Denní {account.daily_drawdown_pct:.1f}% · "
                f"Trailing {account.trailing_drawdown_pct:.1f}%",
                "warn",
            )
        self._last_dd_critical = critical

        for a in alerts:
            upper = a.upper()
            if "SPREAD" in upper and not self._last_spread_alert:
                self._last_spread_alert = True
                log.insight(
                    "market",
                    "Spread nad normálem",
                    a.replace("[WARN] ", "").replace("[ERROR] ", ""),
                    "warn",
                )
            elif "ATR" in upper and not self._last_atr_alert:
                self._last_atr_alert = True
                log.insight(
                    "market",
                    "Volatilita (ATR impulse)",
                    "Neočekávaný pohyb — snižte size nebo čekejte.",
                    "warn",
                )

        if market and not market.spread_warning:
            self._last_spread_alert = False
        if market and not market.atr_impulse:
            self._last_atr_alert = False

        now_ts = time.monotonic()
        if now_ts - self._last_tick_log_ts >= 12.0:
            self._last_tick_log_ts = now_ts
            log.cmd(
                "tick",
                f"{market.bid:.2f} · spr {market.spread_points:.0f}p · "
                f"ATR {market.atr:.2f} · DD {account.daily_drawdown_pct:.1f}%",
                "info",
            )

    def _poll_once(self) -> None:
        if not self._mt5_lock.acquire(timeout=2.0):
            logger.warning("MT5 poll skipped — API lock busy")
            return
        try:
            if not mt5.terminal_info():
                logger.warning("MT5 terminal disconnected")
                self._connected = False
                now_ts = time.monotonic()
                if now_ts - self._last_reconnect_ts >= 30.0:
                    self._last_reconnect_ts = now_ts
                    self.state.compute_log.cmd("mt5", "Pokus o reconnect…", "warn")
                    if self.reconnect():
                        self.state.compute_log.insight(
                            "mt5",
                            "MT5 reconnect OK",
                            "Spojení obnoveno automaticky.",
                            "ok",
                        )
                        return
                    self.state.compute_log.insight(
                        "mt5",
                        "Reconnect selhal",
                        "Spusťte MetaTrader 5 ručně.",
                        "err",
                    )
                self.state.compute_log.insight(
                    "mt5",
                    "MT5 odpojeno",
                    "Spusťte MetaTrader 5 a přihlaste se k účtu.",
                    "err",
                )
                with self.state.lock:
                    prev = self.state.account
                if prev:
                    self.state.update(
                        account=AccountSnapshot(
                            login=prev.login,
                            company=prev.company,
                            balance=prev.balance,
                            equity=prev.equity,
                            margin=prev.margin,
                            free_margin=prev.free_margin,
                            daily_start_balance=prev.daily_start_balance,
                            daily_drawdown_usd=prev.daily_drawdown_usd,
                            daily_drawdown_pct=prev.daily_drawdown_pct,
                            trailing_max_equity=prev.trailing_max_equity,
                            trailing_drawdown_usd=prev.trailing_drawdown_usd,
                            trailing_drawdown_pct=prev.trailing_drawdown_pct,
                            is_critical=prev.is_critical,
                            connected=False,
                        ),
                        alerts=["[CHYBA] MT5 odpojeno — spusťte terminál a obnovte stránku."],
                    )
                else:
                    self.state.update(
                        alerts=["[CHYBA] MT5 odpojeno — spusťte terminál a obnovte stránku."],
                    )
                return

            self._cache_symbol_params()
            account = self._build_account_snapshot()
            market = self._build_market_snapshot()
            positions = self._fetch_positions()
            alerts = self._collect_alerts(account, market)

            if (
                account.is_critical
                and SAFETY.auto_kill_on_critical
                and not self._auto_kill_done
            ):
                self._auto_kill_done = True
                closed = self._kill_switch_close_all_unlocked()
                msg = f"Auto kill-switch — zavřeno {closed} pozic (CRITICAL DD)"
                alerts.append(f"[KRITICKÉ] {msg}")
                self.state.compute_log.insight("risk", "Auto kill-switch", msg, "err")
                with self.state.lock:
                    self.state.kill_switch_triggered = True
                    self.state.kill_switch_message = msg
                positions = self._fetch_positions()

            self._track_position_changes(positions, market)

            with self.state.lock:
                self.state.position_tracks = update_position_tracks(
                    positions, self.state.position_tracks
                )

            pdh, pdl = calc_pdh_pdl(
                market.m1_rates if len(market.m1_rates) > 100 else market.h1_rates
            )
            signal_lab = compute_signal_lab(
                market.m1_rates,
                market.m5_rates,
                market.bid,
                market.atr,
                pdh,
                pdl,
                market.spread_points,
                market.spread_median,
            )
            indicator_bundle = build_indicator_bundle(
                market.m1_rates,
                market.m5_rates,
                market.m15_rates,
                market.h1_rates,
                market.dxy_m5_rates,
            )

            self.state.update(
                account=account,
                market=market,
                positions=positions,
                alerts=alerts,
                signal_lab=signal_lab,
                indicators=indicator_bundle,
            )
            self._engine_log_tick(account, market, signal_lab, alerts)
            self._connected = True
        finally:
            self._mt5_lock.release()

    def start_streaming(self, interval: float = 0.5) -> None:
        """Start background polling thread."""
        if self._running:
            return
        self._running = True

        def _loop() -> None:
            while self._running:
                try:
                    self._poll_once()
                except Exception:
                    logger.exception("Error in MT5 polling loop")
                time.sleep(interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="MT5Stream")
        self._thread.start()
        logger.info("MT5 streaming started (interval=%.1fs)", interval)

    def stop_streaming(self) -> None:
        self._running = False


def run_console_stream() -> None:
    """Phase 1 entry point — console M1 streaming with drawdown."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    connector = MT5Connector()

    if not connector.initialize():
        print("Failed to connect to MT5. Ensure terminal is running.")
        return

    print(f"Streaming {MT5.symbol} M1 rates. Press Ctrl+C to stop.\n")
    try:
        while True:
            connector._poll_once()
            state = connector.state.read()
            account = state["account"]
            market = state["market"]
            if account and market:
                last = market.last_m1_bar or {}
                print(
                    f"[{datetime.now().strftime('%H:%M:%S')}] "
                    f"O:{last.get('open', 0):.2f} H:{last.get('high', 0):.2f} "
                    f"L:{last.get('low', 0):.2f} C:{last.get('close', 0):.2f} | "
                    f"Spread:{market.spread_points:.1f}p ATR:{market.atr:.2f} | "
                    f"Equity:${account.equity:.2f} DD:{account.daily_drawdown_pct:.2f}% "
                    f"(${account.daily_drawdown_usd:.2f})"
                )
                for alert in state["alerts"]:
                    print(f"  ⚠ {alert}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        connector.shutdown()


def calculate_advanced_metrics(
    m1_rates: pd.DataFrame,
    bid: float,
    tz_name: str,
) -> dict[str, float]:
    """
    Calculate ADR Exhaustion and Session Liquidity Sweep points.
    """
    res = {
        "adr_exhaustion_pct": 0.0,
        "current_day_range": 0.0,
        "adr_target": 25.0,
        "dist_asian_high": 999.0,
        "dist_asian_low": 999.0,
        "dist_london_high": 999.0,
        "dist_london_low": 999.0,
    }
    if m1_rates.empty:
        return res
        
    try:
        from zoneinfo import ZoneInfo
        from datetime import timezone
        
        tz = ZoneInfo(tz_name)
        times_local = pd.to_datetime(m1_rates["time"]).dt.tz_localize(timezone.utc).dt.tz_convert(tz)
        current_bar_time = times_local.iloc[-1]
        current_date = current_bar_time.date()
        
        day_mask = times_local.dt.date == current_date
        day_bars = m1_rates[day_mask]
        
        if not day_bars.empty:
            daily_high = float(day_bars["high"].max())
            daily_low = float(day_bars["low"].min())
            current_range = daily_high - daily_low
            res["current_day_range"] = current_range
            
            # Gold ADR target (25.0 points)
            adr_target = 25.0
            res["adr_target"] = adr_target
            res["adr_exhaustion_pct"] = min(100.0, (current_range / adr_target) * 100.0)
            
            # Asian Session: 00:00 to 08:00 CEST
            asia_mask = (times_local.dt.date == current_date) & (times_local.dt.hour >= 0) & (times_local.dt.hour < 8)
            asia_bars = m1_rates[asia_mask]
            if not asia_bars.empty:
                asia_high = float(asia_bars["high"].max())
                asia_low = float(asia_bars["low"].min())
                res["dist_asian_high"] = asia_high - bid
                res["dist_asian_low"] = bid - asia_low
                
            # London Session: 08:00 to 16:00 CEST
            london_mask = (times_local.dt.date == current_date) & (times_local.dt.hour >= 8) & (times_local.dt.hour < 16)
            london_bars = m1_rates[london_mask]
            if not london_bars.empty:
                london_high = float(london_bars["high"].max())
                london_low = float(london_bars["low"].min())
                res["dist_london_high"] = london_high - bid
                res["dist_london_low"] = bid - london_low
    except Exception as e:
        logger.warning("Error calculating advanced metrics: %s", e)
        
    return res


if __name__ == "__main__":
    run_console_stream()
