#pragma once

#include "firmware_version.h"

#define APP_NAME "TENNIS_KY003"
#define APP_VERSION FIRMWARE_VERSION_STRING

// Hardware pins
#define STATUS_LED_PIN 2
#define KY003_PIN 4

// KY-003 signal handling
#define KY003_INPUT_PULLUP 1
#define KY003_COUNT_ON_FALLING_EDGE 1
#define KY003_DEBOUNCE_MS 8u
#define KY003_RATE_WINDOW_MS 5000u
#define KY003_EDGE_HISTORY_LEN 256

// BLE telemetry pacing
#define BLE_FAST_NOTIFY_INTERVAL_MS 50u
#define BLE_RECONNECT_COOLDOWN_MS 800u
#define BLE_STREAM_DEFAULT_ENABLED 0
#define BLE_STREAM_REQUIRE_KEEPALIVE 1
#define BLE_STREAM_KEEPALIVE_TIMEOUT_MS 5000u

// Data scaling used over BLE
#define RATE_X10_SCALE 10.0f
