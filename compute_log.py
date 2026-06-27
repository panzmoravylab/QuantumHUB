"""Strukturovaný log pro HUD — uživatelské insight karty, ne raw terminál."""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

from config import RISK


@dataclass(frozen=True)
class LogLine:
    time: str
    level: str
    message: str


@dataclass(frozen=True)
class InsightEntry:
    time: str
    category: str
    title: str
    detail: str
    level: str


class ComputeLog:
    """Thread-safe ring buffer — strukturované zprávy pro UI."""

    def __init__(self, maxlen: int = 20) -> None:
        self._lock = threading.Lock()
        self._lines: deque[LogLine] = deque(maxlen=maxlen)
        self._insights: deque[InsightEntry] = deque(maxlen=maxlen)

    def _now(self) -> str:
        tz = ZoneInfo(RISK.timezone)
        return datetime.now(tz).strftime("%H:%M:%S")

    def insight(
        self,
        category: str,
        title: str,
        detail: str,
        level: str = "info",
    ) -> None:
        entry = InsightEntry(
            time=self._now(),
            category=category,
            title=title,
            detail=detail,
            level=level,
        )
        with self._lock:
            self._insights.append(entry)
            self._lines.append(LogLine(time=entry.time, level=level, message=f"{title} — {detail}"))

    def cmd(self, tag: str, message: str, level: str = "info") -> None:
        """Raw terminálový řádek — viditelný běh Python engine."""
        ts = self._now()
        with self._lock:
            self._lines.append(LogLine(time=ts, level=level, message=f"[{tag}] {message}"))

    def info(self, message: str) -> None:
        self.insight("system", "Info", message, "info")

    def ok(self, message: str) -> None:
        self.insight("system", "OK", message, "ok")

    def warn(self, message: str) -> None:
        self.insight("risk", "Varování", message, "warn")

    def error(self, message: str) -> None:
        self.insight("system", "Chyba", message, "err")

    def read(self) -> list[LogLine]:
        with self._lock:
            return list(self._lines)

    def read_insights(self) -> list[InsightEntry]:
        with self._lock:
            return list(self._insights)
