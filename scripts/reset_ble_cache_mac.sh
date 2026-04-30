#!/usr/bin/env bash
set -euo pipefail

echo "BLE cache reset helper (macOS)"
echo
echo "Before continuing:"
echo "  1) Quit Tennis Topspin app"
echo "  2) Power OFF the ESP32 sensor"
echo
read -r -p "Press Enter to open Bluetooth Settings..."

open "x-apple.systempreferences:com.apple.BluetoothSettings"

echo
echo "In Bluetooth Settings:"
echo "  - Find TENNIS_KY003"
echo "  - Click (i) and choose 'Forget This Device'"
echo
read -r -p "After forgetting the device, press Enter to restart bluetoothd..."

if sudo pkill -HUP bluetoothd; then
  echo "bluetoothd restarted successfully."
else
  echo "Could not restart bluetoothd (permission denied or process not found)." >&2
fi

echo
echo "Next steps:"
echo "  1) Reboot Mac (recommended for stubborn GATT cache)"
echo "  2) Power ON ESP32"
echo "  3) Reconnect from app"
echo
echo "Expected app log after success:"
echo "  - GATT characteristics discovered (9)"
echo "  - Includes gate-speed and fw-version"
