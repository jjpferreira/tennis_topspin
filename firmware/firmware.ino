/*
  firmware.ino
  ------------------------------------------------------------
  Modular tennis firmware following the same architectural
  pattern used in the Ghost firmware:
    - config + BLE constants headers
    - sensor handler module
    - BLE handler singleton with deferred commands
    - orchestration in setup()/loop()
*/

#include <Arduino.h>
#include "./include/config.h"
#include "./include/logger.h"
#include "./include/sensor/ky003_sensor.h"
#include "./include/bluetooth/ble_handler.h"
#if LED_RING_ENABLED
#include "./include/led/led_handler.h"
#endif

KY003Sensor sensor;
BLEHandler& bleHandler = BLEHandler::getInstance();
#if LED_RING_ENABLED
LEDHandler& ledHandler = LEDHandler::getInstance();
#endif
static bool g_streamEnabled = BLE_STREAM_DEFAULT_ENABLED != 0;
static uint32_t g_lastStreamKeepaliveMs = 0;
static bool g_streamTimeoutWarned = false;

static bool isStreamActive(uint32_t nowMs) {
    if (!g_streamEnabled) return false;
#if BLE_STREAM_REQUIRE_KEEPALIVE
    if ((nowMs - g_lastStreamKeepaliveMs) > BLE_STREAM_KEEPALIVE_TIMEOUT_MS) {
        g_streamEnabled = false;
        if (!g_streamTimeoutWarned) {
            Logger::warn("Live stream disabled: keepalive timeout");
            g_streamTimeoutWarned = true;
        }
        return false;
    }
#endif
    return true;
}

void setup() {
    Serial.begin(115200);
    pinMode(STATUS_LED_PIN, OUTPUT);
    digitalWrite(STATUS_LED_PIN, LOW);

    Logger::info(String(APP_NAME) + " " + FIRMWARE_VERSION_DISPLAY + " booting");

    sensor.begin();
#if LED_RING_ENABLED
    ledHandler.begin();
#endif
    bleHandler.begin();
    bleHandler.startAdvertising();

    Logger::info("BLE advertising started");
}

void loop() {
    uint32_t now = millis();

    sensor.update(now);
    bleHandler.processReconnect(now);

    if (bleHandler.hasDeferredCommand()) {
        String cmd = bleHandler.takeDeferredCommand();
        if (cmd == "RESET") {
            sensor.reset();
            Logger::info("Counter reset command applied");
        } else if (cmd == "STREAM:ON") {
            g_streamEnabled = true;
            g_lastStreamKeepaliveMs = now;
            g_streamTimeoutWarned = false;
            Logger::info("Live stream armed");
        } else if (cmd == "STREAM:OFF") {
            g_streamEnabled = false;
            Logger::info("Live stream disarmed");
        } else if (cmd == "PING") {
            g_lastStreamKeepaliveMs = now;
            g_streamTimeoutWarned = false;
            if (!g_streamEnabled) {
                g_streamEnabled = true;
                Logger::info("Live stream auto-armed by keepalive");
            }
        } else {
            Logger::warn("Unknown command: " + cmd);
        }
    }

    if (!bleHandler.isConnected()) {
        g_streamEnabled = false;
        g_streamTimeoutWarned = false;
    }

    static uint32_t lastNotifyMs = 0;
    if ((now - lastNotifyMs) >= BLE_FAST_NOTIFY_INTERVAL_MS && isStreamActive(now)) {
        lastNotifyMs = now;
        bleHandler.pushTelemetry(
            sensor.getState(),
            sensor.getHitCount(),
            sensor.getRateX10(now)
        );
    }

#if LED_RING_ENABLED
    static uint32_t s_lastLedMs = 0;
    if ((now - s_lastLedMs) >= LED_UPDATE_INTERVAL_MS) {
        s_lastLedMs = now;
        float hitsPerSec =
            static_cast<float>(sensor.getRateX10(now)) / RATE_X10_SCALE;
        ledHandler.updateLevel(hitsPerSec);
        ledHandler.update();
    }
#endif
}
