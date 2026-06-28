"""
Audio alerting and sticky alert latch for dashboard events.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_last_alert_hash: str | None = None
_lock = threading.Lock()

ALERT_LATCH_SECONDS = 30.0


def _play_windows_beep(frequency: int = 1000, duration_ms: int = 500) -> None:
    try:
        import winsound

        winsound.Beep(frequency, duration_ms)
    except Exception as exc:
        logger.debug("winsound failed: %s", exc)


def _play_system_bell() -> None:
    sys.stdout.write("\a")
    sys.stdout.flush()


def play_alert(severity: str = "critical") -> None:
    """Play alert sound based on severity."""
    if severity == "critical":
        if sys.platform == "win32":
            _play_windows_beep(1200, 800)
            _play_windows_beep(800, 400)
        else:
            _play_system_bell()
    elif severity == "warning":
        if sys.platform == "win32":
            _play_windows_beep(900, 400)
        else:
            _play_system_bell()
    else:
        _play_system_bell()


def alert_on_new_critical(alerts: list[str]) -> None:
    """De-duplicate and fire audio only on new critical/warning alerts."""
    global _last_alert_hash

    if not alerts:
        return

    critical = [a for a in alerts if "KRITICK" in a.upper() or "CRITICAL" in a.upper() or "BLOK" in a.upper() or "ANOMÁL" in a.upper() or "ANOMALY" in a.upper()]
    if not critical:
        return

    alert_hash = "|".join(sorted(critical))
    with _lock:
        if alert_hash == _last_alert_hash:
            return
        _last_alert_hash = alert_hash

    severity = "critical" if any("KRITICK" in a.upper() or "CRITICAL" in a.upper() for a in critical) else "warning"
    threading.Thread(target=play_alert, args=(severity,), daemon=True).start()


def _severity_from_text(text: str) -> str:
    upper = text.upper()
    if "KRITICK" in upper or "CRITICAL" in upper:
        return "critical"
    if "BLOK" in upper or "STOP" in upper or "ANOMÁL" in upper:
        return "warn"
    return "info"


def latch_alerts(
    current_alerts: list[str],
    previous_latch: dict[str, Any] | None,
    dismissed: bool = False,
) -> dict[str, Any]:
    """Keep alert visible for at least ALERT_LATCH_SECONDS after it appears."""
    now = time.time()
    prev = previous_latch or {}
    if dismissed:
        return {"text": "", "ts": 0, "severity": "info", "active": False}

    if current_alerts:
        text = "  ·  ".join(current_alerts)
        return {
            "text": text,
            "ts": now,
            "severity": _severity_from_text(text),
            "active": True,
        }

    if prev.get("active") and prev.get("text"):
        age = now - float(prev.get("ts", 0))
        if age < ALERT_LATCH_SECONDS:
            return {**prev, "active": True}

    return {"text": "", "ts": 0, "severity": "info", "active": False}


def render_latched_alert_bar(latch: dict[str, Any] | None) -> tuple[str, dict]:
    latch = latch or {}
    if latch.get("active") and latch.get("text"):
        sev = latch.get("severity", "warn")
        cls = f"alert-bar alert-bar-{sev}"
        return str(latch["text"]), {"display": "flex"}
    return "", {"display": "none"}


def send_discord_webhook(message: str) -> None:
    """Send alert message to Discord webhook asynchronously."""
    from config import DISCORD_WEBHOOK_URL
    import requests

    url = DISCORD_WEBHOOK_URL
    if not url:
        logger.info(f"Discord Webhook URL not set. Alert message: {message}")
        return

    def run():
        try:
            payload = {"content": f"🚨 **Quantum HUD Alert**: {message}"}
            res = requests.post(url, json=payload, timeout=5)
            if res.status_code >= 400:
                logger.error(f"Discord Webhook returned status {res.status_code}: {res.text}")
            else:
                logger.info(f"Discord Webhook sent successfully: {message}")
        except Exception as exc:
            logger.error(f"Failed to send Discord Webhook alert: {exc}")

    threading.Thread(target=run, daemon=True).start()
