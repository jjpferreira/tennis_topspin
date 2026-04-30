#pragma once

#include <Arduino.h>
#include <BLE2902.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <freertos/FreeRTOS.h>
#include <freertos/semphr.h>
#include "../config.h"
#include "../firmware_version.h"
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

    /**
     * Print a one-shot dump of the BLE GATT profile to Serial:
     *   - advertised device name
     *   - service UUID
     *   - bluetooth MAC address (BD_ADDR)
     *   - every registered characteristic UUID + tag
     * Use this to confirm at boot that the firmware really does expose all 9
     * characteristics (otherwise the macOS GATT cache is hiding something).
     */
    void logProfileToSerial();

    /**
     * Periodic compact restatement of the BLE profile on Serial. Prints once
     * every ~10 seconds to make it easy to confirm the running profile at any
     * point during a session.
     */
    void publishProfileHeartbeat(uint32_t nowMs);

    /** Number of GATT characteristics created on the tennis service. */
    uint8_t characteristicCount() const;

    void pushTelemetry(uint8_t state, uint32_t count, uint16_t rateX10, uint16_t rpmX10);
    void pushImpact(
        uint32_t hitCount,
        int16_t xMg,
        int16_t yMg,
        int16_t zMg,
        uint16_t magnitudeMg,
        uint8_t intensityPct,
        int8_t contactX,
        int8_t contactY,
        bool validImpact
    );
    void pushGateSpeed(
        uint32_t sampleId,
        uint16_t speedKmhX10,
        uint32_t transitUs
    );
    void pushHealth(
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
    );

    /** UTF-8 acknowledgement notify on the command characteristic (e.g. PONG after PING). */
    void notifyCommandAck(const char* utf8);

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
    BLECharacteristic* _rpmChar;
    BLECharacteristic* _impactChar;
    BLECharacteristic* _gateSpeedChar;
    BLECharacteristic* _healthChar;
    BLECharacteristic* _fwVersionChar;
    BLECharacteristic* _commandChar;

    SemaphoreHandle_t _cmdMutex;
    String _deferredCommand;
};
