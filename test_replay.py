"""
Test replay engine — full HUD simulation from JSON snapshot without MT5.

Used when HUD_MODE=test. Replays captured OHLC, simulates positions, spread spikes,
drawdown scenarios, and kill switch (in-memory only).
"""

from __future__ import annotations

import csv
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import MetaTrader5 as mt5
import numpy as np
import pandas as pd

from compute_log import ComputeLog
from config import ACCOUNT, INDICATORS, RISK, SAFETY, TEST, UI, TRADE_JOURNAL_PATH
from indicators import build_indicator_bundle, calc_pdh_pdl
from prop_rules import PropState, compute_drawdowns, load_state, update_baselines
from mt5_connector import (
    AccountSnapshot,
    MarketSnapshot,
    PositionInfo,
    SharedState,
    SymbolTradeParams,
    calculate_advanced_metrics,
)
from position_tracker import calc_position_r, calc_sl_distance_pts, position_side, update_position_tracks
from signal_lab import SignalLabSnapshot, compute_signal_lab

logger = logging.getLogger(__name__)


def _rates_to_df(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    for col in ("open", "high", "low", "close", "tick_volume", "real_volume", "spread"):
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


def _slice_rates(df: pd.DataFrame, end_ts: pd.Timestamp, count: int) -> pd.DataFrame:
    if df.empty:
        return df
    subset = df[df["time"] <= end_ts]
    if subset.empty:
        return df.head(count).copy()
    return subset.tail(count).copy()


class TestReplayConnector:
    """Drop-in replacement for MT5Connector when HUD_MODE=test."""

    def __init__(self, state: SharedState | None = None) -> None:
        self.state = state or SharedState()
        self._running = False
        self._thread: threading.Thread | None = None
        self._connected = False
        self._snapshot: dict[str, Any] = {}
        self._symbol_params: SymbolTradeParams | None = None
        self._symbol: str = "XAUUSD"
        self._dxy_symbol: str = ""
        self._m1_full = pd.DataFrame()
        self._m5_full = pd.DataFrame()
        self._m15_full = pd.DataFrame()
        self._h1_full = pd.DataFrame()
        self._dxy_full = pd.DataFrame()
        self._replay_index = 0
        self._spread_history: list[float] = []
        self._positions: list[PositionInfo] = []
        self._prop_state = load_state(ACCOUNT.starting_balance)
        self._poll_count = 0
        self._last_regime: str | None = None
        self._last_dd_critical = False
        self._last_spread_alert = False
        self._last_atr_alert = False
        self._last_tick_log_ts = 0.0
        self._base_spread = 15.0
        self._replay_accumulator = 0.0
        self._initial_position_profit = 0.0

    def get_symbol_trade_params(self) -> SymbolTradeParams | None:
        return self._symbol_params

    def is_connected(self) -> bool:
        return self._connected

    def initialize(self) -> bool:
        path = TEST.snapshot_path
        if not path.exists():
            logger.error("Test snapshot not found: %s", path)
            self.state.compute_log.insight(
                "test",
                "Snapshot chybí",
                f"Soubor {path.name} neexistuje — spusťte Ulozit_test_data.bat",
                "err",
            )
            return False

        try:
            self._snapshot = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.error("Failed to load test snapshot: %s", exc)
            return False

        meta = self._snapshot.get("meta", {})
        self._symbol = meta.get("symbol", "XAUUSD")
        self._dxy_symbol = meta.get("dxy_symbol", "")

        params = self._snapshot.get("symbol_params", {})
        tick_val = float(params.get("tick_value", 1.0))
        if "XAUUSD" in self._symbol.upper() or "GOLD" in self._symbol.upper():
            if tick_val == 0.1:
                tick_val = 1.0  # Force correct tick value for standard gold contracts
        self._symbol_params = SymbolTradeParams(
            tick_value=tick_val,
            tick_size=float(params.get("tick_size", 0.01)),
            volume_min=float(params.get("volume_min", 0.01)),
            volume_max=float(params.get("volume_max", 100.0)),
            volume_step=float(params.get("volume_step", 0.01)),
        )

        rates = self._snapshot.get("rates", {})
        self._m1_full = _rates_to_df(rates.get("m1", []))
        self._m5_full = _rates_to_df(rates.get("m5", []))
        self._m15_full = _rates_to_df(rates.get("m15", []))
        self._h1_full = _rates_to_df(rates.get("h1", []))
        self._dxy_full = _rates_to_df(rates.get("dxy_m5", []))

        if self._m1_full.empty:
            logger.error("Test snapshot has no M1 data")
            return False

        replay = self._snapshot.get("replay", {})
        
        # Target start date: 15 June 2026 at 08:00 CEST (Europe/Prague timezone)
        try:
            target_tz = ZoneInfo(RISK.timezone)
            target_dt = datetime(2026, 6, 15, 8, 0, 0, tzinfo=target_tz)
            target_ts = pd.Timestamp(target_dt.astimezone(timezone.utc)).tz_localize(None)
            
            # Find closest M1 bar
            diffs = (self._m1_full["time"] - target_ts).abs()
            start_idx = int(diffs.idxmin())
            self._replay_index = min(max(start_idx, UI.chart_bars_m1), len(self._m1_full) - 1)
            logger.info("Test replay starting at date-matched M1 bar index %d (%s local)", self._replay_index, target_dt)
        except Exception as exc:
            logger.warning("Could not match start date 2026-06-15 08:00 CEST in replay data (%s). Falling back.", exc)
            start = int(replay.get("start_index", max(60, len(self._m1_full) // 3)))
            self._replay_index = min(max(start, UI.chart_bars_m1), len(self._m1_full) - 1)

        seed = self._snapshot.get("market_seed", {})
        self._base_spread = float(seed.get("spread_points", 15.0))

        account = self._snapshot.get("account", {})
        equity = float(account.get("equity", ACCOUNT.starting_balance))
        self._prop_state = load_state(equity)

        self._positions = self._load_positions()
        # Recalculate initial positions' profit to match the starting price of the replay
        if not self._m1_full.empty and self._replay_index < len(self._m1_full):
            starting_bar = self._m1_full.iloc[self._replay_index]
            starting_close = float(starting_bar["close"])
            for p in self._positions:
                p.price_current = starting_close
                p.profit = self._calculate_position_profit(p, starting_close)
                p.rrr = self._calc_rrr(p.type, p.price_open, p.sl, p.tp, starting_close)
                p.r_current = p.rrr
                p.sl_distance_pts = calc_sl_distance_pts(p.type, p.sl, starting_close)

        self._initial_position_profit = sum(p.profit for p in self._positions)
        self._apply_scenario_overrides()

        self._connected = True
        logger.info(
            "Test replay loaded — %s (%d M1 bars, start @ %d)",
            path.name,
            len(self._m1_full),
            self._replay_index,
        )
        self.state.compute_log.insight(
            "test",
            "TEST režim aktivní",
            f"{path.name} · M1 bar / {TEST.m1_bar_seconds:.0f}s · pozice {len(self._positions)}",
            "ok",
        )
        return True

    def _load_positions(self) -> list[PositionInfo]:
        result: list[PositionInfo] = []
        base_positions = self._snapshot.get("positions", [])
        
        # If no positions are captured in snapshot, provide a default BUY template
        if not base_positions:
            # Let's check starting close price from M1 rates
            start_price = 2330.0
            if not self._m1_full.empty and self._replay_index < len(self._m1_full):
                start_price = float(self._m1_full.iloc[self._replay_index]["close"])
            
            base_positions = [{
                "ticket": 990001,
                "type": mt5.ORDER_TYPE_BUY,
                "price_open": start_price,
                "sl": start_price - 15.0,
                "tp": start_price + 30.0,
                "volume": 0.15
            }]

        ticket_counter = 990001
        for row in base_positions:
            pos_type = int(row.get("type", 0))
            # Replicate 4 times to simulate order block entry (3-5 positions range)
            for i in range(4):
                price_open = float(row["price_open"])
                price_current = float(row.get("price_current", price_open))
                sl = float(row.get("sl", 0.0))
                tp = float(row.get("tp", 0.0))
                rrr = self._calc_rrr(pos_type, price_open, sl, tp, price_current)
                result.append(
                    PositionInfo(
                        ticket=ticket_counter,
                        symbol=row.get("symbol", self._symbol),
                        volume=0.15,  # Force lotsize to 0.15 per user instruction
                        profit=0.0,
                        sl=sl,
                        tp=tp,
                        price_open=price_open,
                        price_current=price_current,
                        type=pos_type,
                        rrr=rrr,
                        r_current=rrr,
                        sl_distance_pts=calc_sl_distance_pts(pos_type, sl, price_current),
                        side=position_side(pos_type),
                    )
                )
                ticket_counter += 1
        return result

    def _apply_scenario_overrides(self) -> None:
        scenario = TEST.scenario.lower()
        account = self._snapshot.setdefault("account", {})
        base_equity = float(account.get("equity", ACCOUNT.starting_balance))

        if scenario == "critical":
            account["equity"] = base_equity * (1 - ACCOUNT.daily_drawdown_limit_pct / 100 - 0.2)
        elif scenario == "near_limit":
            account["equity"] = base_equity * (1 - ACCOUNT.daily_drawdown_limit_pct / 100 + 0.3)
        elif scenario == "healthy":
            account["equity"] = base_equity

        equity = float(account.get("equity", base_equity))
        self._prop_state = PropState(
            daily_date=self._prop_state.daily_date,
            daily_start_equity=float(account.get("balance", base_equity)),
            trailing_max_equity=max(self._prop_state.trailing_max_equity, equity),
            trades_today=self._prop_state.trades_today,
        )

    def shutdown(self) -> None:
        self._running = False
        self._connected = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)
        logger.info("Test replay shutdown")

    def reconnect(self) -> bool:
        return self.initialize()

    def kill_switch_close_all(self) -> int:
        closed = len(self._positions)
        
        # Log to trade journal
        market = self.state.read().get("market")
        spread = market.spread_points if market else self._base_spread
        atr = market.atr if market else 0.0
        tz = ZoneInfo(RISK.timezone)
        now_dt = datetime.now(tz)
        
        for p in self._positions:
            self._log_journal_event(
                "CLOSE",
                p.ticket,
                p.symbol,
                p.volume,
                p.profit,
                spread,
                atr,
                p.sl,
                p.tp,
                now_dt,
            )

        self._positions = []
        with self.state.lock:
            self.state.kill_switch_triggered = True
            self.state.kill_switch_message = f"[TEST] Kill switch — {closed} simulované pozice zavřeny"
        self.state.compute_log.insight(
            "test",
            "Kill switch (simulace)",
            f"Zavřeno {closed} pozic — bez MT5 order_send",
            "warn",
        )
        return closed

    def _calculate_position_profit(self, p: PositionInfo, price: float) -> float:
        tick_value = self._symbol_params.tick_value if self._symbol_params else 1.0
        tick_size = self._symbol_params.tick_size if self._symbol_params else 0.01
        if p.type == mt5.ORDER_TYPE_BUY:
            price_diff = price - p.price_open
        else:
            price_diff = p.price_open - price
        profit = (price_diff / tick_size * tick_value * p.volume) if tick_size else p.profit
        return round(profit, 2)

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
        bar_time: datetime | None = None,
    ) -> None:
        TRADE_JOURNAL_PATH.parent.mkdir(parents=True, exist_ok=True)
        header_exists = TRADE_JOURNAL_PATH.exists()
        
        with open(TRADE_JOURNAL_PATH, "a", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            if not header_exists:
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
            
            ts_str = bar_time.isoformat() if bar_time else datetime.now(timezone.utc).isoformat()
            writer.writerow(
                [
                    ts_str,
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

    def _calc_rrr(
        self,
        pos_type: int,
        price_open: float,
        sl: float,
        tp: float,
        current: float,
    ) -> float | None:
        _ = tp
        return calc_position_r(pos_type, price_open, sl, current)

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

    def _check_and_skip_night_block(self) -> None:
        if self._replay_index >= len(self._m1_full):
            return
        
        tz = ZoneInfo(RISK.timezone)
        skipped = False
        start_idx = self._replay_index
        
        while self._replay_index < len(self._m1_full):
            current_bar = self._m1_full.iloc[self._replay_index]
            bar_time = current_bar["time"]
            local_dt = bar_time.replace(tzinfo=timezone.utc).astimezone(tz)
            
            hour = local_dt.hour
            minute = local_dt.minute
            
            is_night = False
            if hour == 23:
                is_night = True
            elif hour == 0 and minute < 30:
                is_night = True
                
            if not is_night:
                break
                
            self._replay_index += 1
            skipped = True
            
        if skipped:
            end_idx = min(self._replay_index, len(self._m1_full) - 1)
            logger.info(
                "[TEST] Skipping night block from bar %d (%s) to %d (%s local)",
                start_idx,
                self._m1_full.iloc[start_idx]["time"].replace(tzinfo=timezone.utc).astimezone(tz).strftime("%d.%m. %H:%M"),
                end_idx,
                self._m1_full.iloc[end_idx]["time"].replace(tzinfo=timezone.utc).astimezone(tz).strftime("%d.%m. %H:%M"),
            )
            self.state.compute_log.cmd(
                "test",
                f"[TEST] Přeskočena noc (23:00 - 00:30) na další den",
                "warn",
            )
            
        if self._replay_index >= len(self._m1_full):
            replay = self._snapshot.get("replay", {})
            loop = replay.get("loop", TEST.replay_loop)
            if loop:
                start = int(replay.get("start_index", UI.chart_bars_m1))
                self._replay_index = min(start, len(self._m1_full) - 1)
                self._replay_accumulator = 0.0
            else:
                self._replay_index = len(self._m1_full) - 1

    def _advance_replay(self) -> None:
        replay = self._snapshot.get("replay", {})
        loop = replay.get("loop", TEST.replay_loop)
        sec_per_bar = max(0.5, TEST.m1_bar_seconds) / max(0.1, TEST.replay_speed)
        bars_per_sec = 1.0 / sec_per_bar
        interval = UI.refresh_interval_ms / 1000.0
        self._replay_accumulator += bars_per_sec * interval

        while self._replay_accumulator >= 1.0:
            self._replay_index += 1
            self._replay_accumulator -= 1.0

        # Automatically check and bypass night blocks
        self._check_and_skip_night_block()

        if self._replay_index >= len(self._m1_full):
            if loop:
                start = int(replay.get("start_index", UI.chart_bars_m1))
                self._replay_index = min(start, len(self._m1_full) - 1)
                self._replay_accumulator = 0.0
                self.state.compute_log.cmd("test", "Replay loop — návrat na start", "info")
            else:
                self._replay_index = len(self._m1_full) - 1

    def _current_spread(self) -> float:
        replay = self._snapshot.get("replay", {})
        every = int(replay.get("spread_spike_every", 0))
        mult = float(replay.get("spread_spike_multiplier", 2.0))
        if every > 0 and self._poll_count > 0 and self._poll_count % every == 0:
            return self._base_spread * mult
        return self._base_spread

    def _update_positions_pnl(
        self,
        bid: float,
        ask: float,
        spread: float,
        atr: float,
        bar_time: datetime,
    ) -> None:
        tick_value = self._symbol_params.tick_value if self._symbol_params else 1.0
        tick_size = self._symbol_params.tick_size if self._symbol_params else 0.01
        updated: list[PositionInfo] = []

        for p in self._positions:
            current = bid if p.type == mt5.ORDER_TYPE_BUY else ask
            
            # Check SL/TP hit
            hit = False
            event = ""
            exit_price = current
            
            if p.type == mt5.ORDER_TYPE_BUY:
                if p.sl > 0 and bid <= p.sl:
                    hit = True
                    event = "SL"
                    exit_price = p.sl
                elif p.tp > 0 and bid >= p.tp:
                    hit = True
                    event = "TP"
                    exit_price = p.tp
            else:
                if p.sl > 0 and ask >= p.sl:
                    hit = True
                    event = "SL"
                    exit_price = p.sl
                elif p.tp > 0 and ask <= p.tp:
                    hit = True
                    event = "TP"
                    exit_price = p.tp

            if hit:
                # Calculate final profit at SL/TP close price
                profit = self._calculate_position_profit(p, exit_price)
                self._log_journal_event(
                    event,
                    p.ticket,
                    p.symbol,
                    p.volume,
                    profit,
                    spread,
                    atr,
                    p.sl,
                    p.tp,
                    bar_time,
                )
                self.state.compute_log.insight(
                    "test",
                    f"Pozice {p.ticket} zavřena ({event})",
                    f"{p.side} {p.volume} lotů za {exit_price:.2f} · Zisk {profit:+.2f} USD",
                    "ok" if profit >= 0 else "warn",
                )
                continue

            if p.type == mt5.ORDER_TYPE_BUY:
                price_diff = current - p.price_open
            else:
                price_diff = p.price_open - current
            profit = (price_diff / tick_size * tick_value * p.volume) if tick_size else p.profit
            r = self._calc_rrr(p.type, p.price_open, p.sl, p.tp, current)
            updated.append(
                PositionInfo(
                    ticket=p.ticket,
                    symbol=p.symbol,
                    volume=p.volume,
                    profit=round(profit, 2),
                    sl=p.sl,
                    tp=p.tp,
                    price_open=p.price_open,
                    price_current=current,
                    type=p.type,
                    rrr=r,
                    r_current=r,
                    sl_distance_pts=calc_sl_distance_pts(p.type, p.sl, current),
                    side=p.side,
                )
            )
        self._positions = updated

    def _build_account_snapshot(self) -> AccountSnapshot:
        raw = self._snapshot.get("account", {})
        login = int(raw.get("login", 999999))
        company = str(raw.get("company", "TEST REPLAY"))
        balance = float(raw.get("balance", ACCOUNT.starting_balance))
        base_equity = float(raw.get("equity", balance))
        pos_profit = sum(p.profit for p in self._positions)
        equity = base_equity + (pos_profit - self._initial_position_profit)

        self._prop_state = update_baselines(self._prop_state, equity)
        dd = compute_drawdowns(equity, self._prop_state)

        return AccountSnapshot(
            login=login,
            company=company,
            balance=balance,
            equity=equity,
            margin=float(raw.get("margin", 0.0)),
            free_margin=float(raw.get("free_margin", equity)),
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
        current_bar = self._m1_full.iloc[self._replay_index]
        end_ts = current_bar["time"]
        close = float(current_bar["close"])

        spread = self._current_spread()
        point = self._symbol_params.tick_size if self._symbol_params else 0.01
        half = spread * point / 2 if point else 0.0
        bid = close - half
        ask = close + half

        self._spread_history.append(spread)
        if len(self._spread_history) > RISK.spread_median_window:
            self._spread_history = self._spread_history[-RISK.spread_median_window :]
        spread_median = float(np.median(self._spread_history)) if self._spread_history else spread
        spread_warning = spread > spread_median * RISK.spread_warning_multiplier if spread_median else False

        m1 = _slice_rates(self._m1_full, end_ts, UI.chart_bars_m1)
        m5 = _slice_rates(self._m5_full, end_ts, UI.chart_bars_m5)
        m15 = _slice_rates(self._m15_full, end_ts, UI.chart_bars_m15)
        h1 = _slice_rates(self._h1_full, end_ts, 50)
        dxy = _slice_rates(self._dxy_full, end_ts, UI.chart_bars_m5)

        atr = self._calc_atr(m1) if not m1.empty else 0.0
        current_range = float(current_bar["high"] - current_bar["low"])
        last_bar = {
            "open": float(current_bar["open"]),
            "high": float(current_bar["high"]),
            "low": float(current_bar["low"]),
            "close": close,
        }
        atr_impulse = atr > 0 and current_range > INDICATORS.atr_impulse_multiplier * atr

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
            alerts.append("[KRITICKÉ] Blízkost prop limitu — simulace.")
        if market.atr_impulse:
            alerts.append("[ANOMÁLIE] Liquidity sweep / ATR impulz detekován.")
        if market.spread_warning:
            alerts.append("[BARRIER] Vysoké transakční náklady — exekuce pozastavena.")
        return alerts

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
            log.insight("signal", f"Režim · {signal_lab.regime}", signal_lab.headline, "info")

        critical = account.is_critical
        if critical and not self._last_dd_critical:
            log.insight(
                "risk",
                "Prop DD — kritická zóna (TEST)",
                f"Denní {account.daily_drawdown_pct:.1f}% · Trailing {account.trailing_drawdown_pct:.1f}%",
                "warn",
            )
        self._last_dd_critical = critical

        for a in alerts:
            upper = a.upper()
            if "SPREAD" in upper and not self._last_spread_alert:
                self._last_spread_alert = True
                log.insight("market", "Spread nad normálem (TEST)", a, "warn")
            elif "ATR" in upper and not self._last_atr_alert:
                self._last_atr_alert = True
                log.insight("market", "Volatilita ATR impulse (TEST)", a, "warn")

        if market and not market.spread_warning:
            self._last_spread_alert = False
        if market and not market.atr_impulse:
            self._last_atr_alert = False

        now_ts = time.monotonic()
        if now_ts - self._last_tick_log_ts >= 12.0:
            self._last_tick_log_ts = now_ts
            bar_time = self._m1_full.iloc[self._replay_index]["time"]
            log.cmd(
                "tick",
                f"[TEST] {market.bid:.2f} · bar {self._replay_index}/{len(self._m1_full)} · "
                f"{bar_time.strftime('%H:%M')} · spr {market.spread_points:.0f}p",
                "info",
            )

    def _poll_once(self) -> None:
        self._poll_count += 1
        self._advance_replay()

        market = self._build_market_snapshot()
        bar_time = pd.Timestamp(self._m1_full.iloc[self._replay_index]["time"]).to_pydatetime()
        self._update_positions_pnl(
            market.bid,
            market.ask,
            market.spread_points,
            market.atr,
            bar_time,
        )
        account = self._build_account_snapshot()
        alerts = self._collect_alerts(account, market)

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
            positions=list(self._positions),
            alerts=alerts,
            signal_lab=signal_lab,
            indicators=indicator_bundle,
        )
        with self.state.lock:
            self.state.position_tracks = update_position_tracks(
                self._positions, self.state.position_tracks
            )
        self._engine_log_tick(account, market, signal_lab, alerts)

    def start_streaming(self, interval: float = 0.5) -> None:
        if self._running:
            return
        self._running = True

        def _loop() -> None:
            while self._running:
                try:
                    self._poll_once()
                except Exception:
                    logger.exception("Error in test replay loop")
                time.sleep(interval)

        self._thread = threading.Thread(target=_loop, daemon=True, name="TestReplay")
        self._thread.start()
        logger.info("Test replay streaming started (interval=%.1fs)", interval)

    def stop_streaming(self) -> None:
        self._running = False
