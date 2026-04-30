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
    # Live speed dial in the no-shots branch must reflect a fresh gate
    # sample (and decay to 0 when stale) -- not freeze on a previous
    # value or stay at the simulated baseline.
    assert "live_speed = (\n                self._last_gate_speed_mph if gate_fresh else 0.0\n            )" in src
    assert 'self.lbl_live_rpm.setText(f"Live RPM' in src


def test_ball_speed_metric_slider_starts_at_zero_mph():
    """Regression guard: bench-test/hand-sweep gate samples must be visible.

    MetricSlider.set_value() clamps the value into [min_v, max_v]. If the
    speed slider's `min_v` is anything above 0 mph, every sub-threshold
    sample (a slow drill, a kid's swing, or a manual gate-test sweep at
    1-4 km/h) is silently snapped up to that floor and the indicator dot
    pins to the left edge -- exactly the "shows in the logs but no UI
    representation" failure mode reported during gate-speed bring-up.

    Allow 0 mph as the lower bound so the dial faithfully reflects what
    the firmware is reporting, even when that is "almost zero".
    """
    src = read_app()
    match = re.search(
        r'self\.ms_speed\s*=\s*MetricSlider\(\s*"Ball Speed"\s*,\s*([0-9.+-]+)\s*,',
        src,
    )
    assert match, "ms_speed MetricSlider construction not found"
    floor = float(match.group(1))
    assert floor == 0, (
        f"ms_speed slider floor is {floor} mph -- must be 0 so slow gate "
        f"samples don't get clamped invisible. See "
        f"test_ball_speed_metric_slider_starts_at_zero_mph for context."
    )


def test_live_speed_dial_prefers_fresh_gate_sample_over_last_shot_speed():
    """Regression guard: dial must track current ball motion, not last shot.

    Previously _refresh_ui unconditionally pushed `latest.speed` (the last
    completed shot's value) into the speed dial every 80ms, which meant
    that bench testing the gate sensors -- where every gate-speed packet
    is logged but no main-hall hit occurs -- left the dial stuck on the
    previous shot's speed. The dial must instead prefer a fresh gate
    sample (within ~1s) and only fall back to the last-shot speed when
    the gate stream goes quiet.
    """
    src = read_app()

    refresh_fn = re.search(
        r"def _refresh_ui\(self.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert refresh_fn, "_refresh_ui block not found"
    body = refresh_fn.group(0)
    assert "gate_fresh = (" in body
    assert "(now_t - self._last_gate_speed_ts) <= 1.0" in body
    assert "self._last_gate_speed_mph if gate_fresh else latest.speed" in body


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


def test_impact_parser_accepts_extended_payload_with_baseline_gravity_and_tilt():
    """Regression guard: _on_impact must parse the new 23-byte impact frame
    that carries the racket's resting gravity vector + a derived tilt
    angle, AND keep parsing the legacy 16- and 13-byte forms.

    Without backward compatibility, an older firmware build in the field
    would suddenly stop emitting impact events to the dashboard the
    moment the host upgrades. Without forward compatibility, the new
    arm-angle source is silently ignored.
    """
    src = read_app()

    on_impact = re.search(
        r"def _on_impact\(self, _sender, data: bytearray\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert on_impact, "_on_impact block not found"
    body = on_impact.group(0)

    # New 23-byte form is preferred and parsed via the extended struct
    # spec. The 16-byte legacy form must still be reachable, and the
    # 13-byte pre-magnitude form must still be reachable too.
    assert "if len(data) >= 23:" in body
    assert '"<IhhhHBbbBhhhb"' in body
    assert "elif len(data) >= 16:" in body
    assert '"<IhhhHBbbB"' in body
    assert "elif len(data) >= 13:" in body
    assert '"<IhhhBbb"' in body

    # Legacy paths emit zeros for the new orientation fields so the
    # downstream signal signature stays uniform.
    assert "0, 0, 0, 0," in body

    # Diagnostic line surfaces the new tilt + gravity vector at INFO so
    # we can confirm end-to-end without a debugger.
    assert 'tilt={tilt_deg}deg gravity_mg' in body


def test_impact_signal_carries_orientation_fields():
    """The Qt impact signal MUST carry baseline gravity and tilt so the
    main window's _on_impact_packet can record them. Dropping them at
    the signal boundary would silently revert arm_angle to the random
    simulator value even after the firmware was upgraded.
    """
    src = read_app()
    assert (
        "impact = pyqtSignal(int, int, int, int, int, int, int, int, int, "
        "int, int, int, int)"
    ) in src


def test_live_arm_angle_uses_measured_tilt_when_fresh():
    """Regression guard: the count-driven shot reconstruction must prefer
    the latest ADXL335-derived racket tilt over the legacy random
    simulator value. The simulator value (`random.uniform(-18.0, 18.0)
    + impact_x * 0.34`) is allowed only as a fallback for older firmware
    builds that don't ship the gravity baseline yet, so the dashboard
    stays usable during a firmware upgrade.
    """
    src = read_app()

    # Tilt state initialized on the main window.
    assert "self._last_arm_tilt_deg = 0.0" in src
    assert "self._last_arm_tilt_ts = 0.0" in src
    assert "self._last_gravity_baseline_mg" in src

    # _on_impact_packet stashes the latest measured tilt (only when the
    # baseline gravity vector is actually present; legacy frames ship
    # zeros and must NOT overwrite a good reading).
    pkt = re.search(
        r"def _on_impact_packet\(.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert pkt, "_on_impact_packet block not found"
    pkt_body = pkt.group(0)
    assert "tilt_deg: int = 0," in pkt_body
    assert "self._last_arm_tilt_deg = float(tilt_deg)" in pkt_body
    assert "if gravity_present:" in pkt_body

    # Live shot path prefers the measured tilt when fresh.
    telemetry = re.search(
        r"def _on_telemetry\(.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert telemetry, "_on_telemetry block not found"
    tbody = telemetry.group(0)
    assert "self._last_arm_tilt_ts" in tbody
    assert "arm_fresh" in tbody
    assert "arm_raw = float(self._last_arm_tilt_deg)" in tbody
    # The legacy synthetic path stays in place ONLY as the fallback.
    assert "random.uniform(-18.0, 18.0) + impact_x * 0.34" in tbody
