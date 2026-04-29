from pathlib import Path
import re


APP_FILE = (
    Path(__file__).resolve().parents[1]
    / "python_app"
    / "realtime_tennis_monitor.py"
)


def read_app() -> str:
    return APP_FILE.read_text(encoding="utf-8")


def test_ble_worker_lock_prevents_hopping_without_freezing_reconnects():
    """Regression guard for the 'connect to tennis then dead-stop' bug.

    We want strict address lock (no random peripheral hopping), but we must
    keep retrying that same locked address after disconnect.
    """
    src = read_app()

    assert "self._locked_address: str | None = None" in src
    assert "session BLE lock set" in src
    assert "ignoring tennis-looking device" in src

    # Old bug: we once stopped the worker loop after first disconnect by
    # setting _running=False + break. Keep that pattern out forever.
    assert "_scan_frozen_after_first_lock" not in src
    assert "Locked sensor disconnected. Auto-scan is paused by design" not in src
    # On macOS, device.name is often empty even when adv.local_name is valid.
    # Guard against re-introducing connect-time rejection based only on
    # `device.name`.
    assert "refusing to connect to %s — name '%s' does not start with %s*" not in src


def test_stale_cache_handler_is_manual_only():
    """Regression guard for disruptive auto-toggle behavior on macOS."""
    src = read_app()

    assert "manual_recovery_only" in src
    assert "stale cache detected — manual recovery only" in src

    # No automatic Bluetooth power cycling from stale-cache callback.
    assert "auto-recovery: invoking _force_ble_refresh()" not in src
    assert "QTimer.singleShot(0, self._force_ble_refresh)" not in src


def test_refresh_ui_updates_live_metrics_even_with_no_shots():
    """Regression guard for 'no data' UI state when shots list is empty."""
    src = read_app()

    # The early-return condition previously hid live RPM/speed updates.
    assert "if not self.shots and not force:\n            return" not in src
    assert "live_speed = self.telemetry.gate_speed_mph" in src
    assert 'self.lbl_live_rpm.setText(f"Live RPM' in src


def test_live_speed_prefers_gate_packets_with_count_based_shot_append():
    """Keep proven flow: shot append on count deltas, gate packet updates speed."""
    src = read_app()

    gate_fn = re.search(
        r"def _on_gate_speed_packet\(.*?\n    def _classify_ky003_health",
        src,
        flags=re.S,
    )
    assert gate_fn, "_on_gate_speed_packet block not found"
    assert "self.telemetry.gate_speed_mph = mph" in gate_fn.group(0)

    telemetry_fn = re.search(
        r"def _on_telemetry\(.*?\n    def _live_stream_guard",
        src,
        flags=re.S,
    )
    assert telemetry_fn, "_on_telemetry block not found"
    # Live shot reconstruction remains count-driven, but speed must come from
    # fresh gate A/B data only (no synthetic fallback tied to RPM/rate).
    assert "self._append_shot(" in telemetry_fn.group(0)
    assert "self._last_gate_speed_mph" in telemetry_fn.group(0)
    assert "if (now - self._last_gate_speed_ts) > 0.90 or self._last_gate_speed_mph <= 0.1:" in telemetry_fn.group(0)
    assert "continue" in telemetry_fn.group(0)
