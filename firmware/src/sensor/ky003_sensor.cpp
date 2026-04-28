#include "../../include/sensor/ky003_sensor.h"

void KY003Sensor::begin() {
#if KY003_INPUT_PULLUP
    pinMode(KY003_PIN, INPUT_PULLUP);
#else
    pinMode(KY003_PIN, INPUT);
#endif
    _stableState = static_cast<uint8_t>(digitalRead(KY003_PIN));
    _rawLast = _stableState;
    _rawChangedAt = millis();
}

bool KY003Sensor::update(uint32_t nowMs) {
    uint8_t raw = static_cast<uint8_t>(digitalRead(KY003_PIN));
    if (raw != _rawLast) {
        _rawLast = raw;
        _rawChangedAt = nowMs;
        return false;
    }

    if (raw != _stableState && (nowMs - _rawChangedAt) >= KY003_DEBOUNCE_MS) {
        uint8_t prev = _stableState;
        _stableState = raw;
        if (shouldCountEdge(prev, _stableState)) {
            _hitCount++;
            pushEdgeTime(nowMs);
            return true;
        }
    }
    return false;
}

void KY003Sensor::reset() {
    _hitCount = 0;
    _edgeHead = 0;
    _edgeSize = 0;
}

uint16_t KY003Sensor::getRateX10(uint32_t nowMs) const {
    if (_edgeSize == 0) return 0;

    uint32_t cutoff = nowMs - KY003_RATE_WINDOW_MS;
    size_t inWindow = 0;
    for (size_t i = 0; i < _edgeSize; i++) {
        size_t idx = (_edgeHead + KY003_EDGE_HISTORY_LEN - 1 - i) % KY003_EDGE_HISTORY_LEN;
        uint32_t t = _edgeTimes[idx];
        if (t >= cutoff) {
            inWindow++;
        } else {
            break;
        }
    }

    float rateX10 = (10000.0f * static_cast<float>(inWindow)) / static_cast<float>(KY003_RATE_WINDOW_MS);
    if (rateX10 < 0.0f) rateX10 = 0.0f;
    if (rateX10 > 65535.0f) rateX10 = 65535.0f;
    return static_cast<uint16_t>(rateX10);
}

void KY003Sensor::pushEdgeTime(uint32_t nowMs) {
    _edgeTimes[_edgeHead] = nowMs;
    _edgeHead = (_edgeHead + 1) % KY003_EDGE_HISTORY_LEN;
    if (_edgeSize < KY003_EDGE_HISTORY_LEN) {
        _edgeSize++;
    }
}

bool KY003Sensor::shouldCountEdge(uint8_t previous, uint8_t current) const {
#if KY003_COUNT_ON_FALLING_EDGE
    return previous == 1 && current == 0;
#else
    return previous == 0 && current == 1;
#endif
}
