"""Persistent toast queue — alerts stay visible until the user dismisses them."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from typing import Any

from status_rail import StatusChip, build_status_rail


@dataclass(frozen=True)
class ToastItem:
    key: str
    label: str
    tone: str
    ts: float


def toast_key(label: str) -> str:
    normalized = label.strip().upper()
    return hashlib.md5(normalized.encode()).hexdigest()[:12]


def build_toast_candidates(
    alerts: list[str],
    verdict,
    plan,
    style_guide,
    macro_summary,
    market,
    indicators,
) -> list[StatusChip]:
    return build_status_rail(
        alerts,
        verdict,
        plan,
        style_guide,
        macro_summary,
        market,
        indicators,
        max_items=8,
    )


def sync_toast_queue(
    chips: list[StatusChip],
    previous: dict[str, Any] | None,
    dismissed: list[str] | None,
) -> dict[str, Any]:
    """Merge new chips into active toasts; only user dismiss removes them."""
    now = time.time()
    prev_active: dict[str, dict] = dict((previous or {}).get("active", {}))
    dismissed_set = set(dismissed or [])

    for chip in chips:
        key = toast_key(chip.label)
        if key in dismissed_set:
            continue
        if key not in prev_active:
            prev_active[key] = {
                "label": chip.label,
                "tone": chip.tone,
                "ts": now,
            }
        else:
            prev_active[key]["label"] = chip.label
            prev_active[key]["tone"] = chip.tone

    active = {k: v for k, v in prev_active.items() if k not in dismissed_set}
    ordered = sorted(
        active.items(),
        key=lambda kv: (
            0 if kv[1].get("tone") == "critical" else 1 if kv[1].get("tone") == "wait" else 2,
            -float(kv[1].get("ts", 0)),
        ),
    )
    return {"active": dict(ordered[:8])}


def merge_extra_toasts(
    queue: dict[str, Any] | None,
    extras: list[tuple[str, str, str]],
    dismissed: list[str] | None,
) -> dict[str, Any]:
    """Add keyed toasts (e.g. position close alerts) into an existing queue."""
    now = time.time()
    active = dict((queue or {}).get("active", {}))
    dismissed_set = set(dismissed or [])
    for key, label, tone in extras:
        if key in dismissed_set:
            continue
        if key not in active:
            active[key] = {"label": label, "tone": tone, "ts": now}
        else:
            active[key]["label"] = label
            active[key]["tone"] = tone
    ordered = sorted(
        active.items(),
        key=lambda kv: (
            0 if kv[1].get("tone") == "critical" else 1 if kv[1].get("tone") == "wait" else 2,
            -float(kv[1].get("ts", 0)),
        ),
    )
    return {"active": dict(ordered[:8])}


def active_toasts(queue: dict[str, Any] | None) -> list[ToastItem]:
    active = (queue or {}).get("active", {})
    items = [
        ToastItem(key=k, label=v["label"], tone=v.get("tone", "info"), ts=float(v.get("ts", 0)))
        for k, v in active.items()
    ]
    items.sort(
        key=lambda t: (
            0 if t.tone == "critical" else 1 if t.tone == "wait" else 2,
            -t.ts,
        )
    )
    return items
