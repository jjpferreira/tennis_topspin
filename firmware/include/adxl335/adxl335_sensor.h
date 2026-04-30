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
    // Resting gravity vector captured at the moment of impact (in mg). At
    // rest the magnitude should be ~1000 mg (1 g). We ship these alongside
    // the impact deltas so the host can derive racket orientation (e.g.
    // arm/swing tilt) without needing a second BLE characteristic.
    int16_t baselineXMg = 0;
    int16_t baselineYMg = 0;
    int16_t baselineZMg = 0;
    // Convenience: signed lateral racket tilt in degrees, derived from the
    // baseline gravity vector. Positive = racket leaning to one side,
    // negative = the other. Saturated to [-90, 90] so it can be packed
    // into a single int8_t without losing useful range.
    int8_t tiltDeg = 0;
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
    /**
     * Convert the live EWMA baseline (in raw 12-bit ADC counts, where 2048
     * is midrail / zero-g) into a signed gravity vector in mg, one axis
     * per output param. At rest the magnitude is ~1000 mg and the
     * direction encodes the racket's orientation -- which is what we use
     * to derive arm/racket tilt.
     */
    void getBaselineGravityMg(int16_t& xMg, int16_t& yMg, int16_t& zMg) const;
    /**
     * Lateral racket tilt in degrees, derived from the baseline gravity
     * vector. Positive => leaning toward +X axis, negative => toward -X.
     * Saturates to [-90, 90]. Returns 0 before a baseline is established.
     */
    int8_t getBaselineTiltDeg() const;
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
