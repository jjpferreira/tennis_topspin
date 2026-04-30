from pathlib import Path
import importlib.util
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_FILE = REPO_ROOT / "python_app" / "realtime_tennis_monitor.py"
HW_CONFIG_FILE = REPO_ROOT / "python_app" / "hardware_config.py"
FIRMWARE_CONFIG_H = REPO_ROOT / "firmware" / "include" / "config.h"


def read_app() -> str:
    return APP_FILE.read_text(encoding="utf-8")


def _load_hardware_config():
    """Import python_app/hardware_config.py without polluting sys.path."""
    spec = importlib.util.spec_from_file_location(
        "tennis_hardware_config", HW_CONFIG_FILE
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tennis_hardware_config"] = mod
    spec.loader.exec_module(mod)
    return mod


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
    # Live shot reconstruction remains count-driven; gate A/B speed should be
    # preferred when fresh, with model fallback when gate is missing/stale.
    body = telemetry_fn.group(0)
    assert "self._append_shot(" in body
    assert "self._last_gate_speed_mph" in body
    assert "model_speed = max(" in body
    assert "if (now - self._last_gate_speed_ts) <= 0.35 and self._last_gate_speed_mph > 0.1:" in body
    # Gate speed is a direct physical measurement and must NOT be clamped to
    # the profile's "plausible shot" floor (live_speed_min). Doing so silently
    # snaps slow bench/hand-sweep tests up to ~24/38/46 mph and hides any
    # genuinely soft real shot. Only the upper bound is allowed as a safety
    # net against pathological transit times.
    assert "speed = min(prof[\"live_speed_max\"], self._last_gate_speed_mph)" in body
    # The OLD min/max clamp form must not return for the gate-speed branch.
    assert "speed = max(\n                            prof[\"live_speed_min\"]," not in body


def test_gate_speed_packets_are_logged_so_pipeline_is_visible_in_logs():
    """Regression guard for the silent gate-speed handler.

    The original `_on_gate_speed` only emitted the Qt signal and never logged,
    so when speed samples failed to appear in the UI it was impossible to tell
    from the log file whether the firmware never sent a packet or the Python
    side dropped/parsed it incorrectly. Every other notify handler logs at
    INFO via _diag, so gate-speed must too -- otherwise we are blind exactly
    where it matters most for ball-speed debugging.
    """
    src = read_app()

    gate_fn = re.search(
        r"def _on_gate_speed\(self, _sender, data: bytearray\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert gate_fn, "_on_gate_speed block not found"
    body = gate_fn.group(0)
    assert "GATE-SPEED sample #" in body
    assert "ble_log.info(" in body
    # Short/garbled packets must not be dropped silently either: a warning
    # gets emitted so we can spot a payload-shape mismatch immediately.
    assert "GATE-SPEED packet too short" in body


def test_python_and_firmware_share_the_same_gate_distance():
    """Regression guard: hardware_config.py::GATE_DISTANCE_CM and
    firmware/include/config.h::KY003_GATE_DISTANCE_CM must agree on the
    physical sensor spacing.

    Speed = distance / transit_time. If these drift apart the dashboard
    silently scales every shot speed by the wrong factor, with no other
    visible symptom -- the kind of bug that survives weeks because the
    numbers "look reasonable". Forcing them to match is the cheapest way
    to keep that drift impossible.
    """
    hw = _load_hardware_config()
    config_h = FIRMWARE_CONFIG_H.read_text(encoding="utf-8")

    # Pull the float literal out of `#define KY003_GATE_DISTANCE_CM <X>f`.
    match = re.search(
        r"#define\s+KY003_GATE_DISTANCE_CM\s+([0-9]+\.?[0-9]*)f",
        config_h,
    )
    assert match, "KY003_GATE_DISTANCE_CM macro not found in config.h"
    firmware_value = float(match.group(1))

    assert hw.GATE_DISTANCE_CM == firmware_value, (
        f"gate-distance mismatch: hardware_config.py={hw.GATE_DISTANCE_CM}cm "
        f"vs firmware/config.h={firmware_value}cm. Update BOTH whenever the "
        f"physical rig changes."
    )

    # RPM pulses-per-rev is a similar sync risk.
    rpm_match = re.search(
        r"#define\s+KY003_RPM_PULSES_PER_REV\s+([0-9]+)u",
        config_h,
    )
    assert rpm_match, "KY003_RPM_PULSES_PER_REV macro not found in config.h"
    firmware_rpm = int(rpm_match.group(1))
    assert hw.RPM_PULSES_PER_REV == firmware_rpm, (
        f"rpm pulses/rev mismatch: hardware_config.py={hw.RPM_PULSES_PER_REV} "
        f"vs firmware/config.h={firmware_rpm}. Update BOTH whenever the "
        f"main hall sensor magnet count changes."
    )


def test_python_app_imports_hardware_config_for_defaults():
    """Regression guard: realtime_tennis_monitor.py must source its
    gate-distance / pulses-per-rev defaults from hardware_config.py rather
    than hard-coding them inline. Hard-coded copies were the reason the
    Python default sat at 3.0cm while the firmware default sat at the same
    -- a value that masked the actual rig (10mm) and silently scaled every
    recorded speed by 3x.
    """
    src = read_app()
    assert "from hardware_config import" in src
    assert "GATE_DISTANCE_CM as HW_GATE_DISTANCE_CM" in src
    assert "self._fw_gate_distance_cm = HW_GATE_DISTANCE_CM" in src
    assert "self._fw_rpm_pulses_per_rev = HW_RPM_PULSES_PER_REV" in src
    # Ensure the previous hard-coded defaults are gone.
    assert "self._fw_gate_distance_cm = 3.0" not in src
    assert "self._fw_rpm_pulses_per_rev = 1\n" not in src
