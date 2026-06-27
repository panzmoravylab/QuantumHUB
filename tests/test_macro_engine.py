from datetime import datetime
from zoneinfo import ZoneInfo

from macro_engine import MacroStatus, analyze_macro_day
from risk_engine import NewsEvent


def test_analyze_macro_day_clear():
    tz = ZoneInfo("Europe/Prague")
    now = datetime(2026, 6, 27, 12, 0, tzinfo=tz)
    summary = analyze_macro_day([], now)
    assert summary.status in (MacroStatus.CLEAR, MacroStatus.CAUTION)
