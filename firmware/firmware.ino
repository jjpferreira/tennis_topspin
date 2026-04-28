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
#include "./include/calibration_store.h"
#include "./include/sensor/ky003_sensor.h"
#include "./include/sensor/adxl335_sensor.h"
#include "./include/bluetooth/ble_handler.h"
#if LED_RING_ENABLED
#include "./include/led/led_handler.h"
#endif

KY003Sensor sensor;
ADXL335Sensor impactSensor;
BLEHandler& bleHandler = BLEHandler::getInstance();
#if LED_RING_ENABLED
LEDHandler& ledHandler = LEDHandler::getInstance();
#endif
static bool g_streamEnabled = BLE_STREAM_DEFAULT_ENABLED != 0;
static uint32_t g_lastStreamKeepaliveMs = 0;
static bool g_streamTimeoutWarned = false;
static ImpactCalibration g_impactCalibration = ADXL335Sensor::defaultCalibration();

static String impactCalibrationToText(const ImpactCalibration& cfg) {
    String out = "CAL:CFG:";
    out += String(cfg.countsPerG, 2);
    out += ",";
    out += String(cfg.impactMgAt100);
    out += ",";
    out += String(cfg.contactFullScaleMg);
    return out;
}

static bool parseCalibrationSetCommand(const String& cmd, ImpactCalibration& out) {
    const String prefix = "CAL:SET:";
    if (!cmd.startsWith(prefix)) return false;
    String body = cmd.substring(prefix.length());
    int c1 = body.indexOf(',');
    int c2 = body.indexOf(',', c1 + 1);
    if (c1 <= 0 || c2 <= c1 + 1) return false;

    float countsPerG = body.substring(0, c1).toFloat();
    long impactMg = body.substring(c1 + 1, c2).toInt();
    long contactMg = body.substring(c2 + 1).toInt();
    if (countsPerG < 50.0f || impactMg < 100 || contactMg < 100) return false;

    out.countsPerG = countsPerG;
    out.impactMgAt100 = static_cast<uint16_t>(impactMg);
    out.contactFullScaleMg = static_cast<uint16_t>(contactMg);
    return true;
}

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

    if (CalibrationStore::loadImpactCalibration(g_impactCalibration)) {
        Logger::info("Impact calibration loaded from NVS");
    } else {
        Logger::info("Impact calibration defaults in use");
    }
    impactSensor.setCalibration(g_impactCalibration);
    sensor.begin();
    impactSensor.begin();
#if LED_RING_ENABLED
    ledHandler.begin();
#endif
    bleHandler.begin();
    bleHandler.startAdvertising();

    Logger::info("BLE advertising started");
}

void loop() {
    uint32_t now = millis();

    bool impactEdge = sensor.update(now);
    impactSensor.update(now);
    if (impactEdge) {
        impactSensor.captureImpact(now);
    }
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
            bleHandler.notifyCommandAck("PONG");
        } else if (cmd == "CAL:GET") {
            bleHandler.notifyCommandAck(impactCalibrationToText(g_impactCalibration).c_str());
        } else if (cmd == "CAL:SAVE") {
            if (CalibrationStore::saveImpactCalibration(g_impactCalibration)) {
                bleHandler.notifyCommandAck("CAL:SAVE:OK");
            } else {
                bleHandler.notifyCommandAck("CAL:SAVE:ERR");
            }
        } else if (cmd == "CAL:RESET") {
            g_impactCalibration = ADXL335Sensor::defaultCalibration();
            impactSensor.setCalibration(g_impactCalibration);
            if (CalibrationStore::saveImpactCalibration(g_impactCalibration)) {
                bleHandler.notifyCommandAck("CAL:RESET:OK");
            } else {
                bleHandler.notifyCommandAck("CAL:RESET:ERR");
            }
            bleHandler.notifyCommandAck(impactCalibrationToText(g_impactCalibration).c_str());
        } else if (cmd.startsWith("CAL:SET:")) {
            ImpactCalibration incoming = g_impactCalibration;
            if (parseCalibrationSetCommand(cmd, incoming)) {
                g_impactCalibration = incoming;
                impactSensor.setCalibration(g_impactCalibration);
                bleHandler.notifyCommandAck("CAL:SET:OK");
                bleHandler.notifyCommandAck(impactCalibrationToText(g_impactCalibration).c_str());
            } else {
                bleHandler.notifyCommandAck("CAL:SET:ERR");
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
    if (impactEdge && isStreamActive(now)) {
        ImpactSample impact = impactSensor.getLastImpact();
        bleHandler.pushImpact(
            sensor.getHitCount(),
            impact.xMg,
            impact.yMg,
            impact.zMg,
            impact.intensityPct,
            impact.contactX,
            impact.contactY
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
