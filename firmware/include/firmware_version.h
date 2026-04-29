#pragma once

// Manual semver. Bump when the BLE/serial protocol changes in any way.
#define FIRMWARE_VERSION_STRING "1.1.0"
#define FIRMWARE_VERSION_DISPLAY "v" FIRMWARE_VERSION_STRING

// __DATE__ and __TIME__ are inserted by the C preprocessor at COMPILE time, so
// FIRMWARE_BUILD_STAMP changes every time the sketch is rebuilt. Use it (and
// the boot-time and BLE broadcasts in firmware.ino / ble_handler.cpp) to
// confirm at-a-glance that a fresh firmware was actually flashed onto the
// ESP32.
#define FIRMWARE_BUILD_STAMP __DATE__ " " __TIME__

// Convenience full-info string. Format:
//   "tennis-fw v1.1.0 build Apr 29 2026 14:35:21"
#define FIRMWARE_INFO_STRING \
    "tennis-fw " FIRMWARE_VERSION_DISPLAY " build " FIRMWARE_BUILD_STAMP
