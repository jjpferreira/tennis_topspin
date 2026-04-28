#pragma once

#include <Arduino.h>
#include "../config.h"

class KY003Sensor {
public:
    void begin();
    bool update(uint32_t nowMs);
    void reset();

    uint8_t getState() const { return _stableState; }
    uint32_t getHitCount() const { return _hitCount; }
    uint16_t getRateX10(uint32_t nowMs) const;

private:
    void pushEdgeTime(uint32_t nowMs);
    bool shouldCountEdge(uint8_t previous, uint8_t current) const;

    uint8_t _stableState = 1;
    uint8_t _rawLast = 1;
    uint32_t _rawChangedAt = 0;
    uint32_t _hitCount = 0;

    uint32_t _edgeTimes[KY003_EDGE_HISTORY_LEN] = {};
    size_t _edgeHead = 0;
    size_t _edgeSize = 0;
};
