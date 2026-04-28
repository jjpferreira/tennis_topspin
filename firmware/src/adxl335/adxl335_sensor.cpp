#include "../../include/adxl335/adxl335_sensor.h"

#include <cmath>

#include "../../include/config.h"

ImpactCalibration ADXL335Sensor::defaultCalibration() {
    ImpactCalibration cfg;
    cfg.countsPerG = ADXL335_COUNTS_PER_G;
    cfg.impactMgAt100 = ADXL335_IMPACT_MG_AT_100;
    cfg.contactFullScaleMg = ADXL335_CONTACT_FULL_SCALE_MG;
    cfg.minValidImpactMg = ADXL335_MIN_VALID_IMPACT_MG;
    return cfg;
}

void ADXL335Sensor::setCalibration(const ImpactCalibration& cfg) {
    ImpactCalibration next = cfg;
    if (next.countsPerG < 50.0f) next.countsPerG = ADXL335_COUNTS_PER_G;
    if (next.impactMgAt100 < 100) next.impactMgAt100 = ADXL335_IMPACT_MG_AT_100;
    if (next.contactFullScaleMg < 100) next.contactFullScaleMg = ADXL335_CONTACT_FULL_SCALE_MG;
    if (next.minValidImpactMg < 50) next.minValidImpactMg = ADXL335_MIN_VALID_IMPACT_MG;
    _calibration = next;
}

void ADXL335Sensor::begin() {
    analogReadResolution(12);
#if defined(ADC_11db)
    analogSetPinAttenuation(ADXL335_X_PIN, ADC_11db);
    analogSetPinAttenuation(ADXL335_Y_PIN, ADC_11db);
    analogSetPinAttenuation(ADXL335_Z_PIN, ADC_11db);
#endif
    pinMode(ADXL335_X_PIN, INPUT);
    pinMode(ADXL335_Y_PIN, INPUT);
    pinMode(ADXL335_Z_PIN, INPUT);

    float sx = 0.0f;
    float sy = 0.0f;
    float sz = 0.0f;
    for (uint8_t i = 0; i < ADXL335_BASELINE_SAMPLES; i++) {
        int xRaw = 0, yRaw = 0, zRaw = 0;
        sampleAxes(xRaw, yRaw, zRaw);
        sx += static_cast<float>(xRaw);
        sy += static_cast<float>(yRaw);
        sz += static_cast<float>(zRaw);
        delay(2);
        yield();
    }

    _baselineX = sx / static_cast<float>(ADXL335_BASELINE_SAMPLES);
    _baselineY = sy / static_cast<float>(ADXL335_BASELINE_SAMPLES);
    _baselineZ = sz / static_cast<float>(ADXL335_BASELINE_SAMPLES);
    _lastSampleMs = millis();
}

void ADXL335Sensor::update(uint32_t nowMs) {
    if ((nowMs - _lastSampleMs) < ADXL335_SAMPLE_INTERVAL_MS) {
        return;
    }
    _lastSampleMs = nowMs;

    int xRaw = 0, yRaw = 0, zRaw = 0;
    sampleAxes(xRaw, yRaw, zRaw);

    _baselineX = _baselineX * (1.0f - ADXL335_BASELINE_ALPHA) + static_cast<float>(xRaw) * ADXL335_BASELINE_ALPHA;
    _baselineY = _baselineY * (1.0f - ADXL335_BASELINE_ALPHA) + static_cast<float>(yRaw) * ADXL335_BASELINE_ALPHA;
    _baselineZ = _baselineZ * (1.0f - ADXL335_BASELINE_ALPHA) + static_cast<float>(zRaw) * ADXL335_BASELINE_ALPHA;
}

void ADXL335Sensor::captureImpact(uint32_t nowMs) {
    int bestDx = 0;
    int bestDy = 0;
    int bestDz = 0;
    float bestMagCounts = -1.0f;

    for (uint8_t i = 0; i < ADXL335_IMPACT_SAMPLES; i++) {
        int xRaw = 0, yRaw = 0, zRaw = 0;
        sampleAxes(xRaw, yRaw, zRaw);

        const int dx = xRaw - static_cast<int>(_baselineX);
        const int dy = yRaw - static_cast<int>(_baselineY);
        const int dz = zRaw - static_cast<int>(_baselineZ);
        const float mag = sqrtf(
            static_cast<float>(dx * dx) +
            static_cast<float>(dy * dy) +
            static_cast<float>(dz * dz)
        );

        if (mag > bestMagCounts) {
            bestMagCounts = mag;
            bestDx = dx;
            bestDy = dy;
            bestDz = dz;
        }
        delayMicroseconds(ADXL335_IMPACT_SAMPLE_SPACING_US);
    }

    const int16_t xMg = countsToMg(bestDx);
    const int16_t yMg = countsToMg(bestDy);
    const int16_t zMg = countsToMg(bestDz);
    const float magMg = sqrtf(
        static_cast<float>(xMg * xMg) +
        static_cast<float>(yMg * yMg) +
        static_cast<float>(zMg * zMg)
    );
    const uint16_t magMgClamped = static_cast<uint16_t>(constrain(static_cast<int>(magMg), 0, 65535));
    const bool validImpact = magMgClamped >= _calibration.minValidImpactMg;

    int intensity = 0;
    if (validImpact && _calibration.impactMgAt100 > 0) {
        intensity = static_cast<int>(
            (magMg * 100.0f) / static_cast<float>(_calibration.impactMgAt100)
        );
    }
    intensity = constrain(intensity, 0, 100);

    _lastImpact.xMg = validImpact ? xMg : 0;
    _lastImpact.yMg = validImpact ? yMg : 0;
    _lastImpact.zMg = validImpact ? zMg : 0;
    _lastImpact.magnitudeMg = magMgClamped;
    _lastImpact.intensityPct = static_cast<uint8_t>(intensity);
    _lastImpact.contactX = validImpact
        ? toContactCoord(xMg, static_cast<int16_t>(_calibration.contactFullScaleMg))
        : 0;
    _lastImpact.contactY = validImpact
        ? toContactCoord(yMg, static_cast<int16_t>(_calibration.contactFullScaleMg))
        : 0;
    _lastImpact.valid = validImpact;
    _lastImpact.capturedAtMs = nowMs;
}

void ADXL335Sensor::sampleAxes(int& xRaw, int& yRaw, int& zRaw) const {
    xRaw = analogRead(ADXL335_X_PIN);
    yRaw = analogRead(ADXL335_Y_PIN);
    zRaw = analogRead(ADXL335_Z_PIN);
}

int16_t ADXL335Sensor::countsToMg(int deltaCounts) const {
    const float mg = (static_cast<float>(deltaCounts) * 1000.0f) / _calibration.countsPerG;
    if (mg > 32767.0f) return 32767;
    if (mg < -32768.0f) return -32768;
    return static_cast<int16_t>(mg);
}

int8_t ADXL335Sensor::toContactCoord(int16_t mg, int16_t fullScaleMg) {
    if (fullScaleMg <= 0) return 0;
    int v = static_cast<int>((static_cast<float>(mg) * 100.0f) / static_cast<float>(fullScaleMg));
    v = constrain(v, -100, 100);
    return static_cast<int8_t>(v);
}
