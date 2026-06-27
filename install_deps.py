"""Instalace zavislosti po balicku s opakovanim — obchazi SSL vypadky pip."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PACKAGES = [
    "MetaTrader5>=5.0.4874",
    "plotly>=5.20.0,<6.0.0",
    "dash>=2.16.0,<3.0.0",
    "pandas>=2.1.0,<3.0.0",
    "numpy>=1.26.0,<2.2.0",
    "scipy>=1.12.0,<1.15.0",
    "requests>=2.31.0",
    "beautifulsoup4>=4.12.0",
    "python-dotenv>=1.0.0",
    "pytz>=2024.1",
]

IMPORT_CHECKS = [
    ("MetaTrader5", "MetaTrader5"),
    ("plotly", "plotly"),
    ("dash", "dash"),
    ("pandas", "pandas"),
    ("dotenv", "python-dotenv"),
    ("scipy", "scipy"),
    ("bs4", "beautifulsoup4"),
    ("pytz", "pytz"),
]


def _can_import() -> bool:
    for mod, _ in IMPORT_CHECKS:
        try:
            __import__(mod)
        except ImportError:
            return False
    return True


def _pip_install(pkg: str, attempt: int) -> bool:
    cmd = [
        sys.executable,
        "-m",
        "pip",
        "install",
        pkg,
        "--no-cache-dir",
        "--retries",
        "10",
        "--timeout",
        "180",
    ]
    print(f"  -> {pkg}  (pokus {attempt})")
    r = subprocess.run(cmd, cwd=Path(__file__).parent)
    if r.returncode != 0:
        print(f"  pip selhal (kod {r.returncode}) pro: {pkg}")
    return r.returncode == 0


def main() -> int:
    print(f"  Python: {sys.executable}")
    if _can_import():
        print("  Vsechny balicky jsou dostupne.")
        return 0

    print("  Instaluji chybejici balicky po jednom ...")
    for pkg in PACKAGES:
        for attempt in range(1, 4):
            if _pip_install(pkg, attempt):
                break
            if attempt == 3:
                print(f"  [CHYBA] Nepodarilo se nainstalovat: {pkg}")
                return 1

    if _can_import():
        print("  Instalace dokoncena.")
        return 0

    print("  [CHYBA] Po instalaci stale chybi nektere balicky.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
