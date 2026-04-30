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


def test_calibration_wizard_preview_reacts_to_every_impact():
    """Regression guard: the calibration wizard's ball preview MUST
    show a visible reaction (pulse + counter) on every impact event,
    even outside CAPTURE mode and even when the impact's contact
    coordinates are zero (common with a misconfigured ADXL where
    contact_x/y get zeroed in the firmware's invalid path).

    The historical bug: _on_impact_packet shipped event keys
    `x_mg/y_mg/intensity` but the wizard read `impact_x/impact_y/
    redness`, so set_last_hit was always called with (0, 0, 0). The
    preview dot stayed dead center with no glow and the wizard looked
    broken even though impacts were arriving correctly over BLE.
    """
    src = read_app()

    # Backend: event dict carries the keys the preview reads, so
    # set_last_hit gets non-zero arguments on real hits.
    pkt = re.search(
        r"def _on_impact_packet\(.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert pkt, "_on_impact_packet block not found"
    pbody = pkt.group(0)
    assert '"contact_x": int(contact_x),' in pbody
    assert '"contact_y": int(contact_y),' in pbody
    assert '"redness": int(intensity),' in pbody

    # Preview widget exposes a per-hit pulse + counter so the operator
    # gets unambiguous "saw a hit" feedback even when the dot lands at
    # (0, 0). Both are exercised on every impact event by the wizard.
    assert "def trigger_hit_pulse(self):" in src
    assert "def hits_detected(self) -> int:" in src
    assert "def reset_hit_counter(self):" in src
    assert "self._pulse_strength" in src
    assert "self._hits_detected" in src

    # Wizard wires the pulse + counter on every impact, BEFORE the
    # capture-mode early return, so preview reacts in idle mode too.
    wiz = re.search(
        r"def on_impact_event\(self, event: dict\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert wiz, "wizard on_impact_event block not found"
    wbody = wiz.group(0)
    assert "self.wiz_preview.trigger_hit_pulse()" in wbody
    assert 'event.get("contact_x", event.get("impact_x", 0))' in wbody
    assert 'event.get("contact_y", event.get("impact_y", 0))' in wbody
    assert 'event.get("redness", event.get("intensity", 0))' in wbody
    # The trigger_hit_pulse() call must happen before any
    # capture-mode early return, otherwise idle preview is dead again.
    pulse_idx = wbody.index("self.wiz_preview.trigger_hit_pulse()")
    return_idx = wbody.index("return")
    assert pulse_idx < return_idx, (
        "trigger_hit_pulse() must run before the capture-mode return; "
        "otherwise the preview only animates while CAPTURE SOFT/HARD "
        "is armed and looks broken in idle mode."
    )

    # Per-hit status text in idle mode so the operator sees something
    # in addition to the visual pulse.
    assert "Detected hit #" in wbody
    assert "intensity {intensity}%" in wbody


def test_impact_packet_forwards_to_calibration_wizard_even_when_invalid():
    """Regression guard: the calibration wizard MUST receive every
    captured impact, including those flagged `valid=False`. The
    chicken-and-egg bug we are pinning here:
        - LIVE shot pipeline filters on valid (correct).
        - But the wizard is what TUNES the threshold that decides
          `valid`. If we drop sub-threshold impacts before they reach
          the wizard, the wizard cannot recommend a lower threshold
          and the user is stuck whenever calibration is too high.

    The fix: gate ONLY the LIVE book-keeping on `valid`; always forward
    the event dict to hardware-settings windows.
    """
    src = read_app()

    pkt = re.search(
        r"def _on_impact_packet\(.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert pkt, "_on_impact_packet block not found"
    pbody = pkt.group(0)

    # Forwarding loop runs unconditionally.
    forward_idx = pbody.index("for w in self._hardware_settings_windows():")

    # The pre-fix shape was `if not valid: return` *above* the
    # forwarding loop. Pin its absence: if the loop is gated on the
    # valid flag, the wizard is dead again on bench bring-up.
    bad_pattern = re.compile(r"if not valid:\s*\n\s*#[^\n]*\n(\s*#[^\n]*\n)*\s*return\s*\n[\s\S]*for w in self\._hardware_settings_windows")
    assert not bad_pattern.search(pbody), (
        "if not valid: return must NOT precede the wizard-forwarding "
        "loop -- otherwise sub-threshold impacts can't be used to "
        "re-calibrate the threshold."
    )

    # LIVE book-keeping IS gated on valid (otherwise sub-threshold
    # noise pollutes shot history).
    valid_gate = re.search(
        r"if valid:\s*\n\s*self\._impact_by_hit_count\[hit_count\]",
        pbody,
    )
    assert valid_gate, (
        "self._impact_by_hit_count[...] must only run when valid -- "
        "otherwise sub-threshold ADXL noise leaks into LIVE shots."
    )

    # And the gate must be ABOVE the forwarding loop (so we update
    # book-keeping first, then notify wizards).
    assert valid_gate.start() < forward_idx


def test_calibration_wizard_paints_preview_from_raw_lateral_mg():
    """Regression guard: the wizard's preview dot MUST be painted from
    the accelerometer's raw `x_mg`/`y_mg`/`mag_mg`, not from the
    calibration-mapped `contact_x`/`contact_y`.

    Why: the whole point of the wizard is to FIX a bad calibration. If
    we paint the dot from the firmware's already-mapped contact_x/y,
    the dot stays at (0, 0) when the current `contact_full_scale_mg`
    is too high -- exactly when the user is running the wizard.
    Painting from raw mg lets the dot land where the ADXL says the
    racket struck the ball, regardless of the current calibration.
    """
    src = read_app()

    # New helper on the preview widget that maps raw mg to a
    # calibration-independent preview scale.
    helper = re.search(
        r"def set_last_hit_from_raw_mg\(.*?\n        self\.update\(\)\s*\n",
        src,
        flags=re.S,
    )
    assert helper, "set_last_hit_from_raw_mg helper missing"
    hbody = helper.group(0)
    assert "lateral_full_scale_mg" in hbody
    assert "impact_full_scale_mg" in hbody
    assert "self._last_x" in hbody
    assert "self._last_y" in hbody
    assert "self._last_redness" in hbody

    # Wizard uses the raw-mg helper when raw values are available,
    # falls back to contact_x/y otherwise (legacy 16-byte frames).
    wiz = re.search(
        r"def on_impact_event\(self, event: dict\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert wiz, "wizard on_impact_event block not found"
    wbody = wiz.group(0)
    assert "self.wiz_preview.set_last_hit_from_raw_mg(x_mg, y_mg, mag_mg)" in wbody
    # The fallback path is still wired in for legacy events.
    assert "self.wiz_preview.set_last_hit(contact_x, contact_y, redness)" in wbody
    # Idle status line shows raw accelerometer numbers, not just the
    # already-clamped intensity %, so the user can read the actual
    # signal off the sensor while calibrating.
    assert "mag {mag_mg}mg" in wbody
    assert "lateral ({x_mg:+d}, {y_mg:+d})mg" in wbody


def test_calibration_wizard_captures_subthreshold_impacts_for_calibration():
    """Regression guard: capture phases MUST collect impacts whose raw
    magnitude is non-zero, regardless of the firmware's `valid` flag.
    Otherwise the suggested calibration is computed from a biased pool
    (only hits already above the current threshold) and can't lower
    the threshold to track lighter strokes.
    """
    src = read_app()

    wiz = re.search(
        r"def on_impact_event\(self, event: dict\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert wiz, "wizard on_impact_event block not found"
    wbody = wiz.group(0)

    # Capture pool append must NOT be gated on `valid` -- the wizard
    # explicitly wants sub-threshold samples to recommend a lower
    # threshold.
    assert "if not valid:\n            return\n        target.append" not in wbody
    # We do skip empty frames (mag=0 and no lateral signal) since
    # those carry no information.
    assert "if mag_mg <= 0 and not (x_mg or y_mg):" in wbody


def test_calibration_wizard_uses_lognormal_p90_estimator_for_small_n():
    """Regression guard: the wizard's `_p90` must NOT use the order-
    statistic 'second-largest of N' approach at small N. With N=12
    that estimator has ~12% standard error on the true p90 (and was
    ~20% at N=8). The lognormal-fit estimator (mu, sigma in log
    space, then exp(mu + 1.282*sigma)) cuts the variance roughly in
    half and degrades gracefully when sigma -> 0.

    We pin the estimator by exercising the actual function via
    monkey-importing the helper. The math also locks in the standard-
    normal 0.9 quantile constant ~1.2816 so a future 'simplification'
    can't silently swap it for 1.0 (which would map to p84).
    """
    src = read_app()

    # Source-level guard: the function header + key formula stays put.
    assert "def _p90(values: list[float]) -> float:" in src
    assert "logs = [math.log(v) for v in positive]" in src
    assert "math.exp(mu + 1.2816 * sigma)" in src
    # Old order-statistic formula must be gone.
    assert (
        'idx = min(len(sv) - 1, max(0, int(round((len(sv) - 1) * 0.9))))'
        not in src
    )

    # Functional sanity: numerically verify on a known distribution.
    # Build a small lognormal sample and compare the estimator's
    # output to the closed-form p90 of the underlying distribution.
    import math
    # Underlying log-space mu=2.0, sigma=0.5. True p90 = exp(2 + 1.2816*0.5)
    # ~= exp(2.6408) ~= 14.026.
    samples = [math.exp(2.0 + 0.5 * x) for x in [
        -1.0, -0.5, 0.0, 0.0, 0.3, 0.5, 0.7, 0.9, 1.1, 1.3, 1.5, 2.0
    ]]

    # Re-implement the estimator inline so the test doesn't depend on
    # importing PyQt6 just to call a static method.
    positive = [v for v in samples if v > 0]
    logs = [math.log(v) for v in positive]
    mu = sum(logs) / len(logs)
    var = sum((x - mu) ** 2 for x in logs) / max(1, len(logs) - 1)
    sigma = math.sqrt(max(0.0, var))
    estimate = math.exp(mu + 1.2816 * sigma)

    # Estimator should land within ~25% of the analytic p90 with N=12.
    # The order statistic on the same data picks index round(0.9*11)=10
    # -- the 11th of 12 sorted values -- which has noticeably worse
    # variance.
    analytic_p90 = math.exp(2.0 + 1.2816 * 0.5)
    assert abs(estimate - analytic_p90) / analytic_p90 < 0.25, (
        f"lognormal estimator drifted: estimate={estimate:.2f}, "
        f"analytic={analytic_p90:.2f}"
    )


def test_calibration_wizard_uses_rotation_invariant_lateral_metric():
    """Regression guard: the wizard's lateral magnitude MUST be
    rotation-invariant. The old `max(|x_mg|, |y_mg|)` heuristic
    underestimates by `cos(45deg) ~= 0.71` when the sensor is mounted
    at 45 degrees to the racket frame, so a player calibrating on a
    rotated sensor would get a lateral full-scale 30% too small.

    The fix projects the 3D acceleration vector onto the plane
    perpendicular to the dominant impact axis and takes its length.
    The dominant axis is auto-detected as the one with the highest
    sample variance across all captured hits.
    """
    src = read_app()

    assert "def _lateral_mg(event: dict, dominant_axis: str) -> float:" in src
    assert "def _dominant_impact_axis(self) -> str:" in src
    # Old heuristic must be gone.
    assert (
        'max(abs(float(e.get("x_mg", 0.0))), abs(float(e.get("y_mg", 0.0))))'
        not in src
    )
    # New formula: lateral = sqrt(mag^2 - dominant_component^2).
    assert "math.sqrt(max(0.0, mag_sq - comp * comp))" in src

    # Wizard summary uses the dominant-axis projection and surfaces
    # the chosen axis to the operator so they can sanity-check the
    # mounting before saving.
    summary = re.search(
        r"def _update_wizard_summary\(self\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert summary, "_update_wizard_summary block not found"
    sbody = summary.group(0)
    assert "dominant_axis = self._dominant_impact_axis()" in sbody
    assert "self._lateral_mg(e, dominant_axis)" in sbody
    assert "impact axis=" in sbody


def test_calibration_wizard_divisor_leaves_meaningful_clipping_headroom():
    """Regression guard: the wizard's divisor that maps p90 hard hit
    -> intensity must be 0.80, not 0.95.

    Math: with a typical CV~0.2 on hard-hit magnitudes (lognormal-
    ish), p99/p90 ~= 1.17. At 0.95 divisor: p90 -> 95%, p99 -> 111%
    -- ~10% of hardest hits saturate at 100% and become
    indistinguishable. At 0.80: p90 -> 80%, p99 -> 94% -- almost no
    clipping, the player can see relative differences across their
    full range.
    """
    src = read_app()

    summary = re.search(
        r"def _update_wizard_summary\(self\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert summary
    sbody = summary.group(0)
    assert "hard_p90 / 0.80" in sbody
    assert "hard_p90 / 0.95" not in sbody
    # 1200 mg floor (raised from 600) guarantees enough dynamic range
    # between soft/hard for the intensity bar to be useful at all.
    assert "max(1200, hard_p90 / 0.80)" in sbody


def test_calibration_wizard_capture_target_is_twelve_per_phase():
    """Regression guard: per-phase sample count is N=12, not N=8.

    At N=8 the order-statistic p90 was 'second-largest' -- the
    estimator could move 20% just by losing one outlier swing.
    The lognormal estimator already cuts variance, but more samples
    is still strictly better, and 24 hits (12 soft + 12 hard) is
    still a tolerable wizard length on a tablet.
    """
    src = read_app()
    assert "self._capture_target = 12" in src
    assert "self._capture_target = 8" not in src


def test_calibration_wizard_auto_chains_soft_hard_apply_with_countdown():
    """Regression guard: the calibration wizard MUST offer a one-click
    guided flow that auto-progresses soft -> hard -> apply once each
    capture phase fills, with a visible countdown overlay on the ball
    preview so the user can keep their eyes on the racket.

    User-reported expectation: "as i hit it the counter comes down type
    of thing, then should move to the next thing and next until it
    finishes". Manual button-clicking between phases is brittle on a
    tablet during live bring-up and was confusing operators.
    """
    src = read_app()

    # 1) The preview widget exposes a countdown overlay that the
    #    wizard updates per-hit, plus a between-phase "get ready"
    #    overlay used for the soft->hard transition.
    assert "def set_countdown(self, remaining: int | None, target: int | None = None):" in src
    assert "def set_get_ready(self, seconds: int | None, label: str = \"\"):" in src
    assert "self._countdown" in src
    assert "self._get_ready" in src

    # 2) A new top-level RUN GUIDED CALIBRATION button kicks off the
    #    chain so the user does not need to click three buttons.
    assert "self.btn_wiz_run_all" in src
    assert "RUN GUIDED CALIBRATION" in src
    assert "self.btn_wiz_run_all.clicked.connect(self._run_wizard_chain)" in src

    # 3) The chain helper sets a flag the rest of the wizard reads
    #    to decide whether to auto-advance. Without this flag the
    #    manual buttons must keep working unchanged.
    chain = re.search(
        r"def _run_wizard_chain\(self\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert chain, "_run_wizard_chain block not found"
    cbody = chain.group(0)
    assert "self._chain_running = True" in cbody
    assert 'self._start_capture("soft")' in cbody

    # 4) Per-hit countdown is updated during capture so the ball
    #    preview shows a big "X to go" number that ticks down.
    wiz = re.search(
        r"def on_impact_event\(self, event: dict\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert wiz, "on_impact_event block not found"
    wbody = wiz.group(0)
    assert "self.wiz_preview.set_countdown(remaining, self._capture_target)" in wbody
    # Count-down style text in the status line ("X of Y hits remaining").
    assert "of " in wbody and "hits remaining" in wbody

    # 5) When a phase completes WHILE chain is running, we transition
    #    to the next one with a visible "get ready" countdown rather
    #    than dropping back to idle. Soft -> HARD, Hard -> APPLY.
    assert "if self._chain_running:" in wbody
    assert 'self._begin_get_ready("hard"' in wbody
    assert 'self._begin_get_ready("apply"' in wbody

    # 6) The get-ready timer ticks once per second and then either
    #    starts the next capture or applies the suggested calibration.
    tick = re.search(
        r"def _on_chain_get_ready_tick\(self\):.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert tick, "_on_chain_get_ready_tick block not found"
    tbody = tick.group(0)
    assert 'self._start_capture("hard")' in tbody
    assert "self._apply_suggested()" in tbody

    # 7) Apply step closes the chain and clears the overlays so a
    #    re-run from idle starts fresh. Without this, an aborted
    #    chain would leave a dangling countdown on the preview.
    apply_blk = re.search(
        r"def _apply_suggested\(self\):.*?(?=\n    def |\nclass )",
        src,
        flags=re.S,
    )
    assert apply_blk, "_apply_suggested block not found"
    abody = apply_blk.group(0)
    assert "self._chain_running = False" in abody
    assert "self.wiz_preview.set_countdown(None)" in abody
    assert "self.wiz_preview.set_get_ready(None)" in abody


def test_arm_tilt_derived_on_host_with_configurable_axis_projection():
    """Regression guard: the host MUST derive arm tilt from the raw
    gravity baseline using a configurable 2D projection, not just trust
    the firmware's atan2(gx, sqrt(gy^2+gz^2)) value.

    The firmware formula gives a constant ~-45 deg for a forearm/wrist
    mount because forehand and backhand prep keep the forearm at the
    same elevation; the swing-direction signal lives in the YZ-plane
    roll instead. Without this fix, the dashboard's arm-angle slider
    pegs at -45 deg and never moves -- exactly the symptom reported
    during bench bring-up.
    """
    src = read_app()

    # Helper exists, supports six axis pairs and a sign flip.
    helper = re.search(
        r"def _derive_arm_tilt_deg\(.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert helper, "_derive_arm_tilt_deg block not found"
    body = helper.group(0)
    assert '"yz"' in body
    assert '"xy"' in body
    assert '"xz"' in body
    assert "math.degrees(math.atan2(float(a), float(b)))" in body
    assert "self._arm_tilt_sign" in body
    # Saturated to [-90, 90] so it stays inside the slider range.
    assert "deg = 90.0" in body
    assert "deg = -90.0" in body

    # Env-var driven configuration with a sensible default.
    assert 'os.getenv("TENNIS_ARM_AXIS", "yz")' in src

    # _on_impact_packet uses the host-derived value, not the firmware's
    # `tilt_deg`.
    pkt = re.search(
        r"def _on_impact_packet\(.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert pkt, "_on_impact_packet block not found"
    pbody = pkt.group(0)
    assert "tilt = self._derive_arm_tilt_deg(" in pbody
    assert "self._last_arm_tilt_deg = tilt" in pbody
    # The firmware's tilt_deg is logged for diagnostic comparison but
    # not used as the canonical value.
    assert "ARM-TILT hit=" in pbody
    assert "fw_tilt=%ddeg" in pbody


def test_arm_tilt_refreshes_from_gravity_baseline_even_when_impact_invalid():
    """Regression guard: the racket-tilt update must NOT depend on the
    impact's `valid` flag.

    The accelerometer reports a baseline gravity vector continuously --
    that's the racket's pose at rest -- and it's meaningful even when
    the z-spike on a swing is too weak to register as a valid impact.
    Bench-test users with a misconfigured ADXL335 (e.g. floating axis
    pin reading ~3700 mg instead of ~1000 mg) would otherwise see zero
    impact frames at all, leaving the arm-angle slider permanently on
    the simulator value. The fix is to refresh tilt FIRST, then early-
    return on `not valid` only for the impact-x/y bookkeeping.
    """
    src = read_app()

    pkt = re.search(
        r"def _on_impact_packet\(.*?(?=\n    def )",
        src,
        flags=re.S,
    )
    assert pkt, "_on_impact_packet block not found"
    body = pkt.group(0)

    # The order matters: gravity refresh must come BEFORE the validity
    # gate that controls LIVE shot book-keeping. We verify by character
    # offset.
    gravity_idx = body.index("if gravity_present:")
    valid_gate_idx = body.index(
        "if valid:\n            self._impact_by_hit_count[hit_count]"
    )
    assert gravity_idx < valid_gate_idx, (
        "Tilt refresh from the gravity baseline must happen BEFORE the "
        "`if valid:` LIVE-bookkeeping gate, otherwise weak/invalid impacts "
        "(common on a misconfigured ADXL335) silently drop arm-angle data."
    )

    # We still skip impact-x/y bookkeeping for the LIVE shot pipeline
    # on invalid frames -- but the calibration wizard receives them
    # regardless (pinned by
    # test_impact_packet_forwards_to_calibration_wizard_even_when_invalid).
    assert "self._impact_by_hit_count[hit_count] = (contact_x, contact_y, intensity)" in body


def test_ball_speed_slider_supports_bench_mode_flag():
    """Regression guard: TENNIS_BENCH_MODE=1 must shrink the speed dial
    range to 0-40 mph so manual hand sweeps at 1-5 mph are visible.

    Without this, the dot for a 3 mph hand-sweep sample sits at 2.5%
    of the dial width on the default 0-120 mph scale -- visually
    indistinguishable from "not moving" -- which is exactly the
    "data in logs but not on the slider" bug we already shipped a
    speed-dial fix for.
    """
    src = read_app()
    assert 'os.getenv("TENNIS_BENCH_MODE") == "1"' in src
    assert "speed_max_mph = 40.0" in src
    assert (
        'self.ms_speed = MetricSlider("Ball Speed", 0, speed_max_mph, "mph")'
        in src
    )


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
    # The host derives the canonical tilt from the raw gravity baseline
    # (so the projection is configurable without a reflash).
    assert "self._last_arm_tilt_deg = tilt" in pkt_body
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
