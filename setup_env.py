"""
Interaktivni pruvodce nastavenim .env pro Quantum HUD.
Volano z Nastaveni.bat — bezpecne zpracuje hesla se specialnimi znaky.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from mt5_finder import describe_mt5_terminal, find_mt5_terminal

BASE_DIR = Path(__file__).resolve().parent
ENV_PATH = BASE_DIR / ".env"
ENV_EXAMPLE = BASE_DIR / ".env.example"

# MT5_PATH se neptame — system ho najde sam
FIELDS: list[tuple[str, str, str, bool]] = [
    ("MT5_LOGIN", "MT5 Login (cislo uctu)", "", False),
    ("MT5_PASSWORD", "MT5 Heslo", "", True),
    ("MT5_SERVER", "MT5 Server (napr. FTTrading-Live)", "", False),
    ("MT5_EXPECTED_ACCOUNT", "Ocekavany ucet (volitelne, pro kontrolu)", "", False),
    ("MT5_EXPECTED_COMPANY", "Broker / spolecnost", "ForTraders", False),
    ("SYMBOL", "Obchodovany symbol", "XAUUSD", False),
    ("DXY_SYMBOL", "Symbol pro DXY korelaci", "USDX", False),
    ("DISCORD_WEBHOOK_URL", "Discord Webhook URL (volitelne)", "", False),
]


def _load_existing() -> dict[str, str]:
    values: dict[str, str] = {}
    source = ENV_PATH if ENV_PATH.exists() else ENV_EXAMPLE
    if not source.exists():
        return values
    for line in source.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        values[key.strip()] = val.strip()
    return values


def _prompt(key: str, label: str, default: str, secret: bool) -> str:
    existing = current.get(key, default)
    hint = "(Enter = ponechat)" if existing else "(Enter = prazdne)"

    if secret and existing:
        display = "*" * min(len(existing), 8) if existing else "(prazdne)"
    else:
        display = existing or "(prazdne)"

    print(f"\n  {label}")
    print(f"  Aktualne: {display}  {hint}")

    try:
        value = input("  > ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n\nSetup zrusen.")
        sys.exit(1)

    if value == "":
        return existing
    return value


def _write_env(values: dict[str, str]) -> None:
    mt5_path = find_mt5_terminal()
    mt5_note = str(mt5_path) if mt5_path else "auto-detekce pri spusteni"

    lines = [
        "# Quantum HUD — konfigurace (generovano Nastaveni.bat)",
        f"# MT5 terminal: {mt5_note}",
        "",
        "# MT5 prihlasovaci udaje (volitelne pokud je terminal jiz prihlaseny)",
        f"MT5_LOGIN={values.get('MT5_LOGIN', '')}",
        f"MT5_PASSWORD={values.get('MT5_PASSWORD', '')}",
        f"MT5_SERVER={values.get('MT5_SERVER', '')}",
        "",
        "# Validace prop uctu",
        f"MT5_EXPECTED_ACCOUNT={values.get('MT5_EXPECTED_ACCOUNT', '')}",
        f"MT5_EXPECTED_COMPANY={values.get('MT5_EXPECTED_COMPANY', 'ForTraders')}",
        "",
        "# Symboly",
        f"SYMBOL={values.get('SYMBOL', 'XAUUSD')}",
        f"DXY_SYMBOL={values.get('DXY_SYMBOL', 'USDX')}",
        "",
        "# Notifikace",
        f"DISCORD_WEBHOOK_URL={values.get('DISCORD_WEBHOOK_URL', '')}",
        "",
    ]
    ENV_PATH.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    global current
    os.system("")

    print()
    print("  ============================================================")
    print("       QUANTUM HUD  —  Průvodce nastavením")
    print("  ============================================================")
    print()
    print("  MT5 terminal:", describe_mt5_terminal())
    print()
    print("  Tipy:")
    print("  - Cestu k MT5 system najde automaticky — nemusite zadávat")
    print("  - MT5 terminal musi byt spusteny a prihlaseny")
    print("  - Pokud je MT5 jiz prihlaseny, login/heslo/server nechte prazdne")
    print("  - Stisknete Enter pro ponechani aktualni hodnoty")
    print()

    current = _load_existing()
    if ENV_PATH.exists():
        print("  Nalezen existujici soubor .env — upravite jen to, co chcete.")
    else:
        print("  Vytvari se novy soubor .env ...")

    updated: dict[str, str] = {}
    for key, label, default, secret in FIELDS:
        updated[key] = _prompt(key, label, default, secret)

    _write_env(updated)

    print()
    print("  ============================================================")
    print(f"  Hotovo! Konfigurace ulozena: {ENV_PATH}")
    print(f"  MT5 terminal: {describe_mt5_terminal()}")
    print("  ============================================================")
    print()
    print("  Dalsi krok: spustte  Spustit_Quantum_HUD.bat")
    print()


if __name__ == "__main__":
    main()
