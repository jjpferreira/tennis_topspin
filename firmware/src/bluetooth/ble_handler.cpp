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
        digitalWrite(STATUS_LED_PIN, HIGH);
    }

    void onDisconnect(BLEServer* pServer) override {
        (void)pServer;
        BLEHandler::getInstance()._connected = false;
        BLEHandler::getInstance()._reconnectPending = true;
        digitalWrite(STATUS_LED_PIN, LOW);
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
      _commandChar(nullptr),
      _cmdMutex(xSemaphoreCreateMutex()),
      _deferredCommand("") {}

void BLEHandler::begin() {
    BLEDevice::init(APP_NAME);
    _server = BLEDevice::createServer();
    _server->setCallbacks(new TennisServerCallbacks());

    _service = _server->createService(TENNIS_SERVICE_UUID);
    setupCharacteristics();
    _service->start();
    setupAdvertising();
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

    _commandChar = _service->createCharacteristic(
        TENNIS_COMMAND_UUID,
        BLECharacteristic::PROPERTY_WRITE | BLECharacteristic::PROPERTY_WRITE_NR
    );
    _commandChar->setCallbacks(new TennisCommandCallbacks());
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

void BLEHandler::pushTelemetry(uint8_t state, uint32_t count, uint16_t rateX10) {
    if (!_connected) return;

    _stateChar->setValue(&state, sizeof(state));
    _stateChar->notify();

    _countChar->setValue(reinterpret_cast<uint8_t*>(&count), sizeof(count));
    _countChar->notify();

    _rateChar->setValue(reinterpret_cast<uint8_t*>(&rateX10), sizeof(rateX10));
    _rateChar->notify();
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
