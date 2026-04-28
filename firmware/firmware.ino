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
#include "./include/ky003/ky003_sensor.h"
#include "./include/adxl335/adxl335_sensor.h"
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
    out += ",";
    out += String(cfg.minValidImpactMg);
    return out;
}

static bool parseCalibrationSetCommand(const String& cmd, ImpactCalibration& out) {
    const String prefix = "CAL:SET:";
    if (!cmd.startsWith(prefix)) return false;
    String body = cmd.substring(prefix.length());
    int c1 = body.indexOf(',');
    int c2 = body.indexOf(',', c1 + 1);
    int c3 = body.indexOf(',', c2 + 1);
    if (c1 <= 0 || c2 <= c1 + 1) return false;

    float countsPerG = body.substring(0, c1).toFloat();
    long impactMg = body.substring(c1 + 1, c2).toInt();
    long contactMg = 0;
    long minValidMg = out.minValidImpactMg > 0 ? out.minValidImpactMg : ADXL335_MIN_VALID_IMPACT_MG;
    if (c3 > c2 + 1) {
        contactMg = body.substring(c2 + 1, c3).toInt();
        minValidMg = body.substring(c3 + 1).toInt();
    } else {
        contactMg = body.substring(c2 + 1).toInt();
    }
    if (countsPerG < 50.0f || impactMg < 100 || contactMg < 100 || minValidMg < 50) return false;

    out.countsPerG = countsPerG;
    out.impactMgAt100 = static_cast<uint16_t>(impactMg);
    out.contactFullScaleMg = static_cast<uint16_t>(contactMg);
    out.minValidImpactMg = static_cast<uint16_t>(minValidMg);
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

static void applyImpactCalibration(const ImpactCalibration& cfg) {
    g_impactCalibration = cfg;
    impactSensor.setCalibration(g_impactCalibration);
}

static void processControlCommand(const String& cmd, uint32_t nowMs) {
    if (cmd == "RESET") {
        sensor.reset();
        Logger::info("Counter reset command applied");
        return;
    }
    if (cmd == "STREAM:ON") {
        g_streamEnabled = true;
        g_lastStreamKeepaliveMs = nowMs;
        g_streamTimeoutWarned = false;
        Logger::info("Live stream armed");
        return;
    }
    if (cmd == "STREAM:OFF") {
        g_streamEnabled = false;
        Logger::info("Live stream disarmed");
        return;
    }
    if (cmd == "PING") {
        g_lastStreamKeepaliveMs = nowMs;
        g_streamTimeoutWarned = false;
        if (!g_streamEnabled) {
            g_streamEnabled = true;
            Logger::info("Live stream auto-armed by keepalive");
        }
        bleHandler.notifyCommandAck("PONG");
        return;
    }
    if (cmd == "CAL:GET") {
        bleHandler.notifyCommandAck(impactCalibrationToText(g_impactCalibration).c_str());
        return;
    }
    if (cmd == "CAL:SAVE") {
        if (CalibrationStore::saveImpactCalibration(g_impactCalibration)) {
            bleHandler.notifyCommandAck("CAL:SAVE:OK");
        } else {
            bleHandler.notifyCommandAck("CAL:SAVE:ERR");
        }
        return;
    }
    if (cmd == "CAL:RESET") {
        applyImpactCalibration(ADXL335Sensor::defaultCalibration());
        if (CalibrationStore::saveImpactCalibration(g_impactCalibration)) {
            bleHandler.notifyCommandAck("CAL:RESET:OK");
        } else {
            bleHandler.notifyCommandAck("CAL:RESET:ERR");
        }
        bleHandler.notifyCommandAck(impactCalibrationToText(g_impactCalibration).c_str());
        return;
    }
    if (cmd.startsWith("CAL:SET:")) {
        ImpactCalibration incoming = g_impactCalibration;
        if (parseCalibrationSetCommand(cmd, incoming)) {
            applyImpactCalibration(incoming);
            bleHandler.notifyCommandAck("CAL:SET:OK");
            bleHandler.notifyCommandAck(impactCalibrationToText(g_impactCalibration).c_str());
        } else {
            bleHandler.notifyCommandAck("CAL:SET:ERR");
        }
        return;
    }
    Logger::warn("Unknown command: " + cmd);
}

static bool runSensorPipeline(uint32_t nowMs) {
    bool impactEdge = sensor.update(nowMs);
    impactSensor.update(nowMs);
    if (impactEdge) {
        impactSensor.captureImpact(nowMs);
    }
    return impactEdge;
}

static void processBleCommands(uint32_t nowMs) {
    bleHandler.processReconnect(nowMs);
    if (!bleHandler.hasDeferredCommand()) {
        return;
    }
    String cmd = bleHandler.takeDeferredCommand();
    processControlCommand(cmd, nowMs);
}

static void publishBleTelemetry(uint32_t nowMs, bool impactEdge) {
    if (!bleHandler.isConnected()) {
        g_streamEnabled = false;
        g_streamTimeoutWarned = false;
        return;
    }

    static uint32_t lastNotifyMs = 0;
    if ((nowMs - lastNotifyMs) >= BLE_FAST_NOTIFY_INTERVAL_MS && isStreamActive(nowMs)) {
        lastNotifyMs = nowMs;
        bleHandler.pushTelemetry(
            sensor.getState(),
            sensor.getHitCount(),
            sensor.getRateX10(nowMs)
        );
    }

    if (!impactEdge || !isStreamActive(nowMs)) {
        return;
    }

    ImpactSample impact = impactSensor.getLastImpact();
    if (!impact.valid) {
        return;
    }

    bleHandler.pushImpact(
        sensor.getHitCount(),
        impact.xMg,
        impact.yMg,
        impact.zMg,
        impact.magnitudeMg,
        impact.intensityPct,
        impact.contactX,
        impact.contactY,
        impact.valid
    );
}

static void updateLedFeedback(uint32_t nowMs) {
#if LED_RING_ENABLED
    static uint32_t s_lastLedMs = 0;
    if ((nowMs - s_lastLedMs) >= LED_UPDATE_INTERVAL_MS) {
        s_lastLedMs = nowMs;
        float hitsPerSec =
            static_cast<float>(sensor.getRateX10(nowMs)) / RATE_X10_SCALE;
        ledHandler.updateLevel(hitsPerSec);
        ledHandler.update();
    }
#else
    (void)nowMs;
#endif
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
    applyImpactCalibration(g_impactCalibration);
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
    bool impactEdge = runSensorPipeline(now);
    processBleCommands(now);
    publishBleTelemetry(now, impactEdge);
    updateLedFeedback(now);
}
