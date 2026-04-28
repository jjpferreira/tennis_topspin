#pragma once

#include "firmware_version.h"

#define APP_NAME "TENNIS_KY003"
#define APP_VERSION FIRMWARE_VERSION_STRING

// Hardware pins
#define STATUS_LED_PIN 2
#define KY003_PIN 4
#define KY003_GATE_START_PIN 26
#define KY003_GATE_END_PIN 27
#define ADXL335_X_PIN 34
#define ADXL335_Y_PIN 35
#define ADXL335_Z_PIN 32

// KY-003 signal handling
#define KY003_INPUT_PULLUP 1
#define KY003_COUNT_ON_FALLING_EDGE 1
#define KY003_DEBOUNCE_MS 8u
#define KY003_RATE_WINDOW_MS 5000u
#define KY003_EDGE_HISTORY_LEN 256
#define KY003_GATE_DISTANCE_CM 3.0f
#define KY003_GATE_MIN_TRANSIT_MS 1u
#define KY003_GATE_MAX_TRANSIT_MS 250u

// ADXL335 impact capture (analog accelerometer)
#define ADXL335_SAMPLE_INTERVAL_MS 4u
#define ADXL335_BASELINE_SAMPLES 32u
#define ADXL335_BASELINE_ALPHA 0.015f
#define ADXL335_IMPACT_SAMPLES 12u
#define ADXL335_IMPACT_SAMPLE_SPACING_US 850u
#define ADXL335_COUNTS_PER_G 410.0f
#define ADXL335_IMPACT_MG_AT_100 4200
#define ADXL335_CONTACT_FULL_SCALE_MG 1500
#define ADXL335_MIN_VALID_IMPACT_MG 250

// BLE telemetry pacing
#define BLE_FAST_NOTIFY_INTERVAL_MS 50u
#define BLE_RECONNECT_COOLDOWN_MS 800u
#define BLE_STREAM_DEFAULT_ENABLED 0
#define BLE_STREAM_REQUIRE_KEEPALIVE 1
#define BLE_STREAM_KEEPALIVE_TIMEOUT_MS 5000u

// Data scaling used over BLE
#define RATE_X10_SCALE 10.0f

// WS2812 NeoPixel ring — aligned with GhostFinder EMFDetector-LiLyGo `config.h` LED section
#define LED_RING_ENABLED 1
#define LED_PIN 12
#define LED_COUNT 24
/** 1 = solid white on LED 0 only (find LED0 physical heading vs bearing math) */
#define LED_RING_CALIBRATION_MODE 0
/** Math angle (deg) at centre of LED index 0 — see EMFDetector config comments */
#define LED_RING_LED0_CENTER_DEG 0.0f
/** +1 = LED index increases CCW from above; -1 = CW (typical WS2812 rings) */
#define LED_RING_INDEX_ANGLE_SIGN (-1.0f)
/**
 * 0 = classic: fixed 20% sweep base, no direction wedge
 * 1 = direction wedge on idle breathing only; sweep base scales with level
 * 2 = direction on sweep + flash as well
 */
#define LED_DIRECTION_MODE 0
#define LED_DIRECTION_SHADE_IDLE_ONLY (LED_DIRECTION_MODE == 1)

/** Blocking sweep demo speed (ms); used by sweepEffect() */
#define SCAN_SPEED 50

/** Tier thresholds (float). KY-003: hits/s via getRateX10()/RATE_X10_SCALE; magnetometer: use µT */
#define LED_LEVEL_T1 0.5f
#define LED_LEVEL_T2 1.0f
#define LED_LEVEL_T3 2.0f
#define LED_LEVEL_T4 4.0f
#define LED_LEVEL_T5 8.0f
#define LED_UPDATE_INTERVAL_MS 20u
