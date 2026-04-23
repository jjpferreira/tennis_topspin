#pragma once

#include <Adafruit_NeoPixel.h>
#include "../config.h"
#include "../logger.h"

/**
 * WS2812 ring — behaviour and API aligned with GhostFinder
 * `hardware/firmware/EMFDetector-LiLyGo` LEDHandler (tiers, direction shading,
 * OTA ring, calibration sequences, blocking demo effects).
 *
 * Tier thresholds use `LED_LEVEL_T*` in config (e.g. hits/s for KY-003); for a
 * magnetometer project pass µT the same way as EMF `updateLevel`.
 */
class LEDHandler {
public:
    static LEDHandler& getInstance() {
        static LEDHandler instance;
        return instance;
    }

    void begin();
    void updateLevel(float signalValue);
    /**
     * Optional 3-vector + scalar for direction wedge (same math as EMF app).
     * Units are yours; shading uses relative geometry vs magnitudeUt.
     */
    void updateFieldDirection(float x, float y, float z, float magnitudeUt);
    void update();
    bool isInitialized() { return initialized; }

    void setOtaVisual(uint8_t phase, uint8_t progressPct = 0);
    void clearOtaVisual();

    void showAutoCalibrationReady();
    void showAutoCalibrationCountdown();
    void showAutoCalibrationCountdownTick();
    void showAutoCalibrationInProgress();
    void showAutoCalibrationActivity(uint8_t progressPct = 0);
    void showAutoCalibrationSuccess();
    void showAutoCalibrationFailure();
    void showManualCalibrationReady();
    void showManualCalibrationCountdown();
    void showManualCalibrationInProgress();
    void showManualCalibrationAlmostDone();
    void showNormalOperation();

    /** Tier boundaries for levels 1–5; idle (level 0) stays at 0. */
    void setRingThresholdsUt(float t1, float t2, float t3, float t4, float t5);

    /** Same as setRingThresholdsUt — alias for non-EMF sketches. */
    void setLevelThresholds(float t1, float t2, float t3, float t4, float t5) {
        setRingThresholdsUt(t1, t2, t3, t4, t5);
    }

    /** ~2.2 s violet pulse; skipped if OTA visual active or LEDs not initialised. */
    void showThresholdsSavedAck();

private:
    LEDHandler();

    struct RingLevel {
        const char* name;
        int r, g, b;
        float intensity;
        float threshold;
    };

    static const int NUM_LEVELS = 6;
    RingLevel ringLevels[NUM_LEVELS] = {
        {"Idle", 0, 80, 120, 0.3f, 0.0f},
        {"Level 1", 0, 100, 100, 0.5f, LED_LEVEL_T1},
        {"Level 2", 80, 0, 120, 0.6f, LED_LEVEL_T2},
        {"Level 3", 120, 100, 0, 0.7f, LED_LEVEL_T3},
        {"Level 4", 180, 60, 0, 0.8f, LED_LEVEL_T4},
        {"Level 5", 255, 0, 0, 1.0f, LED_LEVEL_T5},
    };

    void sweepEffect(int level);
    void handleLevel5();

    void flashRing(int r, int g, int b, int times);
    void chaseEffect(int r, int g, int b, int loops);
    void progressFill(int r, int g, int b);
    void figureEightFill(int r, int g, int b);
    void pulseEffect(int r, int g, int b);
    void breathingEffect(int r, int g, int b);
    void setColor(int r, int g, int b);
    void setLED(int led, int r, int g, int b);

    void shadeRGBForDirection(int ledIndex, int& r, int& g, int& b);
    void maybeApplyDirectionShade(int ledIndex, int& r, int& g, int& b, bool isIdleBreathing);
    static float angularDiffDeg(float a, float b);

    void breathingPattern(int r, int g, int b, unsigned long currentTime);
    void sweepPattern(int r, int g, int b, unsigned long currentTime, int speed, int level = 1);
    void flashPattern(int r, int g, int b, unsigned long currentTime);
    void otaPattern(unsigned long currentTime);
    void autoCalibrationPattern(unsigned long currentTime, uint8_t progressPct);
    void renderThresholdsSavedAck(unsigned long currentTime);

    Adafruit_NeoPixel pixels;
    float dirX = 0.f, dirY = 0.f, dirZ = 0.f;
    float dirMagUt = 0.f;
    bool dirValid = false;
    int currentLevel;
    volatile bool otaVisualActive = false;
    volatile uint8_t otaPhase = 0;
    volatile uint8_t otaProgressPct = 0;
    volatile unsigned long otaPhaseSince = 0;
    unsigned long levelStartTime;
    bool initialized = false;

    bool threshSaveAckActive = false;
    unsigned long threshSaveAckStartMs = 0;
};
