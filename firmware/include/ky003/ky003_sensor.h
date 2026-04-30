#pragma once

#include <Arduino.h>
#include "../config.h"

class KY003Sensor {
public:
    explicit KY003Sensor(
        uint8_t pin = KY003_PIN,
        bool countOnFallingEdge = (KY003_COUNT_ON_FALLING_EDGE != 0),
        bool inputPullup = (KY003_INPUT_PULLUP != 0),
        uint16_t debounceMs = static_cast<uint16_t>(KY003_DEBOUNCE_MS),
        uint32_t rateWindowMs = static_cast<uint32_t>(KY003_RATE_WINDOW_MS)
    );

    void begin();
    bool update(uint32_t nowMs);
    void reset();

    // Returns true exactly ONCE per raw signal transition that *will*
    // count as an edge once it survives debounce. Use this to fire
    // time-critical, debounce-independent side-effects (eg. the
    // ADXL335 captureImpact burst) at the very instant the magnet
    // first crosses the sensor, instead of waiting `_debounceMs`
    // for the signal to stabilise. The hit *counter* still uses
    // update()'s debounced edge -- this probe is purely a "what
    // just changed in the raw signal" trigger. The flag latches
    // across the debounce window and is consumed on read.
    bool consumeRawEdge();

    uint8_t getState() const { return _stableState; }
    uint32_t getHitCount() const { return _hitCount; }
    uint32_t getLastEdgeMs() const { return _edgeSize > 0 ? _lastEdgeMs : 0; }
    bool hasObservedEdge() const { return _edgeSize > 0; }
    uint16_t getRateX10(uint32_t nowMs) const;
    // Instantaneous RPM*10 from the most recent inter-edge intervals.
    // Returns 0 if there is no recent activity within `freshnessMs`.
    uint16_t getInstantRpmX10(uint32_t nowMs, uint16_t pulsesPerRev,
                              uint32_t freshnessMs = 750u) const;

private:
    void pushEdgeTime(uint32_t nowMs);
    bool shouldCountEdge(uint8_t previous, uint8_t current) const;

    uint8_t _pin;
    bool _countOnFallingEdge;
    bool _inputPullup;
    uint16_t _debounceMs;
    uint32_t _rateWindowMs;

    uint8_t _stableState = 1;
    uint8_t _rawLast = 1;
    uint32_t _rawChangedAt = 0;
    uint32_t _hitCount = 0;
    // Latch set when the raw signal first transitions in the
    // direction we count (eg. falling for `_countOnFallingEdge`).
    // Cleared by `consumeRawEdge()`. Used to trigger the ADXL335
    // burst at the actual contact instant rather than ~8 ms later
    // when the debounced edge fires.
    bool _rawEdgePending = false;

    uint32_t _edgeTimes[KY003_EDGE_HISTORY_LEN] = {};
    size_t _edgeHead = 0;
    size_t _edgeSize = 0;
    uint32_t _lastEdgeMs = 0;
};
