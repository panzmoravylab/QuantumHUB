from i18n import action_label, t, translate_reason


def test_t_english():
    assert t("mt5_ok", "EN") == "MT5 OK"
    assert t("no_positions", "CZ") == "Žádné otevřené pozice"


def test_action_label():
    assert action_label("DRŽET", "EN") == "HOLD"
    assert action_label("ZAVŘÍT", "CZ") == "ZAVŘÍT"


def test_translate_reason():
    msg = "Všechny podmínky splněny"
    assert translate_reason(msg, "EN") == "All conditions met"
