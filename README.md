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
- `KY003_GATE_DISTANCE_CM = 4.3` (centre-to-centre sensor spacing in cm). At this spacing the firmware's 500&nbsp;µs min-transit guard caps measurable speed at ~310&nbsp;km/h, comfortably above any real serve.
- Main KY-003 also feeds RPM derivation (`KY003_RPM_PULSES_PER_REV`) via trigger rate conversion.

> **Single source of truth for physical-rig constants.** The same gate
> distance and pulses-per-rev values live in two places — both must be
> updated together whenever the hardware changes:
>
> 1. `firmware/include/config.h` (compile-time defaults baked into firmware)
> 2. `python_app/hardware_config.py` (Python-side defaults and analysis)
>
> A regression test (`tests/test_python_app_ble_regressions.py`) fails the
> build if the two ever drift, because a mismatch silently scales every
> recorded shot speed by the wrong factor with no other visible symptom.
> The firmware's NVS-stored runtime value can still be overridden on the
> fly via the BLE `GATE:SET:<cm>` / `GATE:SAVE` commands; that override is
> treated as ground truth for live sessions and the Python constant is the
> default used until the firmware reports its own value.

## BLE Data Model

- `state` (uint8): current debounced KY-003 level (0/1)
- `count` (uint32): cumulative trigger count
- `rate_x10` (uint16): trigger rate in events/sec * 10
- `command` (UTF-8 write): supports `RESET`

## Logging

The Python app uses Python's `logging` module with three named loggers:

- `tennis.app` — top-level lifecycle (startup, shutdown).
- `tennis.ble` — BLE worker: connect/disconnect, GATT enumeration, notify pipelines.
- `tennis.ui`  — dashboard reactions (chip updates, popups, button presses).

Output destinations:

- **Console (stderr):** `INFO` and above by default. Set `TENNIS_LOG_DEBUG=1`
  to enable `DEBUG` on the console as well.
- **Rotating file (always DEBUG):** `python_app/logs/tennis_monitor.log`
  with up to 5 × 5 MB backups. Override the directory with `TENNIS_LOG_DIR=/path`.

When something goes wrong (BLE flake, GATT cache stale, missing characteristics),
attach `python_app/logs/tennis_monitor.log` to the bug report — every connect
attempt is captured with full GATT enumeration, firmware build identifier,
notify counts and any recovery actions.

Quick examples:

```bash
# Default (INFO on console, DEBUG to file):
./python_app/realtime_tennis_monitor.py

# Verbose console:
TENNIS_LOG_DEBUG=1 ./python_app/realtime_tennis_monitor.py

# Custom log directory:
TENNIS_LOG_DIR=~/Desktop/tennis-logs ./python_app/realtime_tennis_monitor.py
```

## Notes

- This project is isolated under `_apps/tennis`.
- No original GhostFinder files were modified.
