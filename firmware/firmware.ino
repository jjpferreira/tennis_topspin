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
KY003Sensor gateStartSensor(KY003_GATE_START_PIN);
KY003Sensor gateEndSensor(KY003_GATE_END_PIN);
ADXL335Sensor impactSensor;
BLEHandler& bleHandler = BLEHandler::getInstance();
#if LED_RING_ENABLED
LEDHandler& ledHandler = LEDHandler::getInstance();
#endif
static bool g_streamEnabled = BLE_STREAM_DEFAULT_ENABLED != 0;
static uint32_t g_lastStreamKeepaliveMs = 0;
static bool g_streamTimeoutWarned = false;
static ImpactCalibration g_impactCalibration = ADXL335Sensor::defaultCalibration();
static float g_gateDistanceCm = KY003_GATE_DISTANCE_CM;
static uint16_t g_rpmPulsesPerRev = KY003_RPM_PULSES_PER_REV;

struct GateSpeedState {
    bool awaitingEnd = false;
    uint32_t startUs = 0;
    uint32_t sampleId = 0;
    bool ready = false;
    uint16_t speedKmhX10 = 0;
    uint32_t transitUs = 0;
};
static GateSpeedState g_gateSpeed;

struct SensorPipelineResult {
    bool impactEdge = false;
    bool gateSpeedReady = false;
};

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

static uint16_t computeRpmX10(uint16_t rateX10) {
    if (g_rpmPulsesPerRev == 0) return 0;
    const uint32_t rpmX10 = (static_cast<uint32_t>(rateX10) * 60u) / static_cast<uint32_t>(g_rpmPulsesPerRev);
    return static_cast<uint16_t>(constrain(static_cast<int>(rpmX10), 0, 65535));
}

static String gateConfigToText() {
    String out = "GATE:CFG:";
    out += String(g_gateDistanceCm, 3);
    return out;
}

static String rpmConfigToText() {
    String out = "RPM:CFG:";
    out += String(g_rpmPulsesPerRev);
    return out;
}

static void updateGateSpeedState(uint32_t nowUs, bool startEdge, bool endEdge) {
    if (g_gateSpeed.awaitingEnd && (nowUs - g_gateSpeed.startUs) > KY003_GATE_MAX_TRANSIT_US) {
        g_gateSpeed.awaitingEnd = false;
    }
    if (startEdge) {
        g_gateSpeed.awaitingEnd = true;
        g_gateSpeed.startUs = nowUs;
        return;
    }
    if (!g_gateSpeed.awaitingEnd || !endEdge || nowUs <= g_gateSpeed.startUs) {
        return;
    }
    uint32_t dtUs = nowUs - g_gateSpeed.startUs;
    g_gateSpeed.awaitingEnd = false;
    if (dtUs < KY003_GATE_MIN_TRANSIT_US || dtUs > KY003_GATE_MAX_TRANSIT_US) {
        return;
    }

    // km/h * 10 = (distance_cm * 360000) / dt_us
    float kmhX10f = (g_gateDistanceCm * 360000.0f) / static_cast<float>(dtUs);
    if (kmhX10f < 0.0f) kmhX10f = 0.0f;
    if (kmhX10f > 65535.0f) kmhX10f = 65535.0f;

    g_gateSpeed.sampleId++;
    g_gateSpeed.transitUs = dtUs;
    g_gateSpeed.speedKmhX10 = static_cast<uint16_t>(kmhX10f);
    g_gateSpeed.ready = true;
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
        bleHandler.notifyCommandAck(gateConfigToText().c_str());
        bleHandler.notifyCommandAck(rpmConfigToText().c_str());
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
    if (cmd == "GATE:GET") {
        bleHandler.notifyCommandAck(gateConfigToText().c_str());
        return;
    }
    if (cmd.startsWith("GATE:SET:")) {
        float cm = cmd.substring(String("GATE:SET:").length()).toFloat();
        if (cm >= 0.5f && cm <= 100.0f) {
            g_gateDistanceCm = cm;
            bleHandler.notifyCommandAck("GATE:SET:OK");
            bleHandler.notifyCommandAck(gateConfigToText().c_str());
        } else {
            bleHandler.notifyCommandAck("GATE:SET:ERR");
        }
        return;
    }
    if (cmd == "GATE:SAVE") {
        if (CalibrationStore::saveRuntimeConfig(g_gateDistanceCm, g_rpmPulsesPerRev)) {
            bleHandler.notifyCommandAck("GATE:SAVE:OK");
        } else {
            bleHandler.notifyCommandAck("GATE:SAVE:ERR");
        }
        return;
    }
    if (cmd == "GATE:RESET") {
        g_gateDistanceCm = KY003_GATE_DISTANCE_CM;
        if (CalibrationStore::saveRuntimeConfig(g_gateDistanceCm, g_rpmPulsesPerRev)) {
            bleHandler.notifyCommandAck("GATE:RESET:OK");
        } else {
            bleHandler.notifyCommandAck("GATE:RESET:ERR");
        }
        bleHandler.notifyCommandAck(gateConfigToText().c_str());
        return;
    }
    if (cmd == "RPM:GET") {
        bleHandler.notifyCommandAck(rpmConfigToText().c_str());
        return;
    }
    if (cmd.startsWith("RPM:SET:")) {
        long ppr = cmd.substring(String("RPM:SET:").length()).toInt();
        if (ppr >= 1 && ppr <= 128) {
            g_rpmPulsesPerRev = static_cast<uint16_t>(ppr);
            bleHandler.notifyCommandAck("RPM:SET:OK");
            bleHandler.notifyCommandAck(rpmConfigToText().c_str());
        } else {
            bleHandler.notifyCommandAck("RPM:SET:ERR");
        }
        return;
    }
    if (cmd == "RPM:SAVE") {
        if (CalibrationStore::saveRuntimeConfig(g_gateDistanceCm, g_rpmPulsesPerRev)) {
            bleHandler.notifyCommandAck("RPM:SAVE:OK");
        } else {
            bleHandler.notifyCommandAck("RPM:SAVE:ERR");
        }
        return;
    }
    if (cmd == "RPM:RESET") {
        g_rpmPulsesPerRev = KY003_RPM_PULSES_PER_REV;
        if (CalibrationStore::saveRuntimeConfig(g_gateDistanceCm, g_rpmPulsesPerRev)) {
            bleHandler.notifyCommandAck("RPM:RESET:OK");
        } else {
            bleHandler.notifyCommandAck("RPM:RESET:ERR");
        }
        bleHandler.notifyCommandAck(rpmConfigToText().c_str());
        return;
    }
    Logger::warn("Unknown command: " + cmd);
}

static SensorPipelineResult runSensorPipeline(uint32_t nowMs, uint32_t nowUs) {
    SensorPipelineResult out;
    out.impactEdge = sensor.update(nowMs);
    bool gateStartEdge = gateStartSensor.update(nowMs);
    bool gateEndEdge = gateEndSensor.update(nowMs);
    updateGateSpeedState(nowUs, gateStartEdge, gateEndEdge);
    out.gateSpeedReady = g_gateSpeed.ready;

    if (out.impactEdge) {
        Logger::info(String("[HIT] main pin=") + KY003_PIN +
                     " count=" + sensor.getHitCount());
    }
    if (gateStartEdge) {
        Logger::info(String("[HIT] gateStart pin=") + KY003_GATE_START_PIN);
    }
    if (gateEndEdge) {
        Logger::info(String("[HIT] gateEnd   pin=") + KY003_GATE_END_PIN);
    }

    static uint32_t lastDiagMs = 0;
    if (nowMs - lastDiagMs >= 2000u) {
        lastDiagMs = nowMs;
        Logger::info(String("[DIAG] pins main(") + KY003_PIN + ")=" +
                     digitalRead(KY003_PIN) + " gateA(" + KY003_GATE_START_PIN +
                     ")=" + digitalRead(KY003_GATE_START_PIN) + " gateB(" +
                     KY003_GATE_END_PIN + ")=" + digitalRead(KY003_GATE_END_PIN) +
                     " count=" + sensor.getHitCount());
    }

    impactSensor.update(nowMs);
    if (out.impactEdge) {
        impactSensor.captureImpact(nowMs);
    }
    return out;
}

static void processBleCommands(uint32_t nowMs) {
    bleHandler.processReconnect(nowMs);
    if (!bleHandler.hasDeferredCommand()) {
        return;
    }
    String cmd = bleHandler.takeDeferredCommand();
    processControlCommand(cmd, nowMs);
}

static void publishBleTelemetry(uint32_t nowMs, const SensorPipelineResult& sensorResult) {
    static bool s_wasConnected = false;
    const bool nowConnected = bleHandler.isConnected();
    if (!nowConnected) {
        s_wasConnected = false;
        g_streamTimeoutWarned = false;
        g_gateSpeed.ready = false;
        return;
    }
    if (!s_wasConnected) {
        // New client connected — re-arm the stream to the firmware default so
        // older Python builds that cannot send STREAM:ON/PING still get data.
        s_wasConnected = true;
        g_streamEnabled = (BLE_STREAM_DEFAULT_ENABLED != 0);
        g_lastStreamKeepaliveMs = nowMs;
        g_streamTimeoutWarned = false;
    }

    static uint32_t lastNotifyMs = 0;
    if ((nowMs - lastNotifyMs) >= BLE_FAST_NOTIFY_INTERVAL_MS && isStreamActive(nowMs)) {
        lastNotifyMs = nowMs;
        const uint16_t rateX10 = sensor.getRateX10(nowMs);
        const uint16_t instantRpmX10 = sensor.getInstantRpmX10(nowMs, g_rpmPulsesPerRev);
        bleHandler.pushTelemetry(
            sensor.getState(),
            sensor.getHitCount(),
            rateX10,
            instantRpmX10
        );
    }

    if (!isStreamActive(nowMs)) {
        return;
    }

    if (sensorResult.gateSpeedReady && g_gateSpeed.ready) {
        bleHandler.pushGateSpeed(g_gateSpeed.sampleId, g_gateSpeed.speedKmhX10, g_gateSpeed.transitUs);
        g_gateSpeed.ready = false;
    }

    if (sensorResult.impactEdge) {
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
}

static uint32_t sinceMs(uint32_t nowMs, uint32_t lastMs) {
    if (lastMs == 0) return 0xFFFFFFFFu;
    return nowMs - lastMs;
}

static void publishSensorHealth(uint32_t nowMs) {
    static uint32_t lastHealthMs = 0;
    if ((nowMs - lastHealthMs) < 1000u) return;
    if (!bleHandler.isConnected()) return;
    lastHealthMs = nowMs;

    bleHandler.pushHealth(
        sensor.getHitCount(),
        sinceMs(nowMs, sensor.getLastEdgeMs()),
        sensor.getState(),
        gateStartSensor.getHitCount(),
        sinceMs(nowMs, gateStartSensor.getLastEdgeMs()),
        gateStartSensor.getState(),
        gateEndSensor.getHitCount(),
        sinceMs(nowMs, gateEndSensor.getLastEdgeMs()),
        gateEndSensor.getState(),
        sinceMs(nowMs, impactSensor.getLastImpactMs()),
        impactSensor.getBaselineMagnitudeMg()
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

    if (CalibrationStore::loadRuntimeConfig(g_gateDistanceCm, g_rpmPulsesPerRev)) {
        Logger::info("Runtime gate/RPM config loaded from NVS");
    } else {
        Logger::info("Runtime gate/RPM defaults in use");
    }
    if (g_gateDistanceCm < 0.5f || g_gateDistanceCm > 100.0f) g_gateDistanceCm = KY003_GATE_DISTANCE_CM;
    if (g_rpmPulsesPerRev < 1 || g_rpmPulsesPerRev > 128) g_rpmPulsesPerRev = KY003_RPM_PULSES_PER_REV;

    if (CalibrationStore::loadImpactCalibration(g_impactCalibration)) {
        Logger::info("Impact calibration loaded from NVS");
    } else {
        Logger::info("Impact calibration defaults in use");
    }
    applyImpactCalibration(g_impactCalibration);
    sensor.begin();
    gateStartSensor.begin();
    gateEndSensor.begin();
    impactSensor.begin();
#if LED_RING_ENABLED
    ledHandler.begin();
#endif
    bleHandler.begin();
    bleHandler.startAdvertising();
    g_lastStreamKeepaliveMs = millis();

    Logger::info("BLE advertising started");
#if BLE_STREAM_DEFAULT_ENABLED
    Logger::info("Live stream default: ENABLED");
#else
    Logger::info("Live stream default: DISABLED");
#endif
}

void loop() {
    uint32_t now = millis();
    uint32_t nowUs = micros();
    SensorPipelineResult sensorResult = runSensorPipeline(now, nowUs);
    processBleCommands(now);
    publishBleTelemetry(now, sensorResult);
    publishSensorHealth(now);
    updateLedFeedback(now);
}
