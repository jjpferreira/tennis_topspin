#include "../../include/bluetooth/ble_handler.h"

class TennisCommandCallbacks : public BLECharacteristicCallbacks {
public:
    void onWrite(BLECharacteristic* c) override {
        String cmd = c->getValue();
        cmd.trim();
        if (cmd.length() > 0 && cmd.length() < 64) {
            BLEHandler::getInstance().onDataReceived(cmd);
        }
    }
};

class TennisServerCallbacks : public BLEServerCallbacks {
public:
    void onConnect(BLEServer* pServer) override {
        (void)pServer;
        BLEHandler::getInstance()._connected = true;
        BLEHandler::getInstance()._reconnectPending = false;
        digitalWrite(STATUS_LED_PIN, HIGH);
        Serial.println(F("[BLE] client connected"));
        BLEHandler::getInstance().logProfileToSerial();
    }

    void onDisconnect(BLEServer* pServer) override {
        (void)pServer;
        BLEHandler::getInstance()._connected = false;
        BLEHandler::getInstance()._reconnectPending = true;
        digitalWrite(STATUS_LED_PIN, LOW);
        Serial.println(F("[BLE] client disconnected — re-advertising"));
    }
};

BLEHandler::BLEHandler()
    : _connected(false),
      _reconnectPending(false),
      _lastReconnectMs(0),
      _server(nullptr),
      _service(nullptr),
      _advertising(nullptr),
      _stateChar(nullptr),
      _countChar(nullptr),
      _rateChar(nullptr),
      _rpmChar(nullptr),
      _impactChar(nullptr),
      _gateSpeedChar(nullptr),
      _healthChar(nullptr),
      _fwVersionChar(nullptr),
      _commandChar(nullptr),
      _cmdMutex(xSemaphoreCreateMutex()),
      _deferredCommand("") {}

void BLEHandler::begin() {
    BLEDevice::init(APP_NAME);
    _server = BLEDevice::createServer();
    _server->setCallbacks(new TennisServerCallbacks());

    // CRITICAL: BLEServer::createService(uuid) defaults to numHandles=15, which
    // is exactly enough for a service + 5 notify characteristics (each notify
    // char consumes 3 handles: declaration + value + CCCD). Beyond that the
    // ESP32 Arduino BLE library SILENTLY DROPS characteristics — the very bug
    // that produced the 5-char fingerprint (state/count/rate/rpm/impact) on
    // the dashboard. We expose 9 chars (8 with notify CCCD, 1 read-only), so
    // we need a comfortable headroom (~32 handles) to avoid running into the
    // limit again as the profile grows.
    _service = _server->createService(BLEUUID(TENNIS_SERVICE_UUID), 32, 0);
    setupCharacteristics();
    _service->start();
    setupAdvertising();
    // Always print the full profile right after registration so the operator
    // can prove on serial that all 9 characteristics were created. This is the
    // ground truth — the macOS GATT cache may still serve a stale view, but
    // the firmware itself broadcasts the full set every boot.
    logProfileToSerial();
}

void BLEHandler::setupCharacteristics() {
    _stateChar = _service->createCharacteristic(
        TENNIS_STATE_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY
    );
    _stateChar->addDescriptor(new BLE2902());

    _countChar = _service->createCharacteristic(
        TENNIS_COUNT_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY
    );
    _countChar->addDescriptor(new BLE2902());

    _rateChar = _service->createCharacteristic(
        TENNIS_RATE_X10_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY
    );
    _rateChar->addDescriptor(new BLE2902());

    _rpmChar = _service->createCharacteristic(
        TENNIS_RPM_X10_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY
    );
    _rpmChar->addDescriptor(new BLE2902());

    _impactChar = _service->createCharacteristic(
        TENNIS_IMPACT_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY
    );
    _impactChar->addDescriptor(new BLE2902());

    _gateSpeedChar = _service->createCharacteristic(
        TENNIS_GATE_SPEED_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY
    );
    _gateSpeedChar->addDescriptor(new BLE2902());

    _healthChar = _service->createCharacteristic(
        TENNIS_HEALTH_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_NOTIFY
    );
    _healthChar->addDescriptor(new BLE2902());

    // Read-only firmware build identifier. The value is set ONCE at boot from
    // FIRMWARE_INFO_STRING (semver + __DATE__ + __TIME__) so each rebuild
    // produces a new payload — central can confirm flash freshness instantly.
    _fwVersionChar = _service->createCharacteristic(
        TENNIS_FW_VERSION_UUID,
        BLECharacteristic::PROPERTY_READ
    );
    _fwVersionChar->setValue(FIRMWARE_INFO_STRING);

    _commandChar = _service->createCharacteristic(
        TENNIS_COMMAND_UUID,
        BLECharacteristic::PROPERTY_READ | BLECharacteristic::PROPERTY_WRITE |
            BLECharacteristic::PROPERTY_WRITE_NR | BLECharacteristic::PROPERTY_NOTIFY
    );
    _commandChar->addDescriptor(new BLE2902());
    _commandChar->setCallbacks(new TennisCommandCallbacks());
}

void BLEHandler::notifyCommandAck(const char* utf8) {
    if (!_connected || !_commandChar || !utf8) {
        return;
    }
    String s(utf8);
    _commandChar->setValue(s);
    _commandChar->notify();
}

void BLEHandler::setFirmwareInfoString(const char* utf8) {
    if (!_fwVersionChar || !utf8) {
        return;
    }
    _fwVersionChar->setValue(utf8);
    Logger::info(String("[GATT] fw-version override: ") + utf8);
}

void BLEHandler::setupAdvertising() {
    _advertising = BLEDevice::getAdvertising();
    _advertising->addServiceUUID(TENNIS_SERVICE_UUID);
    _advertising->setScanResponse(true);
}

void BLEHandler::startAdvertising() {
    BLEDevice::startAdvertising();
}

void BLEHandler::processReconnect(uint32_t nowMs) {
    if (!_reconnectPending) return;
    if ((nowMs - _lastReconnectMs) < BLE_RECONNECT_COOLDOWN_MS) return;

    _lastReconnectMs = nowMs;
    _reconnectPending = false;
    BLEDevice::startAdvertising();
}

void BLEHandler::pushTelemetry(uint8_t state, uint32_t count, uint16_t rateX10, uint16_t rpmX10) {
    if (!_connected) return;

    _stateChar->setValue(&state, sizeof(state));
    _stateChar->notify();

    _countChar->setValue(reinterpret_cast<uint8_t*>(&count), sizeof(count));
    _countChar->notify();

    _rateChar->setValue(reinterpret_cast<uint8_t*>(&rateX10), sizeof(rateX10));
    _rateChar->notify();

    _rpmChar->setValue(reinterpret_cast<uint8_t*>(&rpmX10), sizeof(rpmX10));
    _rpmChar->notify();
}

void BLEHandler::pushImpact(
    uint32_t hitCount,
    int16_t xMg,
    int16_t yMg,
    int16_t zMg,
    uint16_t magnitudeMg,
    uint8_t intensityPct,
    int8_t contactX,
    int8_t contactY,
    bool validImpact,
    int16_t baselineXMg,
    int16_t baselineYMg,
    int16_t baselineZMg,
    int8_t tiltDeg
) {
    if (!_connected || !_impactChar) return;

    // Wire format (little-endian, packed). The first 16 bytes are the
    // legacy contract -- the host must remain backward-compatible because
    // older firmware builds in the field still ship that form. New
    // baseline gravity + derived tilt fields are appended at the end so
    // an older host that only reads 16 bytes keeps working unchanged.
    struct __attribute__((packed)) ImpactPayload {
        uint32_t hitCount;
        int16_t xMg;
        int16_t yMg;
        int16_t zMg;
        uint16_t magnitudeMg;
        uint8_t intensityPct;
        int8_t contactX;
        int8_t contactY;
        uint8_t flags;
        int16_t baselineXMg;
        int16_t baselineYMg;
        int16_t baselineZMg;
        int8_t tiltDeg;
    } payload = {
        hitCount,
        xMg,
        yMg,
        zMg,
        magnitudeMg,
        intensityPct,
        contactX,
        contactY,
        static_cast<uint8_t>(validImpact ? 0x01 : 0x00),
        baselineXMg,
        baselineYMg,
        baselineZMg,
        tiltDeg
    };

    _impactChar->setValue(reinterpret_cast<uint8_t*>(&payload), sizeof(payload));
    _impactChar->notify();
}

void BLEHandler::pushGateSpeed(
    uint32_t sampleId,
    uint16_t speedKmhX10,
    uint32_t transitUs
) {
    if (!_connected || !_gateSpeedChar) return;

    struct __attribute__((packed)) GateSpeedPayload {
        uint32_t sampleId;
        uint16_t speedKmhX10;
        uint32_t transitUs;
    } payload = {
        sampleId,
        speedKmhX10,
        transitUs
    };

    _gateSpeedChar->setValue(reinterpret_cast<uint8_t*>(&payload), sizeof(payload));
    _gateSpeedChar->notify();
}

void BLEHandler::pushHealth(
    uint32_t mainHits,
    uint32_t mainSinceMs,
    uint8_t mainState,
    uint32_t gateAHits,
    uint32_t gateASinceMs,
    uint8_t gateAState,
    uint32_t gateBHits,
    uint32_t gateBSinceMs,
    uint8_t gateBState,
    uint32_t impactSinceMs,
    uint16_t impactBaselineMg
) {
    if (!_connected || !_healthChar) return;

    struct __attribute__((packed)) HealthPayload {
        uint32_t mainHits;
        uint32_t mainSinceMs;
        uint8_t  mainState;
        uint32_t gateAHits;
        uint32_t gateASinceMs;
        uint8_t  gateAState;
        uint32_t gateBHits;
        uint32_t gateBSinceMs;
        uint8_t  gateBState;
        uint32_t impactSinceMs;
        uint16_t impactBaselineMg;
    } payload = {
        mainHits,
        mainSinceMs,
        mainState,
        gateAHits,
        gateASinceMs,
        gateAState,
        gateBHits,
        gateBSinceMs,
        gateBState,
        impactSinceMs,
        impactBaselineMg
    };

    _healthChar->setValue(reinterpret_cast<uint8_t*>(&payload), sizeof(payload));
    _healthChar->notify();
}

void BLEHandler::onDataReceived(const String& command) {
    // Keep BLE callback path fast by deferring command execution to loop().
    setDeferredCommand(command);
}

void BLEHandler::setDeferredCommand(const String& cmd) {
    if (!_cmdMutex) return;
    xSemaphoreTake(_cmdMutex, portMAX_DELAY);
    _deferredCommand = cmd;
    xSemaphoreGive(_cmdMutex);
}

bool BLEHandler::hasDeferredCommand() const {
    if (!_cmdMutex) return false;
    xSemaphoreTake(_cmdMutex, portMAX_DELAY);
    bool has = _deferredCommand.length() > 0;
    xSemaphoreGive(_cmdMutex);
    return has;
}

String BLEHandler::takeDeferredCommand() {
    if (!_cmdMutex) return "";
    xSemaphoreTake(_cmdMutex, portMAX_DELAY);
    String cmd = _deferredCommand;
    _deferredCommand = "";
    xSemaphoreGive(_cmdMutex);
    return cmd;
}

uint8_t BLEHandler::characteristicCount() const {
    uint8_t n = 0;
    if (_stateChar)     n++;
    if (_countChar)     n++;
    if (_rateChar)      n++;
    if (_rpmChar)       n++;
    if (_impactChar)    n++;
    if (_gateSpeedChar) n++;
    if (_healthChar)    n++;
    if (_fwVersionChar) n++;
    if (_commandChar)   n++;
    return n;
}

static void logChar(const char* tag, BLECharacteristic* ch) {
    Serial.print(F("[GATT]   "));
    if (!ch) {
        Serial.print(F("MISSING "));
        Serial.println(tag);
        return;
    }
    Serial.print(ch->getUUID().toString().c_str());
    Serial.print(F(" ("));
    Serial.print(tag);
    Serial.println(F(")"));
}

void BLEHandler::logProfileToSerial() {
    Serial.print(F("[GATT] device_name="));
    Serial.println(APP_NAME);
    Serial.print(F("[GATT] mac="));
    Serial.println(BLEDevice::getAddress().toString().c_str());
    Serial.print(F("[GATT] service_uuid="));
    Serial.println(TENNIS_SERVICE_UUID);
    Serial.print(F("[GATT] characteristic_count="));
    Serial.println(characteristicCount());
    logChar("state",      _stateChar);
    logChar("count",      _countChar);
    logChar("rate",       _rateChar);
    logChar("rpm",        _rpmChar);
    logChar("impact",     _impactChar);
    logChar("gate-speed", _gateSpeedChar);
    logChar("health",     _healthChar);
    logChar("fw-version", _fwVersionChar);
    logChar("command",    _commandChar);
}

void BLEHandler::publishProfileHeartbeat(uint32_t nowMs) {
    static uint32_t lastBeatMs = 0;
    if (lastBeatMs != 0 && (nowMs - lastBeatMs) < 10000u) return;
    lastBeatMs = nowMs == 0 ? 1 : nowMs;
    Serial.print(F("[GATT-HB] svc="));
    Serial.print(TENNIS_SERVICE_UUID);
    Serial.print(F(" name="));
    Serial.print(APP_NAME);
    Serial.print(F(" chars="));
    Serial.print(characteristicCount());
    Serial.print(F(" connected="));
    Serial.println(_connected ? F("yes") : F("no"));
}
