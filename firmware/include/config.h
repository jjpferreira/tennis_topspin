#pragma once

#include "firmware_version.h"

// Bumping the suffix invalidates macOS CoreBluetooth's per-peripheral GATT
// cache by making the device look brand new (different advertised name +
// service UUID = no cached profile). This is the only reliable way to force
// macOS to re-discover the full 9-characteristic profile when "Forget Device"
// + bluetoothd restart aren't enough.
#define APP_NAME "TENNIS_KY003_V2"
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
#define KY003_GATE_DEBOUNCE_MS 1u
#define KY003_RATE_WINDOW_MS 5000u
#define KY003_EDGE_HISTORY_LEN 256
// Physical centre-to-centre spacing of the two KY-003 gate sensors, in cm.
// The compile-time default is what we burn into NVS on first boot; the
// runtime value can be overridden over BLE via `GATE:SET:<cm>` + `GATE:SAVE`,
// then reset to this default with `GATE:RESET`. Keep this value in sync with
// `python_app/hardware_config.py::GATE_DISTANCE_CM`. The Python app reads
// the runtime value from the firmware on connect, so the dashboard always
// reflects ground truth, but the Python constant is the canonical "what the
// rig is supposed to be" used for self-tests and offline analysis.
//
// Sizing rationale: at 4.5 cm spacing, the 500 us min-transit guard caps
// measurable speed at 4.5*36000/500 = 324 km/h -- comfortably above any
// real serve. A previous 1.0 cm rig silently dropped anything faster than
// 72 km/h because transit times sub-500us were rejected as glitches.
#define KY003_GATE_DISTANCE_CM 4.5f
#define KY003_GATE_MIN_TRANSIT_US 500u
// Allow slow hand-driven A->B magnet passes during bench validation. A real
// ball pass takes <5ms (well under 1% of this ceiling), so widening the window
// only affects the "no pending start" reset behaviour for manual testing.
// Bumping to 10s lets the operator move the magnet at any speed without losing
// the armed start, then reset by sweeping again.
#define KY003_GATE_MAX_TRANSIT_US 10000000u
#define KY003_RPM_PULSES_PER_REV 1u
// Keep RPM visible a bit longer between pulses so live dashboards do not look
// dead during low-frequency manual testing.
#define KY003_RPM_FRESHNESS_MS 2500u

// ADXL335 impact capture (analog accelerometer)
#define ADXL335_SAMPLE_INTERVAL_MS 4u
#define ADXL335_BASELINE_SAMPLES 32u
#define ADXL335_BASELINE_ALPHA 0.015f
// Magnitude (in mg) above which the EWMA baseline updater stops
// integrating new samples, so a swing's pre-contact acceleration
// (typically 3000-15000 mg sustained over 300-600 ms) cannot leak
// into the resting baseline. Above noise from slow rig movement
// (~300 mg) and below a real swing (>=3000 mg).
#define ADXL335_BASELINE_FREEZE_MG 2000.0f
#define ADXL335_IMPACT_SAMPLES 12u
#define ADXL335_IMPACT_SAMPLE_SPACING_US 850u
// How many ADC reads to average into a single per-axis sample inside
// the impact burst. Cuts the radio-correlated SAR ADC noise floor by
// ~sqrt(N). Each read is ~12 us so 4x oversample fits comfortably
// inside the 850 us spacing window.
#define ADXL335_ADC_OVERSAMPLE 4u
#define ADXL335_COUNTS_PER_G 410.0f
#define ADXL335_IMPACT_MG_AT_100 4200
#define ADXL335_CONTACT_FULL_SCALE_MG 1500
#define ADXL335_MIN_VALID_IMPACT_MG 250

// BLE telemetry pacing
#define BLE_FAST_NOTIFY_INTERVAL_MS 50u
#define BLE_RECONNECT_COOLDOWN_MS 800u
#define BLE_STREAM_DEFAULT_ENABLED 1
#define BLE_STREAM_REQUIRE_KEEPALIVE 0
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
