from pathlib import Path
import re


TENNIS_APP_ROOT = Path(__file__).resolve().parents[1]
TENNIS_FW_ROOT = TENNIS_APP_ROOT / "firmware"

CONFIG_H = TENNIS_FW_ROOT / "include" / "config.h"
VERSION_H = TENNIS_FW_ROOT / "include" / "firmware_version.h"
BLE_CONSTANTS_H = TENNIS_FW_ROOT / "include" / "bluetooth" / "ble_constants.h"
BLE_HANDLER_H = TENNIS_FW_ROOT / "include" / "bluetooth" / "ble_handler.h"
BLE_HANDLER_CPP = TENNIS_FW_ROOT / "src" / "bluetooth" / "ble_handler.cpp"
SENSOR_H = TENNIS_FW_ROOT / "include" / "sensor" / "ky003_sensor.h"
SENSOR_CPP = TENNIS_FW_ROOT / "src" / "sensor" / "ky003_sensor.cpp"
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


def test_tennis_ble_contract_has_service_and_expected_characteristics():
    ble_constants = read_text(BLE_CONSTANTS_H)
    ble_handler_h = read_text(BLE_HANDLER_H)
    ble_handler_cpp = read_text(BLE_HANDLER_CPP)

    assert '#define TENNIS_SERVICE_UUID' in ble_constants
    for name in ("TENNIS_STATE_UUID", "TENNIS_COUNT_UUID", "TENNIS_RATE_X10_UUID", "TENNIS_COMMAND_UUID"):
        assert f"#define {name}" in ble_constants

    assert "void pushTelemetry(uint8_t state, uint32_t count, uint16_t rateX10);" in ble_handler_h
    assert "_stateChar->notify();" in ble_handler_cpp
    assert "_countChar->notify();" in ble_handler_cpp
    assert "_rateChar->notify();" in ble_handler_cpp
    assert "BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR" in ble_handler_cpp


def test_tennis_streaming_is_explicitly_armed_and_keepalive_guarded():
    sketch = read_text(SKETCH)
    config = read_text(CONFIG_H)

    assert "#define BLE_STREAM_DEFAULT_ENABLED 0" in config
    assert "#define BLE_STREAM_REQUIRE_KEEPALIVE 1" in config
    assert "#define BLE_STREAM_KEEPALIVE_TIMEOUT_MS 5000u" in config

    assert "static bool g_streamEnabled = BLE_STREAM_DEFAULT_ENABLED != 0;" in sketch
    assert "static bool isStreamActive(uint32_t nowMs)" in sketch
    assert "if ((nowMs - g_lastStreamKeepaliveMs) > BLE_STREAM_KEEPALIVE_TIMEOUT_MS)" in sketch
    assert 'else if (cmd == "STREAM:ON")' in sketch
    assert 'else if (cmd == "STREAM:OFF")' in sketch
    assert 'else if (cmd == "PING")' in sketch
    assert "if (!bleHandler.isConnected()) {" in sketch
    assert "&& isStreamActive(now)" in sketch


def test_tennis_sensor_logic_uses_debounce_edge_count_and_rate_window():
    sensor_h = read_text(SENSOR_H)
    sensor_cpp = read_text(SENSOR_CPP)
    config_h = read_text(CONFIG_H)

    assert "void update(uint32_t nowMs);" in sensor_h
    assert "uint16_t getRateX10(uint32_t nowMs) const;" in sensor_h
    assert "bool shouldCountEdge(uint8_t previous, uint8_t current) const;" in sensor_h
    assert "#define KY003_DEBOUNCE_MS 8u" in config_h
    assert "#define KY003_RATE_WINDOW_MS 5000u" in config_h

    assert "if (raw != _stableState && (nowMs - _rawChangedAt) >= KY003_DEBOUNCE_MS)" in sensor_cpp
    assert "if (shouldCountEdge(prev, _stableState)) {" in sensor_cpp
    assert "_hitCount++;" in sensor_cpp
    assert "uint32_t cutoff = nowMs - KY003_RATE_WINDOW_MS;" in sensor_cpp
    assert "float rateX10 = (10000.0f * static_cast<float>(inWindow)) / static_cast<float>(KY003_RATE_WINDOW_MS);" in sensor_cpp


def test_tennis_firmware_loop_keeps_commands_deferred_and_non_blocking():
    sketch = read_text(SKETCH)
    ble_handler_cpp = read_text(BLE_HANDLER_CPP)

    assert "if (bleHandler.hasDeferredCommand()) {" in sketch
    assert "String cmd = bleHandler.takeDeferredCommand();" in sketch
    assert "setDeferredCommand(command);" in ble_handler_cpp
    assert "xSemaphoreTake(_cmdMutex, portMAX_DELAY);" in ble_handler_cpp
    assert "xSemaphoreGive(_cmdMutex);" in ble_handler_cpp

