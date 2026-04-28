# Tennis BLE Sensor App (KY-003)

This folder contains a **new standalone project** that reuses the same architecture style as the GhostFinder BLE stack, but for a tennis use case.

## Goal

Stream fast magnetic trigger data from an ESP32 + **KY-003 magnetic sensor** to a Python desktop app over BLE.

## Structure

- `firmware/firmware.ino`
  - Main orchestration loop (same style as Ghost firmware main sketch)
- `firmware/include/config.h`
  - Pin map, timing, debounce, and BLE pacing constants
- `firmware/include/bluetooth/ble_constants.h`
  - UUIDs for service + characteristics
- `firmware/include/bluetooth/ble_handler.h`
- `firmware/src/bluetooth/ble_handler.cpp`
  - BLE singleton with reconnect handling + deferred command queue
- `firmware/include/ky003/ky003_sensor.h`
- `firmware/src/ky003/ky003_sensor.cpp`
  - KY-003 debounce, edge counting, and rate window logic
- `python_app/realtime_tennis_monitor.py`
  - PyQt6 + Bleak desktop live monitor
  - Connects to BLE device, displays state/counter/rate, and plots live hit rate

## Firmware Wiring Header (Sensor Pin Table)

Use this as the quick wiring reference for the ESP32 firmware.

| Sensor / Module | Purpose | ESP32 Pin | Config Key |
|---|---|---:|---|
| KY-003 (main trigger) | Hit edge/count/rate base signal | `GPIO 4` | `KY003_PIN` |
| KY-003 gate start | Ball speed timing start gate | `GPIO 26` | `KY003_GATE_START_PIN` |
| KY-003 gate end | Ball speed timing end gate | `GPIO 27` | `KY003_GATE_END_PIN` |
| ADXL335 X | Impact axis X analog input | `GPIO 34` | `ADXL335_X_PIN` |
| ADXL335 Y | Impact axis Y analog input | `GPIO 35` | `ADXL335_Y_PIN` |
| ADXL335 Z | Impact axis Z analog input | `GPIO 32` | `ADXL335_Z_PIN` |
| Status LED | BLE connection status | `GPIO 2` | `STATUS_LED_PIN` |
| WS2812 LED ring (optional) | Visual feedback ring data line | `GPIO 12` | `LED_PIN` |

Reference distance for gate speed timing:
- `KY003_GATE_DISTANCE_CM = 3.0` (start-to-end sensor spacing)
- Main KY-003 also feeds RPM derivation (`KY003_RPM_PULSES_PER_REV`) via trigger rate conversion.

## BLE Data Model

- `state` (uint8): current debounced KY-003 level (0/1)
- `count` (uint32): cumulative trigger count
- `rate_x10` (uint16): trigger rate in events/sec * 10
- `command` (UTF-8 write): supports `RESET`

## Notes

- This project is isolated under `_apps/tennis`.
- No original GhostFinder files were modified.
