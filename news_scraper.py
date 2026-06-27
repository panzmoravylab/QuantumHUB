"""
Economic calendar — Investing.com (primární, 7 dní), ForexFactory XML záloha.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

from config import LOGS_DIR, MACRO, RISK
from risk_engine import NewsEvent

if TYPE_CHECKING:
    from compute_log import ComputeLog
    from mt5_connector import MT5Connector

logger = logging.getLogger(__name__)

CALENDAR_URL = "https://www.forexfactory.com/calendar?day=today"
FF_XML_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.xml"
FF_JSON_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
INVESTING_URL = "https://www.investing.com/economic-calendar/Service/getCalendarFilteredData"
INVESTING_COUNTRIES = (5, 6, 72, 37, 4, 39, 35, 12, 17)  # USD EUR GBP JPY AUD CAD CHF NZD
CALENDAR_CACHE_PATH = LOGS_DIR / "macro_calendar_cache.json"
FF_CACHE_PATH = CALENDAR_CACHE_PATH
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/html,*/*",
}

RELEVANT_CURRENCIES = frozenset({"USD", "EUR", "GBP", "XAU", "CHF", "JPY"})


class NewsCache:
    """Thread-safe cache for macro events."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._events: list[NewsEvent] = []
        self._last_fetch: datetime | None = None
        self._fetch_error: str | None = None
        self._source: str = ""

    def update(
        self,
        events: list[NewsEvent],
        error: str | None = None,
        source: str = "",
    ) -> None:
        with self._lock:
            self._events = events
            self._last_fetch = datetime.now(ZoneInfo(RISK.timezone))
            self._fetch_error = error
            self._source = source

    def read(self) -> tuple[list[NewsEvent], str | None, str]:
        with self._lock:
            return list(self._events), self._fetch_error, self._source


def _macro_relevant(currency: str, importance: int, title: str) -> bool:
    c = (currency or "USD").upper().strip()
    if importance >= 3:
        return c in RELEVANT_CURRENCIES or not c
    if importance >= 2:
        return c in ("USD", "EUR", "GBP")
    return False


def _impact_from_string(s: str) -> str:
    s = (s or "").lower()
    if "high" in s or "red" in s:
        return "high"
    if "medium" in s or "orange" in s or "ora" in s:
        return "medium"
    return "low"


def _parse_time_str(time_str: str, base_date: datetime) -> datetime | None:
    time_str = time_str.strip().lower()
    if not time_str or time_str in ("all day", "tentative", "day", "tbd", ""):
        return None

    tz = ZoneInfo(RISK.timezone)
    match = re.match(r"(\d{1,2}):(\d{2})(am|pm)?", time_str)
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2))
    ampm = match.group(3)
    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0

    return base_date.replace(hour=hour, minute=minute, second=0, microsecond=0, tzinfo=tz)


def _read_ff_cache(ignore_ttl: bool = False) -> list | None:
    if not FF_CACHE_PATH.exists():
        return None
    try:
        raw = json.loads(FF_CACHE_PATH.read_text(encoding="utf-8"))
        if not ignore_ttl and time.time() - raw.get("ts", 0) > MACRO.ff_cache_ttl_sec:
            return None
        return raw.get("data")
    except Exception:
        return None


def _save_ff_cache(data: list) -> None:
    try:
        FF_CACHE_PATH.write_text(
            json.dumps({"ts": time.time(), "data": data}),
            encoding="utf-8",
        )
    except Exception as exc:
        logger.debug("FF cache write failed: %s", exc)


def _download_ff_raw() -> list:
    errors: list[str] = []

    for url, parser in ((FF_XML_URL, "xml"), (FF_JSON_URL, "json")):
        try:
            resp = requests.get(url, headers=HEADERS, timeout=25)
            resp.raise_for_status()
            if parser == "json":
                rows = resp.json()
                if isinstance(rows, list) and rows:
                    _save_ff_cache(rows)
                    return rows
            else:
                rows = _parse_ff_xml(resp.content)
                if rows:
                    _save_ff_cache(rows)
                    return rows
        except Exception as exc:
            errors.append(f"{url.split('/')[-1]}: {exc}")
            logger.warning("FF %s failed: %s", url, exc)

    stale = _read_ff_cache(ignore_ttl=True)
    if stale:
        logger.info("Using stale FF calendar cache (%d rows)", len(stale))
        return stale

    if errors:
        logger.warning("All FF sources failed: %s", "; ".join(errors))
    return []


def _parse_ff_xml(content: bytes) -> list[dict]:
    root = ET.fromstring(content)
    rows: list[dict] = []
    for event in root.findall("event"):
        title = (event.findtext("title") or "").strip()
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "country": (event.findtext("country") or "USD").strip(),
                "date": (event.findtext("date") or "").strip(),
                "time": (event.findtext("time") or "").strip(),
                "impact": (event.findtext("impact") or "Low").strip(),
            }
        )
    return rows


def _investing_impact(title_attr: str, row_classes: str) -> str:
    text = f"{title_attr} {row_classes}".lower()
    if "high volatility" in text or "high impact" in text:
        return "high"
    if "moderate volatility" in text or "medium" in text:
        return "medium"
    return "low"


def _parse_investing_row(row, tz: ZoneInfo, now: datetime) -> NewsEvent | None:
    dt_raw = row.get("data-event-datetime")
    if not dt_raw:
        return None

    title_cell = row.select_one("td.event")
    title = title_cell.get_text(strip=True) if title_cell else ""
    if not title:
        return None

    cur_cell = row.select_one("td.flagCur")
    currency = "USD"
    if cur_cell:
        cur_text = cur_cell.get_text(strip=True)
        currency = cur_text[:3].upper() if cur_text else "USD"

    sentiment = row.select_one("td.sentiment")
    impact = _investing_impact(
        sentiment.get("title", "") if sentiment else "",
        " ".join(row.get("class", [])),
    )
    if impact not in ("high", "medium"):
        return None

    imp_num = 3 if impact == "high" else 2
    if not _macro_relevant(currency, imp_num, title):
        return None

    try:
        event_time = datetime.strptime(dt_raw, "%Y/%m/%d %H:%M:%S").replace(tzinfo=tz)
    except ValueError:
        return None

    window_start = now - timedelta(hours=MACRO.lookback_hours)
    window_end = now + timedelta(days=MACRO.lookahead_days)
    if event_time < window_start or event_time > window_end:
        return None

    return NewsEvent(
        title=title,
        currency=currency,
        impact=impact,
        event_time=event_time,
        seconds_until=int((event_time - now).total_seconds()),
    )


def fetch_investing_calendar(now: datetime) -> list[NewsEvent]:
    """Investing.com — 7 dní dopředu, medium + high."""
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    window_end = now + timedelta(days=MACRO.lookahead_days)

    cached = _read_ff_cache()
    if cached and cached[0].get("_source") == "investing":
        events = [_parse_investing_cache_row(row, now, tz) for row in cached]
        events = [e for e in events if e]
        if events:
            return events

    headers = {
        **HEADERS,
        "X-Requested-With": "XMLHttpRequest",
        "Origin": "https://www.investing.com",
        "Referer": "https://www.investing.com/economic-calendar/",
    }
    body = {
        "country[]": list(INVESTING_COUNTRIES),
        "importance[]": [2, 3],
        "dateFrom": now.strftime("%Y-%m-%d"),
        "dateTo": window_end.strftime("%Y-%m-%d"),
        "timeZone": "58",
        "timeFilter": "timeRemain",
        "currentTab": "custom",
        "limit_from": 0,
    }

    try:
        resp = requests.post(INVESTING_URL, data=body, headers=headers, timeout=30)
        resp.raise_for_status()
        payload = resp.json()
        html = payload.get("data") or ""
    except Exception as exc:
        logger.warning("Investing.com calendar failed: %s", exc)
        stale = _read_ff_cache(ignore_ttl=True)
        if stale and stale[0].get("_source") == "investing":
            events = [_parse_investing_cache_row(row, now, tz) for row in stale]
            return [e for e in events if e]
        return []

    soup = BeautifulSoup(html, "html.parser")
    events: list[NewsEvent] = []
    cache_rows: list[dict] = []
    for row in soup.select("tr.js-event-item"):
        parsed = _parse_investing_row(row, tz, now)
        if parsed:
            events.append(parsed)
            cache_rows.append(
                {
                    "_source": "investing",
                    "title": parsed.title,
                    "country": parsed.currency,
                    "date": parsed.event_time.strftime("%Y/%m/%d %H:%M:%S"),
                    "impact": parsed.impact,
                }
            )

    events.sort(key=lambda e: e.event_time)
    if cache_rows:
        _save_ff_cache(cache_rows)
    logger.info("Investing calendar: %d events in %d-day window", len(events), MACRO.lookahead_days)
    return events


def _parse_investing_cache_row(row: dict, now: datetime, tz: ZoneInfo) -> NewsEvent | None:
    title = row.get("title") or ""
    if not title:
        return None
    currency = (row.get("country") or "USD").upper()
    impact = (row.get("impact") or "medium").lower()
    if impact not in ("high", "medium"):
        return None
    try:
        event_time = datetime.strptime(row["date"], "%Y/%m/%d %H:%M:%S").replace(tzinfo=tz)
    except (KeyError, ValueError):
        return None
    window_start = now - timedelta(hours=MACRO.lookback_hours)
    window_end = now + timedelta(days=MACRO.lookahead_days)
    if event_time < window_start or event_time > window_end:
        return None
    return NewsEvent(
        title=title,
        currency=currency,
        impact=impact,
        event_time=event_time,
        seconds_until=int((event_time - now).total_seconds()),
    )


def _parse_ff_row(row: dict, now: datetime, tz: ZoneInfo) -> NewsEvent | None:
    title = row.get("title") or row.get("name") or ""
    if not title:
        return None

    currency = (row.get("country") or row.get("currency") or "USD").upper()
    impact = _impact_from_string(row.get("impact", ""))
    if impact not in ("high", "medium"):
        return None
    imp_num = 3 if impact == "high" else 2
    if not _macro_relevant(currency, imp_num, title):
        return None

    date_str = row.get("date") or ""
    time_str = row.get("time") or ""
    try:
        if "T" in date_str:
            event_time = datetime.fromisoformat(date_str).astimezone(tz)
        elif "/" in date_str and " " in date_str:
            event_time = datetime.strptime(date_str, "%Y/%m/%d %H:%M:%S").replace(tzinfo=tz)
        elif re.match(r"\d{2}-\d{2}-\d{4}", date_str[:10]):
            base = datetime.strptime(date_str[:10], "%m-%d-%Y").replace(tzinfo=tz)
            event_time = _parse_time_str(time_str, base) if time_str else base
            if event_time is None:
                return None
        else:
            base = now
            if date_str:
                try:
                    base = datetime.strptime(date_str[:10], "%Y-%m-%d").replace(tzinfo=tz)
                except ValueError:
                    pass
            event_time = _parse_time_str(time_str or date_str, base)
            if event_time is None:
                return None
    except (ValueError, TypeError):
        return None

    window_start = now - timedelta(hours=MACRO.lookback_hours)
    window_end = now + timedelta(days=MACRO.lookahead_days)
    if event_time < window_start or event_time > window_end:
        return None

    return NewsEvent(
        title=title,
        currency=currency,
        impact=impact,
        event_time=event_time,
        seconds_until=int((event_time - now).total_seconds()),
    )


def fetch_ff_json(now: datetime) -> list[NewsEvent]:
    """ForexFactory JSON — this week + next week, 7 dní dopředu."""
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)

    data = _read_ff_cache()
    if data is None:
        data = _download_ff_raw()
    if not data:
        return []

    events: list[NewsEvent] = []
    for row in data:
        parsed = _parse_ff_row(row, now, tz)
        if parsed:
            events.append(parsed)

    events.sort(key=lambda e: e.event_time)
    logger.info("FF calendar: %d events in %d-day window", len(events), MACRO.lookahead_days)
    return events


def scrape_forex_factory(now: datetime) -> list[NewsEvent]:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    events: list[NewsEvent] = []
    try:
        resp = requests.get(CALENDAR_URL, headers=HEADERS, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("ForexFactory HTML scrape failed: %s", exc)
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    for row in soup.select("tr.calendar__row"):
        impact = _parse_impact_cell(row.select_one("td.calendar__impact"))
        if impact not in ("high", "medium"):
            continue
        event_cell = row.select_one("td.calendar__event")
        if not event_cell:
            continue
        title = event_cell.get_text(strip=True)
        currency_cell = row.select_one("td.calendar__currency")
        currency = currency_cell.get_text(strip=True) if currency_cell else "USD"
        imp_num = 3 if impact == "high" else 2
        if not _macro_relevant(currency, imp_num, title):
            continue
        time_cell = row.select_one("td.calendar__time")
        time_str = time_cell.get_text(strip=True) if time_cell else ""
        event_time = _parse_time_str(time_str, now)
        if event_time is None:
            continue
        window_end = now + timedelta(days=MACRO.lookahead_days)
        if event_time > window_end:
            continue
        events.append(
            NewsEvent(
                title=title,
                currency=currency,
                impact=impact,
                event_time=event_time,
                seconds_until=int((event_time - now).total_seconds()),
            )
        )
    events.sort(key=lambda e: e.event_time)
    return events


def _parse_impact_cell(cell) -> str:
    if cell is None:
        return "low"
    classes = " ".join(cell.get("class", []))
    if "high" in classes or "red" in classes:
        return "high"
    if "medium" in classes or "ora" in classes:
        return "medium"
    return "low"


def fetch_all_macro_events(
    now: datetime | None = None,
    connector: MT5Connector | None = None,
) -> tuple[list[NewsEvent], str, str | None]:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)

    if connector is not None and getattr(connector, "is_connected", lambda: False)():
        try:
            mt5_events = connector.fetch_macro_events(now)
            if mt5_events:
                return mt5_events, "MT5 Calendar", None
        except Exception as exc:
            logger.warning("MT5 macro fetch failed: %s", exc)

    investing_events = fetch_investing_calendar(now)
    if investing_events:
        return investing_events, "Investing.com", None

    json_events = fetch_ff_json(now)
    if json_events:
        return json_events, "ForexFactory", None

    html_events = scrape_forex_factory(now)
    if html_events:
        return html_events, "ForexFactory HTML", None

    error = (
        "Kalendář prázdný — Investing.com i FF nedostupné. "
        f"Okno: {MACRO.lookahead_days} dní dopředu."
    )
    return [], "CHYBA", error


def format_t_minus(seconds: int) -> str:
    prefix = "T-Minus" if seconds >= 0 else "T+"
    abs_sec = abs(seconds)
    h, rem = divmod(abs_sec, 3600)
    m, s = divmod(rem, 60)
    if h >= 24:
        d, rh = divmod(h, 24)
        return f"{prefix} {d}d {rh:02d}:{m:02d}:{s:02d}"
    return f"{prefix} {h:02d}:{m:02d}:{s:02d}"


def refresh_news_counts(events: list[NewsEvent], now: datetime | None = None) -> list[NewsEvent]:
    tz = ZoneInfo(RISK.timezone)
    now = now or datetime.now(tz)
    return [
        NewsEvent(
            title=e.title,
            currency=e.currency,
            impact=e.impact,
            event_time=e.event_time,
            seconds_until=int((e.event_time - now).total_seconds()),
        )
        for e in events
    ]


class NewsScraperThread:
    def __init__(
        self,
        cache: NewsCache | None = None,
        connector: MT5Connector | None = None,
        interval: float = 900.0,
        compute_log: ComputeLog | None = None,
    ) -> None:
        self.cache = cache or NewsCache()
        self.connector = connector
        self.interval = interval
        self.compute_log = compute_log
        self._running = False
        self._thread: threading.Thread | None = None

    def _log_fetch(self, events: list[NewsEvent], source: str, error: str | None) -> None:
        if not self.compute_log:
            return
        from macro_engine import analyze_macro_focus

        tz = ZoneInfo(RISK.timezone)
        now = datetime.now(tz)
        summary = analyze_macro_focus(events, now)
        if source == "CHYBA":
            self.compute_log.cmd(
                "macro",
                f"cache · {len(events)} událostí · briefing {summary.focus_label}",
                "warn",
            )
        else:
            self.compute_log.cmd(
                "macro",
                f"{source} · {len(events)} evt · briefing {summary.focus_label}",
                "ok",
            )

    def fetch_once(self) -> None:
        try:
            tz = ZoneInfo(RISK.timezone)
            now = datetime.now(tz)
            events, source, error = fetch_all_macro_events(now, self.connector)
            if source == "CHYBA":
                prev, _, _ = self.cache.read()
                if prev:
                    events = refresh_news_counts(prev, now)
                self.cache.update(events, error, source)
                self._log_fetch(events, source, error)
                return
            self.cache.update(events, error, source)
            self._log_fetch(events, source, error)
        except Exception as exc:
            logger.exception("News fetch error")
            prev, _, _ = self.cache.read()
            if prev:
                tz = ZoneInfo(RISK.timezone)
                self.cache.update(
                    refresh_news_counts(prev, datetime.now(tz)),
                    str(exc),
                    "CHYBA",
                )
            else:
                try:
                    events, source, error = fetch_all_macro_events(
                        datetime.now(ZoneInfo(RISK.timezone)), None
                    )
                    self.cache.update(events, error or str(exc), source)
                except Exception:
                    self.cache.update([], str(exc), "CHYBA")

    def start(self) -> None:
        if self._running:
            return
        self._running = True

        def _loop() -> None:
            self.fetch_once()
            while self._running:
                time.sleep(self.interval)
                self.fetch_once()

        self._thread = threading.Thread(target=_loop, daemon=True, name="NewsScraper")
        self._thread.start()

    def stop(self) -> None:
        self._running = False
