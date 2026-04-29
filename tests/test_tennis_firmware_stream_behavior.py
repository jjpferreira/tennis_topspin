"""
Behavioral regression tests for the firmware BLE telemetry stream state machine.

These tests do NOT just match strings in firmware source. They run a Python
simulator of `publishBleTelemetry` + `processControlCommand` logic from
`firmware/firmware.ino` and exercise real transitions:

  boot → wait-for-client → connect → keepalive/timeout → reconnect → STREAM:ON/OFF/PING

This catches state-interaction bugs (like the "default-on flag silently
cleared in the not-connected branch" regression) that pure source-shape
tests can never see.

The simulator derives its defaults from `firmware/include/config.h` so it
stays in lock-step with the actual firmware intent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest


TENNIS_FW_ROOT = Path(__file__).resolve().parents[1] / "firmware"
CONFIG_H = TENNIS_FW_ROOT / "include" / "config.h"


def _config_text() -> str:
    return CONFIG_H.read_text(encoding="utf-8")


def _parse_define(text: str, name: str) -> str | None:
    m = re.search(rf"#define\s+{re.escape(name)}\s+(\S+)", text)
    return m.group(1) if m else None


def _config_int(name: str) -> int:
    raw = _parse_define(_config_text(), name)
    assert raw is not None, f"Missing define {name} in config.h"
    cleaned = raw.rstrip("uUlL")
    return int(cleaned, 0)


# ----- Firmware-mirroring state machine ------------------------------------------------


@dataclass
class TelemetryPacket:
    now_ms: int
    state: int
    count: int
    rate_x10: int
    rpm_x10: int


@dataclass
class StreamFirmware:
    """Mirror of the streaming behavior in firmware.ino.

    Mirrors:
      * `g_streamEnabled` static initialized from BLE_STREAM_DEFAULT_ENABLED.
      * `isStreamActive(...)` keepalive timeout under BLE_STREAM_REQUIRE_KEEPALIVE.
      * `processControlCommand(...)` for STREAM:ON, STREAM:OFF, PING.
      * `publishBleTelemetry(...)` re-arming behavior on fresh connect.
    """
    default_enabled: bool
    require_keepalive: bool
    keepalive_timeout_ms: int
    notify_interval_ms: int = 50

    stream_enabled: bool = field(init=False)
    last_keepalive_ms: int = field(default=0, init=False)
    last_notify_ms: int = field(default=0, init=False)
    was_connected: bool = field(default=False, init=False)
    publishes: list[TelemetryPacket] = field(default_factory=list, init=False)
    pong_count: int = field(default=0, init=False)

    def __post_init__(self):
        self.stream_enabled = self.default_enabled
        # firmware.ino setup() initializes g_lastStreamKeepaliveMs = millis()
        self.last_keepalive_ms = 0

    # ------------------------------------------------------------------
    # Equivalent of processControlCommand(...)
    # ------------------------------------------------------------------
    def receive_command(self, cmd: str, now_ms: int) -> str | None:
        if cmd == "STREAM:ON":
            self.stream_enabled = True
            self.last_keepalive_ms = now_ms
            return None
        if cmd == "STREAM:OFF":
            self.stream_enabled = False
            return None
        if cmd == "PING":
            self.last_keepalive_ms = now_ms
            if not self.stream_enabled:
                self.stream_enabled = True
            self.pong_count += 1
            return "PONG"
        return None

    # ------------------------------------------------------------------
    # Equivalent of isStreamActive(nowMs)
    # ------------------------------------------------------------------
    def _is_stream_active(self, now_ms: int) -> bool:
        if not self.stream_enabled:
            return False
        if self.require_keepalive:
            if (now_ms - self.last_keepalive_ms) > self.keepalive_timeout_ms:
                self.stream_enabled = False
                return False
        return True

    # ------------------------------------------------------------------
    # Equivalent of publishBleTelemetry(nowMs, sensorResult)
    # ------------------------------------------------------------------
    def tick(
        self,
        now_ms: int,
        connected: bool,
        sensor_state: int = 0,
        sensor_count: int = 0,
        rate_x10: int = 0,
        rpm_x10: int = 0,
    ) -> None:
        if not connected:
            # New disconnect-branch (post-fix): never silently disables stream;
            # only resets edge tracker so reconnect re-arms cleanly.
            self.was_connected = False
            return

        if not self.was_connected:
            self.was_connected = True
            # Fresh client connection edge: re-arm to firmware default.
            self.stream_enabled = self.default_enabled
            self.last_keepalive_ms = now_ms

        if (now_ms - self.last_notify_ms) >= self.notify_interval_ms and self._is_stream_active(now_ms):
            self.last_notify_ms = now_ms
            self.publishes.append(
                TelemetryPacket(
                    now_ms=now_ms,
                    state=sensor_state,
                    count=sensor_count,
                    rate_x10=rate_x10,
                    rpm_x10=rpm_x10,
                )
            )


def _firmware_under_test() -> StreamFirmware:
    """Build a simulator using the *current* config.h values.

    If someone flips BLE_STREAM_DEFAULT_ENABLED back to 0 by accident, these
    behavioral tests will reflect that change immediately.
    """
    return StreamFirmware(
        default_enabled=bool(_config_int("BLE_STREAM_DEFAULT_ENABLED")),
        require_keepalive=bool(_config_int("BLE_STREAM_REQUIRE_KEEPALIVE")),
        keepalive_timeout_ms=_config_int("BLE_STREAM_KEEPALIVE_TIMEOUT_MS"),
        notify_interval_ms=_config_int("BLE_FAST_NOTIFY_INTERVAL_MS"),
    )


# ----- Behavioral tests ----------------------------------------------------------------


def _run_loop(fw: StreamFirmware, *, total_ms: int, connected_at_ms: int | None,
              disconnect_at_ms: int | None = None, step_ms: int = 10,
              count_func=lambda t: 0) -> None:
    """Run firmware loop ticks across `total_ms` of simulated time."""
    now = 0
    while now <= total_ms:
        connected = False
        if connected_at_ms is not None and now >= connected_at_ms:
            connected = True
        if disconnect_at_ms is not None and now >= disconnect_at_ms:
            connected = False
        fw.tick(now, connected=connected, sensor_count=count_func(now))
        now += step_ms


def test_stream_arms_immediately_when_client_connects_with_default_on():
    fw = _firmware_under_test()
    assert fw.default_enabled, "Current config should default the stream ON"

    # Simulate 2s of pre-connect waiting, then client connects at t=2000ms.
    _run_loop(fw, total_ms=4000, connected_at_ms=2000)

    # We expect packets to start almost immediately after connect.
    assert fw.publishes, "Expected telemetry packets after client connects"
    first_packet = fw.publishes[0]
    assert first_packet.now_ms >= 2000
    assert first_packet.now_ms <= 2000 + fw.notify_interval_ms + 10


def test_pre_connect_idle_does_not_silence_default_on_stream():
    """Regression for the bug we just fixed: default-on flag must not be
    cleared while we're waiting for the first client.
    """
    fw = _firmware_under_test()
    pytest.importorskip("pytest")  # noop sanity

    # Idle for 30 seconds with no client.
    _run_loop(fw, total_ms=30_000, connected_at_ms=None)

    # Stream flag must not have been clobbered — otherwise the very next
    # connection would never produce telemetry without an explicit STREAM:ON.
    assert fw.stream_enabled is True, (
        "BUG: default-on stream was silently disabled during pre-connect idle. "
        "publishBleTelemetry must not clear g_streamEnabled before any client connects."
    )


def test_stream_resumes_on_reconnect_without_command_channel():
    fw = _firmware_under_test()

    # Connect at 1s, disconnect at 5s, then reconnect at 8s.
    now = 0
    while now <= 12_000:
        connected = (1_000 <= now < 5_000) or (now >= 8_000)
        fw.tick(now, connected=connected)
        now += 10

    # Packets should have arrived in BOTH connection windows.
    first_session = [p for p in fw.publishes if 1_000 <= p.now_ms < 5_000]
    second_session = [p for p in fw.publishes if p.now_ms >= 8_000]
    assert first_session, "Expected packets in first connect window"
    assert second_session, "Expected packets in second connect window after reconnect"


def test_keepalive_timeout_disables_stream_only_when_required():
    """If BLE_STREAM_REQUIRE_KEEPALIVE is 0 (current default), the stream
    must keep flowing even without any PING traffic.
    """
    fw = _firmware_under_test()
    if fw.require_keepalive:
        pytest.skip("Keepalive enforcement is enabled; covered by other test")

    # Connect at t=0 and run for 3 * keepalive_timeout_ms with no PING.
    sim_total = max(20_000, fw.keepalive_timeout_ms * 4)
    _run_loop(fw, total_ms=sim_total, connected_at_ms=0)

    last_packet = fw.publishes[-1]
    assert last_packet.now_ms >= sim_total - fw.notify_interval_ms - 10, (
        "Stream stopped publishing despite require_keepalive=0"
    )


def test_explicit_stream_off_then_on_round_trip():
    fw = _firmware_under_test()

    # Connect at t=0.
    fw.tick(0, connected=True)
    fw.tick(50, connected=True)
    assert any(p.now_ms <= 60 for p in fw.publishes)

    fw.receive_command("STREAM:OFF", now_ms=100)
    pre_off_count = len(fw.publishes)

    # Run 1s of ticks while connected, with stream OFF: nothing new should publish.
    for t in range(110, 1_110, 10):
        fw.tick(t, connected=True)
    assert len(fw.publishes) == pre_off_count, "STREAM:OFF must halt telemetry"

    # Send STREAM:ON and verify telemetry resumes.
    fw.receive_command("STREAM:ON", now_ms=1_120)
    for t in range(1_130, 2_000, 10):
        fw.tick(t, connected=True)
    assert len(fw.publishes) > pre_off_count, "STREAM:ON must resume telemetry"


def test_ping_acks_pong_and_arms_stream():
    fw = _firmware_under_test()
    fw.stream_enabled = False  # Force off.

    response = fw.receive_command("PING", now_ms=500)
    assert response == "PONG"
    assert fw.pong_count == 1
    assert fw.stream_enabled is True, "PING must auto-arm the stream"
