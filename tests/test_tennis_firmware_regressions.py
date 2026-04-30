from pathlib import Path
import re


TENNIS_APP_ROOT = Path(__file__).resolve().parents[1]
TENNIS_FW_ROOT = TENNIS_APP_ROOT / "firmware"

CONFIG_H = TENNIS_FW_ROOT / "include" / "config.h"
VERSION_H = TENNIS_FW_ROOT / "include" / "firmware_version.h"
BLE_CONSTANTS_H = TENNIS_FW_ROOT / "include" / "bluetooth" / "ble_constants.h"
BLE_HANDLER_H = TENNIS_FW_ROOT / "include" / "bluetooth" / "ble_handler.h"
BLE_HANDLER_CPP = TENNIS_FW_ROOT / "src" / "bluetooth" / "ble_handler.cpp"
SENSOR_H = TENNIS_FW_ROOT / "include" / "ky003" / "ky003_sensor.h"
SENSOR_CPP = TENNIS_FW_ROOT / "src" / "ky003" / "ky003_sensor.cpp"
ADXL_H = TENNIS_FW_ROOT / "include" / "adxl335" / "adxl335_sensor.h"
ADXL_CPP = TENNIS_FW_ROOT / "src" / "adxl335" / "adxl335_sensor.cpp"
CAL_STORE_H = TENNIS_FW_ROOT / "include" / "calibration_store.h"
CAL_STORE_CPP = TENNIS_FW_ROOT / "src" / "calibration_store.cpp"
SKETCH = TENNIS_FW_ROOT / "firmware.ino"


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_tennis_firmware_version_is_semver_and_exported_to_config():
    version_h = read_text(VERSION_H)
    config_h = read_text(CONFIG_H)

    match = re.search(r'#define FIRMWARE_VERSION_STRING "(\d+\.\d+\.\d+)"', version_h)
    assert match, "Firmware version must be explicit semver"
    assert '#define FIRMWARE_VERSION_DISPLAY "v" FIRMWARE_VERSION_STRING' in version_h
    assert "#define APP_VERSION FIRMWARE_VERSION_STRING" in config_h


def test_tennis_advertised_name_breaks_macos_gatt_cache():
    """The BLE peripheral name must end with a "_V<n>" suffix so that bumping it
    in the future invalidates the macOS CoreBluetooth GATT cache (which
    re-uses cached profiles per peripheral name + service UUID even after
    Forget Device + bluetoothd restart on stubborn machines)."""
    config_h = read_text(CONFIG_H)
    ble_constants = read_text(BLE_CONSTANTS_H)

    name_match = re.search(r'#define APP_NAME "(TENNIS_KY003(?:_V\d+)?)"', config_h)
    assert name_match, "APP_NAME must be set in config.h with the TENNIS_KY003[_Vn] convention"
    assert name_match.group(1).startswith("TENNIS_KY003"), (
        "APP_NAME must keep the TENNIS_KY003 prefix so the python app's "
        "NAME_PREFIX scan filter still matches."
    )

    svc_match = re.search(
        r'#define TENNIS_SERVICE_UUID\s+"([0-9a-fA-F\-]{36})"', ble_constants
    )
    assert svc_match, "TENNIS_SERVICE_UUID must be defined"


def test_tennis_firmware_build_stamp_uses_compiler_macros():
    """Each compile must produce a fresh FIRMWARE_BUILD_STAMP because we rely
    on it (over BLE and on serial) to confirm a flash actually deployed new
    code. The C preprocessor injects __DATE__ and __TIME__ at every build."""
    version_h = read_text(VERSION_H)
    assert "#define FIRMWARE_BUILD_STAMP __DATE__" in version_h
    assert "__TIME__" in version_h
    assert "#define FIRMWARE_INFO_STRING" in version_h
    assert "FIRMWARE_VERSION_DISPLAY" in version_h
    assert "FIRMWARE_BUILD_STAMP" in version_h


def test_tennis_firmware_info_string_is_emitted_on_serial_at_boot_and_periodically():
    sketch = read_text(SKETCH)
    assert "FIRMWARE_INFO_STRING" in sketch, (
        "firmware.ino must broadcast FIRMWARE_INFO_STRING so each flash is identifiable"
    )
    assert "[BOOT]" in sketch, "Boot banner must include the [BOOT] tag"
    assert "publishFirmwareHeartbeat" in sketch, (
        "Periodic [FW] heartbeat function must exist in firmware.ino"
    )
    assert "[FW]" in sketch, "Periodic firmware heartbeat must use [FW] tag"


def test_tennis_ble_service_reserves_enough_gatt_handles():
    """ESP32 Arduino BLE silently drops characteristics past handle 15 because
    BLEServer::createService(uuid) defaults to numHandles=15. With 8 notify
    chars (each consuming 3 handles via CCCD) plus 1 read-only fw-version
    char, we need an explicit, generously-sized handle budget. This test
    pins the explicit createService overload so the bug can't regress
    silently if someone adds another characteristic."""
    ble_handler_cpp = read_text(BLE_HANDLER_CPP)

    # The buggy form (single-arg createService) MUST NOT be present anymore.
    assert "createService(TENNIS_SERVICE_UUID)" not in ble_handler_cpp, (
        "BLEServer::createService(uuid) defaults to numHandles=15 and silently "
        "drops characteristics past that. Use the explicit "
        "createService(BLEUUID(...), numHandles, instanceId) form instead."
    )

    pattern = re.compile(
        r"createService\(\s*BLEUUID\(\s*TENNIS_SERVICE_UUID\s*\)\s*,\s*(\d+)\s*,\s*0\s*\)"
    )
    match = pattern.search(ble_handler_cpp)
    assert match, (
        "BLE service must be created via the explicit handle-budget overload: "
        "createService(BLEUUID(TENNIS_SERVICE_UUID), <numHandles>, 0)"
    )
    num_handles = int(match.group(1))
    # 1 service + 8 notify chars (3 handles each) + 1 read-only char (2 handles)
    # = 27 handles minimum. Anything below 28 is at risk if we add metadata.
    assert num_handles >= 28, (
        f"GATT handle budget {num_handles} is too small for the current "
        "9-characteristic profile (need >=28 handles)."
    )


def test_tennis_ble_profile_is_self_described_on_serial():
    """The firmware must announce its own GATT profile on Serial so the
    operator can prove (without macOS in the loop) that the running build
    really exposes all 9 characteristics — service UUID, device name,
    bluetooth MAC, and every char UUID with its tag."""
    ble_handler_h = read_text(BLE_HANDLER_H)
    ble_handler_cpp = read_text(BLE_HANDLER_CPP)
    sketch = read_text(SKETCH)

    assert "void logProfileToSerial();" in ble_handler_h
    assert "void publishProfileHeartbeat(uint32_t nowMs);" in ble_handler_h
    assert "uint8_t characteristicCount() const;" in ble_handler_h

    assert "void BLEHandler::logProfileToSerial()" in ble_handler_cpp
    assert "[GATT] device_name=" in ble_handler_cpp
    assert "[GATT] mac=" in ble_handler_cpp
    assert "[GATT] service_uuid=" in ble_handler_cpp
    assert "[GATT] characteristic_count=" in ble_handler_cpp
    assert "[GATT-HB] svc=" in ble_handler_cpp
    for tag in (
        '"state"',
        '"count"',
        '"rate"',
        '"rpm"',
        '"impact"',
        '"gate-speed"',
        '"health"',
        '"fw-version"',
        '"command"',
    ):
        assert tag in ble_handler_cpp, (
            f"BLE profile log must label characteristic with tag {tag}"
        )
    assert "[BLE] client connected" in ble_handler_cpp
    assert "[BLE] client disconnected" in ble_handler_cpp
    assert "logProfileToSerial();" in ble_handler_cpp

    assert "bleHandler.publishProfileHeartbeat(now);" in sketch
    assert "BLE advertising started as" in sketch
    assert "TENNIS_SERVICE_UUID" in sketch
    assert "bleHandler.characteristicCount()" in sketch


def test_tennis_firmware_version_is_published_over_ble():
    """The firmware build identifier must be exposed as a read-only BLE
    characteristic so the dashboard can confirm flash freshness without
    requiring a serial monitor."""
    ble_constants = read_text(BLE_CONSTANTS_H)
    ble_handler_h = read_text(BLE_HANDLER_H)
    ble_handler_cpp = read_text(BLE_HANDLER_CPP)
    assert "#define TENNIS_FW_VERSION_UUID" in ble_constants
    assert "_fwVersionChar" in ble_handler_h
    assert "TENNIS_FW_VERSION_UUID" in ble_handler_cpp
    assert "_fwVersionChar->setValue(FIRMWARE_INFO_STRING)" in ble_handler_cpp
    assert "PROPERTY_READ" in ble_handler_cpp


def test_tennis_ble_contract_has_service_and_expected_characteristics():
    ble_constants = read_text(BLE_CONSTANTS_H)
    ble_handler_h = read_text(BLE_HANDLER_H)
    ble_handler_cpp = read_text(BLE_HANDLER_CPP)

    assert '#define TENNIS_SERVICE_UUID' in ble_constants
    for name in (
        "TENNIS_STATE_UUID",
        "TENNIS_COUNT_UUID",
        "TENNIS_RATE_X10_UUID",
        "TENNIS_RPM_X10_UUID",
        "TENNIS_IMPACT_UUID",
        "TENNIS_GATE_SPEED_UUID",
        "TENNIS_HEALTH_UUID",
        "TENNIS_FW_VERSION_UUID",
        "TENNIS_COMMAND_UUID",
    ):
        assert f"#define {name}" in ble_constants

    assert "void pushTelemetry(uint8_t state, uint32_t count, uint16_t rateX10, uint16_t rpmX10);" in ble_handler_h
    assert "void pushImpact(" in ble_handler_h
    assert "void pushGateSpeed(" in ble_handler_h
    assert "uint16_t magnitudeMg," in ble_handler_h
    assert "bool validImpact" in ble_handler_h
    assert "void notifyCommandAck(const char* utf8);" in ble_handler_h
    assert "_stateChar->notify();" in ble_handler_cpp
    assert "_countChar->notify();" in ble_handler_cpp
    assert "_rateChar->notify();" in ble_handler_cpp
    assert "_rpmChar->notify();" in ble_handler_cpp
    assert "_impactChar->notify();" in ble_handler_cpp
    assert "_gateSpeedChar->notify();" in ble_handler_cpp
    assert "uint16_t magnitudeMg;" in ble_handler_cpp
    assert "uint8_t flags;" in ble_handler_cpp
    assert "uint16_t speedKmhX10;" in ble_handler_cpp
    assert "uint32_t transitUs;" in ble_handler_cpp
    assert "TENNIS_COMMAND_UUID" in ble_handler_cpp
    assert "BLECharacteristic::PROPERTY_NOTIFY" in ble_handler_cpp
    assert "BLECharacteristic::PROPERTY_WRITE" in ble_handler_cpp
    assert "void BLEHandler::notifyCommandAck(const char* utf8)" in ble_handler_cpp


def test_tennis_streaming_defaults_to_on_without_keepalive_gate():
    sketch = read_text(SKETCH)
    config = read_text(CONFIG_H)

    assert "#define BLE_STREAM_DEFAULT_ENABLED 1" in config
    assert "#define BLE_STREAM_REQUIRE_KEEPALIVE 0" in config
    assert "#define BLE_STREAM_KEEPALIVE_TIMEOUT_MS 5000u" in config

    assert "static bool g_streamEnabled = BLE_STREAM_DEFAULT_ENABLED != 0;" in sketch
    assert "static bool isStreamActive(uint32_t nowMs)" in sketch
    assert "if ((nowMs - g_lastStreamKeepaliveMs) > BLE_STREAM_KEEPALIVE_TIMEOUT_MS)" in sketch
    assert 'if (cmd == "STREAM:ON")' in sketch
    assert 'if (cmd == "STREAM:OFF")' in sketch
    assert 'if (cmd == "PING")' in sketch
    assert 'bleHandler.notifyCommandAck("PONG")' in sketch
    assert "const bool nowConnected = bleHandler.isConnected();" in sketch
    assert "if ((nowMs - lastNotifyMs) >= BLE_FAST_NOTIFY_INTERVAL_MS && isStreamActive(nowMs)) {" in sketch


def test_tennis_sensor_health_telemetry_is_published():
    sketch = read_text(SKETCH)
    ble_handler_h = read_text(BLE_HANDLER_H)
    ble_handler_cpp = read_text(BLE_HANDLER_CPP)

    assert "void pushHealth(" in ble_handler_h
    assert "void BLEHandler::pushHealth(" in ble_handler_cpp
    assert "_healthChar->notify();" in ble_handler_cpp
    assert "TENNIS_HEALTH_UUID" in ble_handler_cpp

    assert "static void publishSensorHealth(uint32_t nowMs)" in sketch
    assert "publishSensorHealth(now);" in sketch
    assert "bleHandler.pushHealth(" in sketch
    assert "sensor.getLastEdgeMs()" in sketch
    assert "gateStartSensor.getLastEdgeMs()" in sketch
    assert "gateEndSensor.getLastEdgeMs()" in sketch
    assert "impactSensor.getLastImpactMs()" in sketch
    assert "impactSensor.getBaselineMagnitudeMg()" in sketch


def test_tennis_stream_is_rearmed_on_each_new_client_connection():
    """Regression guard for the bug where the default-on stream flag was
    cleared in the not-connected branch of publishBleTelemetry, so commandless
    devices never received telemetry after boot.
    """
    sketch = read_text(SKETCH)

    publish_marker = "static void publishBleTelemetry"
    publish_idx = sketch.find(publish_marker)
    assert publish_idx >= 0, "publishBleTelemetry function must exist"

    # Walk forward to find the function body and the next top-level function so
    # we only inspect publishBleTelemetry itself.
    next_static = sketch.find("\nstatic ", publish_idx + len(publish_marker))
    next_void = sketch.find("\nvoid ", publish_idx + len(publish_marker))
    end_candidates = [c for c in (next_static, next_void) if c >= 0]
    publish_end = min(end_candidates) if end_candidates else len(sketch)
    publish_body = sketch[publish_idx:publish_end]

    # Edge-trigger pattern: track previous connection state and re-arm on rise.
    assert "static bool s_wasConnected" in publish_body, (
        "publishBleTelemetry must remember previous connection state"
    )
    assert "g_streamEnabled = (BLE_STREAM_DEFAULT_ENABLED != 0);" in publish_body, (
        "publishBleTelemetry must re-arm g_streamEnabled to firmware default on a fresh client connection"
    )

    # Anti-pattern guard: do NOT clear g_streamEnabled while the device is just
    # waiting for a client. That was the regression that silenced telemetry.
    not_connected_idx = publish_body.find("if (!nowConnected)")
    assert not_connected_idx >= 0, "expected the disconnected branch in publishBleTelemetry"
    next_brace = publish_body.find("}", not_connected_idx)
    assert next_brace >= 0
    not_connected_branch = publish_body[not_connected_idx:next_brace]
    assert "g_streamEnabled = false" not in not_connected_branch, (
        "publishBleTelemetry must not auto-disable the stream while waiting for a client"
    )


def test_tennis_sensor_logic_uses_debounce_edge_count_and_rate_window():
    sensor_h = read_text(SENSOR_H)
    sensor_cpp = read_text(SENSOR_CPP)
    config_h = read_text(CONFIG_H)

    assert "explicit KY003Sensor(" in sensor_h
    assert "uint8_t pin = KY003_PIN" in sensor_h
    assert "_pin;" in sensor_h
    assert "_countOnFallingEdge;" in sensor_h
    assert "_debounceMs;" in sensor_h
    assert "_rateWindowMs;" in sensor_h
    assert "bool update(uint32_t nowMs);" in sensor_h
    assert "uint16_t getRateX10(uint32_t nowMs) const;" in sensor_h
    assert "bool shouldCountEdge(uint8_t previous, uint8_t current) const;" in sensor_h
    assert "#define KY003_DEBOUNCE_MS 8u" in config_h
    assert "#define KY003_GATE_DEBOUNCE_MS 1u" in config_h
    assert "#define KY003_RATE_WINDOW_MS 5000u" in config_h
    assert "#define KY003_GATE_START_PIN" in config_h
    assert "#define KY003_GATE_END_PIN" in config_h
    assert "#define KY003_GATE_DISTANCE_CM 3.0f" in config_h
    assert "#define KY003_GATE_MIN_TRANSIT_US 500u" in config_h
    assert "#define KY003_GATE_MAX_TRANSIT_US 10000000u" in config_h
    assert "#define KY003_RPM_PULSES_PER_REV 1u" in config_h
    assert "#define KY003_RPM_FRESHNESS_MS 2500u" in config_h

    assert "pinMode(_pin, _inputPullup ? INPUT_PULLUP : INPUT);" in sensor_cpp
    assert "digitalRead(_pin)" in sensor_cpp
    assert "if (raw != _stableState && (nowMs - _rawChangedAt) >= _debounceMs)" in sensor_cpp
    assert "if (shouldCountEdge(prev, _stableState)) {" in sensor_cpp
    assert "_hitCount++;" in sensor_cpp
    assert "uint32_t cutoff = nowMs - _rateWindowMs;" in sensor_cpp
    assert "float rateX10 = (10000.0f * static_cast<float>(inWindow)) / static_cast<float>(_rateWindowMs);" in sensor_cpp


def test_tennis_impact_sensor_module_is_wired_and_configured():
    adxl_h = read_text(ADXL_H)
    adxl_cpp = read_text(ADXL_CPP)
    cal_h = read_text(CAL_STORE_H)
    cal_cpp = read_text(CAL_STORE_CPP)
    sketch = read_text(SKETCH)
    config = read_text(CONFIG_H)

    assert "#define ADXL335_X_PIN" in config
    assert "#define ADXL335_Y_PIN" in config
    assert "#define ADXL335_Z_PIN" in config
    assert "#define ADXL335_IMPACT_SAMPLES" in config
    assert "#define ADXL335_MIN_VALID_IMPACT_MG" in config
    assert "class ADXL335Sensor" in adxl_h
    assert "struct ImpactCalibration" in adxl_h
    assert "uint16_t minValidImpactMg = 0;" in adxl_h
    assert "uint16_t magnitudeMg = 0;" in adxl_h
    assert "bool valid = false;" in adxl_h
    assert "void setCalibration(const ImpactCalibration& cfg);" in adxl_h
    assert "ImpactCalibration defaultCalibration();" in adxl_h
    assert "struct ImpactSample" in adxl_h
    assert "void captureImpact(uint32_t nowMs);" in adxl_h
    assert "void ADXL335Sensor::captureImpact(uint32_t nowMs)" in adxl_cpp
    assert "void ADXL335Sensor::setCalibration(const ImpactCalibration& cfg)" in adxl_cpp
    assert "ImpactCalibration ADXL335Sensor::defaultCalibration()" in adxl_cpp
    assert "analogReadResolution(12);" in adxl_cpp
    assert "cfg.minValidImpactMg = ADXL335_MIN_VALID_IMPACT_MG;" in adxl_cpp
    assert "const bool validImpact = magMgClamped >= _calibration.minValidImpactMg;" in adxl_cpp
    assert "_lastImpact.magnitudeMg = magMgClamped;" in adxl_cpp
    assert "_lastImpact.valid = validImpact;" in adxl_cpp
    assert "class CalibrationStore" in cal_h
    assert "loadImpactCalibration" in cal_h
    assert "saveImpactCalibration" in cal_h
    assert "loadRuntimeConfig" in cal_h
    assert "saveRuntimeConfig" in cal_h
    assert "Preferences" in cal_cpp
    assert "constexpr const char* kMinValidKey = \"imp_min\";" in cal_cpp
    assert "constexpr const char* kGateDistKey = \"gate_cm\";" in cal_cpp
    assert "constexpr const char* kRpmPprKey = \"rpm_ppr\";" in cal_cpp
    assert "constexpr uint8_t kImpactCalibrationVersion = 2;" in cal_cpp
    assert "out.minValidImpactMg = prefs.getUShort(kMinValidKey, out.minValidImpactMg);" in cal_cpp
    assert "prefs.putUShort(kMinValidKey, cfg.minValidImpactMg);" in cal_cpp
    assert "ADXL335Sensor impactSensor;" in sketch
    assert "ImpactCalibration g_impactCalibration" in sketch
    assert "CalibrationStore::loadImpactCalibration" in sketch
    assert "CalibrationStore::loadRuntimeConfig(g_gateDistanceCm, g_rpmPulsesPerRev)" in sketch
    assert "sensor.getInstantRpmX10(" in sketch
    assert "KY003_RPM_FRESHNESS_MS" in sketch
    assert "if (cmd == \"GATE:GET\")" in sketch
    assert "if (cmd.startsWith(\"GATE:SET:\"))" in sketch
    assert "if (cmd == \"RPM:GET\")" in sketch
    assert "if (cmd.startsWith(\"RPM:SET:\"))" in sketch
    assert 'if (cmd == "CAL:GET")' in sketch
    assert 'if (cmd == "CAL:SAVE")' in sketch
    assert 'if (cmd == "CAL:RESET")' in sketch
    assert 'if (cmd.startsWith("CAL:SET:"))' in sketch
    assert "out += String(cfg.minValidImpactMg);" in sketch
    assert "long minValidMg = out.minValidImpactMg > 0 ? out.minValidImpactMg : ADXL335_MIN_VALID_IMPACT_MG;" in sketch
    assert "impactSensor.captureImpact(nowMs);" in sketch
    assert "bleHandler.pushImpact(" in sketch
    assert "gateStartSensor.begin();" in sketch
    assert "gateEndSensor.begin();" in sketch
    assert "static_cast<uint16_t>(KY003_GATE_DEBOUNCE_MS)" in sketch
    assert "updateGateSpeedState(nowUs, gateStartEdge, gateEndEdge);" in sketch
    assert "const bool hadPendingStart = g_gateSpeed.awaitingEnd;" in sketch
    assert "if (startEdge && hadPendingStart)" in sketch
    assert "bleHandler.pushGateSpeed(g_gateSpeed.sampleId, g_gateSpeed.speedKmhX10, g_gateSpeed.transitUs);" in sketch
    # Diagnostic logs must remain so we can see why a gate sample fails when
    # the magnet sweep is reportedly working but no speed packet arrives.
    assert "[GATE] start edge t=" in sketch
    assert "[GATE] sample #" in sketch
    assert "[GATE] end edge dt=" in sketch
    assert "[GATE] timeout" in sketch
    assert "IGNORED — no pending start" in sketch
    assert "[GATE-PUB] BLE notify sample #" in sketch
    # Reconnect-safety: do not let a stale armed start leak across sessions.
    assert "g_gateSpeed.awaitingEnd = false;" in sketch
    assert "impact.magnitudeMg," in sketch
    assert "impact.valid" in sketch


def test_tennis_firmware_loop_keeps_commands_deferred_and_non_blocking():
    sketch = read_text(SKETCH)
    ble_handler_cpp = read_text(BLE_HANDLER_CPP)

    assert "static void processBleCommands(uint32_t nowMs)" in sketch
    assert "if (!bleHandler.hasDeferredCommand()) {" in sketch
    assert "String cmd = bleHandler.takeDeferredCommand();" in sketch
    assert "setDeferredCommand(command);" in ble_handler_cpp
    assert "xSemaphoreTake(_cmdMutex, portMAX_DELAY);" in ble_handler_cpp
    assert "xSemaphoreGive(_cmdMutex);" in ble_handler_cpp

