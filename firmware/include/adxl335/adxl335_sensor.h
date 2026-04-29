#pragma once

#include <Arduino.h>

struct ImpactCalibration {
    float countsPerG = 0.0f;
    uint16_t impactMgAt100 = 0;
    uint16_t contactFullScaleMg = 0;
    uint16_t minValidImpactMg = 0;
};

struct ImpactSample {
    int16_t xMg = 0;
    int16_t yMg = 0;
    int16_t zMg = 0;
    uint16_t magnitudeMg = 0;
    uint8_t intensityPct = 0;
    int8_t contactX = 0;
    int8_t contactY = 0;
    bool valid = false;
    uint32_t capturedAtMs = 0;
};

class ADXL335Sensor {
public:
    void begin();
    void update(uint32_t nowMs);
    void captureImpact(uint32_t nowMs);
    ImpactSample getLastImpact() const { return _lastImpact; }
    uint32_t getLastImpactMs() const { return _lastImpact.capturedAtMs; }
    bool hasBaseline() const { return _baselineEstablished; }
    uint16_t getBaselineMagnitudeMg() const;
    void setCalibration(const ImpactCalibration& cfg);
    ImpactCalibration getCalibration() const { return _calibration; }
    static ImpactCalibration defaultCalibration();

private:
    void sampleAxes(int& xRaw, int& yRaw, int& zRaw) const;
    int16_t countsToMg(int deltaCounts) const;
    static int8_t toContactCoord(int16_t mg, int16_t fullScaleMg);

    float _baselineX = 0.0f;
    float _baselineY = 0.0f;
    float _baselineZ = 0.0f;
    bool _baselineEstablished = false;
    uint32_t _lastSampleMs = 0;
    ImpactSample _lastImpact;
    ImpactCalibration _calibration = defaultCalibration();
};
