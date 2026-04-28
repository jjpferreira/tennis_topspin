#pragma once

#include <Arduino.h>

struct ImpactSample {
    int16_t xMg = 0;
    int16_t yMg = 0;
    int16_t zMg = 0;
    uint8_t intensityPct = 0;
    int8_t contactX = 0;
    int8_t contactY = 0;
    uint32_t capturedAtMs = 0;
};

class ADXL335Sensor {
public:
    void begin();
    void update(uint32_t nowMs);
    void captureImpact(uint32_t nowMs);
    ImpactSample getLastImpact() const { return _lastImpact; }

private:
    void sampleAxes(int& xRaw, int& yRaw, int& zRaw) const;
    static int16_t countsToMg(int deltaCounts);
    static int8_t toContactCoord(int16_t mg, int16_t fullScaleMg);

    float _baselineX = 0.0f;
    float _baselineY = 0.0f;
    float _baselineZ = 0.0f;
    uint32_t _lastSampleMs = 0;
    ImpactSample _lastImpact;
};
