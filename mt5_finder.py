"""
Automatic detection of MetaTrader 5 terminal64.exe on Windows.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CANDIDATES = [
    Path(r"C:\Program Files\MetaTrader 5\terminal64.exe"),
    Path(r"C:\Program Files (x86)\MetaTrader 5\terminal64.exe"),
    Path(r"C:\Program Files\MetaTrader 5\terminal.exe"),
    Path(r"C:\Program Files (x86)\MetaTrader 5\terminal.exe"),
]


def _from_running_process() -> Path | None:
    """Get terminal path from a running terminal64.exe / terminal.exe process."""
    if os.name != "nt":
        return None

    for exe in ("terminal64.exe", "terminal.exe"):
        try:
            result = subprocess.run(
                [
                    "wmic",
                    "process",
                    "where",
                    f"name='{exe}'",
                    "get",
                    "ExecutablePath",
                    "/format:list",
                ],
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.lower().startswith("executablepath="):
                    path_str = line.split("=", 1)[1].strip()
                    if path_str:
                        path = Path(path_str)
                        if path.exists():
                            return path
        except Exception as exc:
            logger.debug("WMIC lookup for %s failed: %s", exe, exc)

    return None


def _scan_program_files() -> Path | None:
    """Scan Program Files for broker MT5 installations."""
    roots = [
        Path(r"C:\Program Files"),
        Path(r"C:\Program Files (x86)"),
    ]
    found: list[Path] = []

    for root in roots:
        if not root.exists():
            continue
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                for sub in ("MetaTrader 5", "MT5"):
                    for exe in ("terminal64.exe", "terminal.exe"):
                        candidate = child / sub / exe
                        if candidate.exists():
                            found.append(candidate)
        except OSError as exc:
            logger.debug("Program Files scan failed under %s: %s", root, exc)

    if not found:
        return None

    # Prefer terminal64.exe, then shortest path (usually default install)
    found.sort(key=lambda p: (p.name != "terminal64.exe", len(str(p))))
    return found[0]


def find_mt5_terminal() -> Path | None:
    """
    Find MT5 terminal executable automatically.
    Priority: running process > default paths > Program Files scan.
    """
    for resolver in (_from_running_process, _scan_defaults, _scan_program_files):
        path = resolver()
        if path:
            logger.info("MT5 terminal auto-detected: %s", path)
            return path

    logger.warning("MT5 terminal not found — ensure MetaTrader 5 is installed")
    return None


def _scan_defaults() -> Path | None:
    for candidate in DEFAULT_CANDIDATES:
        if candidate.exists():
            return candidate
    return None


def describe_mt5_terminal() -> str:
    """Human-readable status for setup wizard."""
    path = find_mt5_terminal()
    if path:
        return str(path)
    return "nenalezen — spustte MT5 terminal a zkuste znovu"
