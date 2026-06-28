from config import normalize_hud_layout, toggle_hud_layout
from i18n import layout_button_label, normalize_layout_mode


def test_normalize_hud_layout_defaults_to_main():
    assert normalize_hud_layout(None) == "main"
    assert normalize_hud_layout("") == "main"
    assert normalize_hud_layout("main") == "main"


def test_normalize_hud_layout_accepts_portrait_aliases():
    assert normalize_hud_layout("portrait") == "portrait"
    assert normalize_hud_layout("vertical") == "portrait"
    assert normalize_hud_layout("PORTRAIT") == "portrait"


def test_toggle_hud_layout():
    assert toggle_hud_layout("main") == "portrait"
    assert toggle_hud_layout("portrait") == "main"
    assert toggle_hud_layout(None) == "portrait"


def test_layout_button_label():
    assert layout_button_label("main", "CZ") == "HLAVNÍ"
    assert layout_button_label("portrait", "CZ") == "PORTRAIT"
    assert layout_button_label("main", "EN") == "MAIN"


def test_i18n_normalize_layout_mode():
    assert normalize_layout_mode("p") == "portrait"
    assert normalize_layout_mode("unknown") == "main"
