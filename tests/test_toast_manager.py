from signal_lab import SignalItem, SignalLabSnapshot, synthesize_m1_verdict
from status_rail import StatusChip
from toast_manager import active_toasts, sync_toast_queue, toast_key


def test_toast_persists_until_dismissed():
    chips = [StatusChip(label="Spread 35p", priority=2, tone="info")]
    queue = sync_toast_queue(chips, None, [])
    assert len(active_toasts(queue)) == 1

    key = toast_key("Spread 35p")
    queue2 = sync_toast_queue([], queue, [])
    assert len(active_toasts(queue2)) == 1

    queue3 = sync_toast_queue([], queue2, [key])
    assert len(active_toasts(queue3)) == 0


def test_toast_new_alert_adds_second_item():
    chips = [StatusChip(label="Spread 35p", priority=2, tone="info")]
    queue = sync_toast_queue(chips, None, [])
    chips2 = [StatusChip(label="Spread 40p", priority=2, tone="wait")]
    queue2 = sync_toast_queue(chips2, queue, [])
    toasts = active_toasts(queue2)
    assert len(toasts) == 2
    labels = {t.label for t in toasts}
    assert "Spread 35p" in labels
    assert "Spread 40p" in labels


def test_m1_verdict_sweep_is_wait():
    lab = SignalLabSnapshot(
        headline="Liquidity sweep — čekej reakci",
        regime="SWEEP",
        signals=[
            SignalItem("M5 momentum", "BULL", "", "bull"),
            SignalItem("Spread", "25p", "", "neutral"),
        ],
    )
    v = synthesize_m1_verdict(lab)
    assert v.direction == "WAIT"
    assert "sweep" in v.headline.lower() or "Liquidity" in v.headline
