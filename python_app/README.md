# Realtime Tennis Monitor

Desktop app for the `_apps/tennis/firmware/firmware.ino` project.

## Run

From repo root:

```bash
python3 -m pip install -r _apps/tennis/python_app/requirements.txt
python3 _apps/tennis/python_app/realtime_tennis_monitor.py
```

## What it does

- Scans for BLE devices named `TENNIS_KY003*`
- Connects and subscribes to live notify characteristics
- Shows:
  - current sensor state (0/1)
  - trigger count
  - trigger rate (events/sec)
- Draws a lightweight live sparkline of trigger rate
- Sends `RESET` command to firmware via BLE write
