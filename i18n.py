"""Central UI strings for CZ / EN localization."""

from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    "no_positions": {"CZ": "Žádné otevřené pozice", "EN": "No active positions"},
    "m1_waiting": {"CZ": "M1 Analytics čeká na data…", "EN": "M1 Analytics waiting for data…"},
    "radar_status": {"CZ": "STATUS RADARU:", "EN": "RADAR STATUS:"},
    "gate_wait": {"CZ": "GATE POČKEJ", "EN": "GATE WAIT"},
    "bullish_bias": {"CZ": "BULLISH BIAS", "EN": "BULLISH BIAS"},
    "bearish_bias": {"CZ": "BEARISH BIAS", "EN": "BEARISH BIAS"},
    "hold_neutral": {"CZ": "HOLD / NEUTRÁLNÍ", "EN": "HOLD / NEUTRAL"},
    "radar_title": {"CZ": "Likviditní Radar (Session H/L)", "EN": "Liquidity Radar (Session H/L)"},
    "sell_liq": {"CZ": "SELL LIKVIDITA", "EN": "SELL LIQUIDITY"},
    "buy_liq": {"CZ": "BUY LIKVIDITA", "EN": "BUY LIQUIDITY"},
    "mt5_ok": {"CZ": "MT5 OK", "EN": "MT5 OK"},
    "mt5_off": {"CZ": "MT5 OFF", "EN": "MT5 OFF"},
    "macro_ok": {"CZ": "MACRO OK", "EN": "MACRO OK"},
    "macro_warn": {"CZ": "MACRO POZOR", "EN": "MACRO CAUTION"},
    "macro_block": {"CZ": "MACRO BLOK", "EN": "MACRO BLOCK"},
    "gw": {"CZ": "GW", "EN": "GW"},
    "off_gw": {"CZ": "MIMO GW", "EN": "OFF GW"},
    "risk_limits": {"CZ": "Risk & limity", "EN": "Risk & limits"},
    "dd_headroom": {"CZ": "DD headroom", "EN": "DD headroom"},
    "trades_left": {"CZ": "Obchody zbývá", "EN": "Trades left"},
    "next_event": {"CZ": "Další událost", "EN": "Next event"},
    "macro_label": {"CZ": "Macro", "EN": "Macro"},
    "no_macro": {"CZ": "Bez high-impact v nejbližších hodinách", "EN": "No high-impact events in the next hours"},
    "show_chart": {"CZ": "Zobrazit graf", "EN": "Show chart"},
    "hide_chart": {"CZ": "Skrýt graf", "EN": "Hide chart"},
    "expand_macro": {"CZ": "Rozbalit +7 dní", "EN": "Expand +7 days"},
    "collapse_macro": {"CZ": "Sbalit na dnes", "EN": "Collapse to today"},
    "panel_account": {"CZ": "Účet", "EN": "Account"},
    "panel_decision": {"CZ": "Rozhodnutí", "EN": "Decision"},
    "panel_session": {"CZ": "Session", "EN": "Session"},
    "panel_macro": {"CZ": "Macro kalendář", "EN": "Macro calendar"},
    "kill_switch": {"CZ": "KILL SWITCH", "EN": "KILL SWITCH"},
    "all_conditions_met": {"CZ": "Všechny podmínky splněny", "EN": "All conditions met"},
}

ACTION_LABELS: dict[str, dict[str, str]] = {
    "DRŽET": {"CZ": "DRŽET", "EN": "HOLD"},
    "KOREKCE": {"CZ": "KOREKCE", "EN": "CORRECTION"},
    "CHRÁNIT": {"CZ": "CHRÁNIT", "EN": "PROTECT"},
    "ZAVŘÍT": {"CZ": "ZAVŘÍT", "EN": "CLOSE"},
}

REASON_EN: dict[str, str] = {
    "Mimo Golden Window 14–18h CE(S)T — nižší likvidita": "Outside Golden Window 2-6 PM CE(S)T - lower liquidity",
    "ATR impulse — cena skáče, počkejte na ustálení": "ATR impulse - price is jumping, wait for stability",
    "Macro CAUTION — zvýšená volatilita kolem dat": "Macro CAUTION - high volatility around news release",
    "Režim WAIT — bez clear edge": "WAIT mode - no clear edge",
    "Verdict CAUTION — obchodujte menší size nebo čekejte": "Verdict CAUTION - trade smaller size or wait",
    "Rozjetý vlak — extrémní rychlost ceny": "Running train - extreme price velocity",
    "Golden Window aktivní — nejlepší likvidita": "Golden Window active - optimal liquidity",
    "Spread nad normálem — drahý vstup": "Spread above median - expensive entry",
    "Prop DD kritické": "Prop Drawdown Critical",
    "Všechny podmínky splněny": "All conditions met",
    "Režim NO TRADE": "NO TRADE mode",
    "Připojte MetaTrader 5 — bez live dat nejde rozhodnout.": "Connect MetaTrader 5 - cannot decide without live data.",
    "Indikátor v MT5 běží, ale HUD nevidí spread ani DD.": "MT5 Indicator running but HUD does not see spread or drawdown.",
    "Indikátor může dát vstup — HUD nevidí žádný blok (spread · macro · prop).": "Indicator signals entry - HUD sees no blockers.",
    "Indikátor může dávat signál — HUD říká NE kvůli rizikům, které indikátor neřeší.": "Indicator signals entry - HUD blocks execution due to high risk.",
    "Indikátor má mezery — HUD vidí okolní rizika, raději počkejte na lepší okno.": "Indicator has gaps - HUD advises waiting for a better window.",
}


def t(key: str, lang: str = "CZ", **kwargs) -> str:
    lang = "EN" if lang == "EN" else "CZ"
    entry = STRINGS.get(key, {})
    text = entry.get(lang, entry.get("CZ", key))
    if kwargs:
        return text.format(**kwargs)
    return text


def action_label(action: str, lang: str = "CZ") -> str:
    lang = "EN" if lang == "EN" else "CZ"
    return ACTION_LABELS.get(action, {}).get(lang, action)


def translate_reason(msg: str, lang: str = "CZ") -> str:
    if not msg or lang != "EN":
        return msg
    for cz, en in REASON_EN.items():
        if cz in msg:
            return msg.replace(cz, en)
    return msg
