#pragma once

#include <Arduino.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "../config.h"
#include "../logger.h"
#include "./ble_constants.h"

class TennisServerCallbacks;
class TennisCommandCallbacks;

class BLEHandler {
    friend class TennisServerCallbacks;
    friend class TennisCommandCallbacks;

public:
    static BLEHandler& getInstance() {
        static BLEHandler instance;
        return instance;
    }

    void begin();
    void startAdvertising();
    void processReconnect(uint32_t nowMs);

    bool isConnected() const { return _connected; }

    void pushTelemetry(uint8_t state, uint32_t count, uint16_t rateX10);

    void onDataReceived(const String& command);
    bool hasDeferredCommand() const;
    String takeDeferredCommand();

private:
    BLEHandler();
    BLEHandler(const BLEHandler&) = delete;
    BLEHandler& operator=(const BLEHandler&) = delete;

    void setupCharacteristics();
    void setupAdvertising();
    void setDeferredCommand(const String& cmd);

    volatile bool _connected;
    volatile bool _reconnectPending;
    uint32_t _lastReconnectMs;

    BLEServer* _server;
    BLEService* _service;
    BLEAdvertising* _advertising;

    BLECharacteristic* _stateChar;
    BLECharacteristic* _countChar;
    BLECharacteristic* _rateChar;
    BLECharacteristic* _commandChar;

    SemaphoreHandle_t _cmdMutex;
    String _deferredCommand;
};
