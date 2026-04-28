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

## BLE Data Model

- `state` (uint8): current debounced KY-003 level (0/1)
- `count` (uint32): cumulative trigger count
- `rate_x10` (uint16): trigger rate in events/sec * 10
- `command` (UTF-8 write): supports `RESET`

## Notes

- This project is isolated under `_apps/tennis`.
- No original GhostFinder files were modified.
