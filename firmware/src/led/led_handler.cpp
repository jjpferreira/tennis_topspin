#include "../../include/led/led_handler.h"

#include <cmath>

#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

LEDHandler::LEDHandler()
    : pixels(LED_COUNT, LED_PIN, NEO_GRB + NEO_KHZ800),
      currentLevel(0),
      levelStartTime(0) {}

void LEDHandler::setRingThresholdsUt(float t1, float t2, float t3, float t4, float t5) {
    ringLevels[1].threshold = t1;
    ringLevels[2].threshold = t2;
    ringLevels[3].threshold = t3;
    ringLevels[4].threshold = t4;
    ringLevels[5].threshold = t5;
}

void LEDHandler::showThresholdsSavedAck() {
    if (!initialized) return;
    if (otaVisualActive) return;
    threshSaveAckActive = true;
    threshSaveAckStartMs = millis();
    Logger::info("LED: settings saved — violet ack queued (~2.2 s)");
}

void LEDHandler::renderThresholdsSavedAck(unsigned long currentTime) {
    const unsigned long dt = currentTime - threshSaveAckStartMs;
    const unsigned long kDurationMs = 2200;
    if (dt >= kDurationMs) {
        threshSaveAckActive = false;
        return;
    }
    const int pr = 110, pg = 25, pb = 205;
    const unsigned phase = (dt / 200) % 4;
    const float v = (phase == 1u || phase == 3u) ? 0.22f : 1.0f;
    const int r = (int)(pr * v);
    const int g = (int)(pg * v);
    const int b = (int)(pb * v);
    for (int i = 0; i < LED_COUNT; i++) {
        pixels.setPixelColor(i, pixels.Color(r, g, b));
    }
}

void LEDHandler::begin() {
    pixels.begin();
    pixels.clear();
    pixels.show();
    initialized = true;
    Logger::info("LED Handler initialized");

    unsigned long startTime = millis();
    while (millis() - startTime < 300) {
        bool on = ((millis() - startTime) % 200) < 100;
        for (int i = 0; i < LED_COUNT; i++) {
            pixels.setPixelColor(i, on ? pixels.Color(0, 50, 50) : pixels.Color(0, 0, 0));
        }
        pixels.show();
        delay(10);
        yield();
    }
    pixels.clear();
    pixels.show();
}

void LEDHandler::updateFieldDirection(float x, float y, float z, float magnitudeUt) {
    dirX = x;
    dirY = y;
    dirZ = z;
    dirMagUt = magnitudeUt;
    dirValid = true;
}

float LEDHandler::angularDiffDeg(float a, float b) {
    float d = a - b;
    while (d > 180.0f) d -= 360.0f;
    while (d < -180.0f) d += 360.0f;
    return fabsf(d);
}

void LEDHandler::shadeRGBForDirection(int ledIndex, int& r, int& g, int& b) {
    if (!dirValid || ledIndex < 0 || ledIndex >= LED_COUNT) return;

    const float x = dirX, y = dirY, z = dirZ;
    const float mag_vec = sqrtf(x * x + y * y + z * z);
    if (mag_vec < 0.05f) return;

    const float h_ut = sqrtf(x * x + y * y);
    const float mag_ref = fmaxf(fabsf(dirMagUt), 1e-9f);
    float h_frac = h_ut / mag_ref;
    if (h_frac > 1.0f) h_frac = 1.0f;

    const float DIM_OUTSIDE = 0.22f;
    const float DIM_Z_HALF = 0.20f;

    if (h_ut >= 0.08f && h_frac >= 0.12f) {
        const float bearingDeg = atan2f(y, x) * (180.0f / (float)M_PI);
        const float sharpness = fminf(mag_vec / 5.0f, 1.0f);
        float spanDeg = (28.0f + 52.0f * h_frac) * (1.0f - 0.45f * sharpness);
        if (spanDeg < 18.0f) spanDeg = 18.0f;
        const float halfSpan = spanDeg * 0.5f;
        const float step = 360.0f / (float)LED_COUNT;
        const float ledCenterDeg =
            LED_RING_LED0_CENTER_DEG
            + (float)LED_RING_INDEX_ANGLE_SIGN * ((float)ledIndex + 0.5f) * step;
        if (angularDiffDeg(bearingDeg, ledCenterDeg) > halfSpan) {
            r = (int)(r * DIM_OUTSIDE);
            g = (int)(g * DIM_OUTSIDE);
            b = (int)(b * DIM_OUTSIDE);
        }
    } else if (h_ut < 0.05f) {
        const int halfN = LED_COUNT / 2;
        const int halfBin = ledIndex / halfN;
        const bool upperBright = (z >= 0.0f);
        const bool thisBright =
            (upperBright && halfBin == 0) || (!upperBright && halfBin == 1);
        if (!thisBright) {
            r = (int)(r * DIM_Z_HALF);
            g = (int)(g * DIM_Z_HALF);
            b = (int)(b * DIM_Z_HALF);
        }
    }

    r = constrain(r, 0, 255);
    g = constrain(g, 0, 255);
    b = constrain(b, 0, 255);
}

void LEDHandler::maybeApplyDirectionShade(int ledIndex, int& r, int& g, int& b, bool isIdleBreathing) {
#if LED_DIRECTION_MODE == 0
    (void)isIdleBreathing;
    return;
#elif LED_DIRECTION_MODE == 1
    if (!isIdleBreathing) return;
#endif
    shadeRGBForDirection(ledIndex, r, g, b);
}

void LEDHandler::updateLevel(float signalValue) {
    if (!initialized) return;
    if (otaVisualActive) return;

    int newLevel = 0;
    if (signalValue >= ringLevels[5].threshold)
        newLevel = 5;
    else if (signalValue >= ringLevels[4].threshold)
        newLevel = 4;
    else if (signalValue >= ringLevels[3].threshold)
        newLevel = 3;
    else if (signalValue >= ringLevels[2].threshold)
        newLevel = 2;
    else if (signalValue >= ringLevels[1].threshold)
        newLevel = 1;
    else
        newLevel = 0;

    if (newLevel != currentLevel) {
        currentLevel = newLevel;
        levelStartTime = millis();
        Serial.printf("[LED] Level -> %d (%s)\n", currentLevel, ringLevels[currentLevel].name);
    }
}

void LEDHandler::setOtaVisual(uint8_t phase, uint8_t progressPct) {
    if (!initialized) return;
    if (!otaVisualActive || otaPhase != phase) {
        otaPhaseSince = millis();
    }
    otaVisualActive = true;
    otaPhase = phase;
    otaProgressPct = progressPct;
}

void LEDHandler::clearOtaVisual() {
    otaVisualActive = false;
    otaPhase = 0;
    otaProgressPct = 0;
}

void LEDHandler::update() {
    if (!initialized) return;

#if LED_RING_CALIBRATION_MODE
    pixels.clear();
    pixels.setPixelColor(0, pixels.Color(255, 255, 255));
    pixels.show();
    return;
#endif

    unsigned long currentTime = millis();
    if (otaVisualActive) {
        otaPattern(currentTime);
        pixels.show();
        return;
    }
    if (threshSaveAckActive) {
        renderThresholdsSavedAck(currentTime);
        pixels.show();
        return;
    }

    switch (currentLevel) {
        case 0:
            breathingPattern(0, 150, 150, currentTime);
            break;
        case 1:
            sweepPattern(ringLevels[1].r, ringLevels[1].g, ringLevels[1].b, currentTime, 150, 1);
            break;
        case 2:
            sweepPattern(ringLevels[2].r, ringLevels[2].g, ringLevels[2].b, currentTime, 120, 2);
            break;
        case 3:
            sweepPattern(ringLevels[3].r, ringLevels[3].g, ringLevels[3].b, currentTime, 90, 3);
            break;
        case 4:
            sweepPattern(ringLevels[4].r, ringLevels[4].g, ringLevels[4].b, currentTime, 60, 4);
            break;
        case 5:
            flashPattern(255, 0, 0, currentTime);
            break;
        default:
            breathingPattern(0, 150, 150, currentTime);
            break;
    }
    pixels.show();
}

void LEDHandler::otaPattern(unsigned long currentTime) {
    const uint8_t phase = otaPhase;
    const uint8_t pct = otaProgressPct;

    if (phase == 4) {
        const float breathe = (sinf((float)currentTime * 0.006f) + 1.0f) * 0.5f;
        const int g = 32 + (int)(breathe * 180.0f);
        for (int i = 0; i < LED_COUNT; i++) {
            pixels.setPixelColor(i, pixels.Color(0, g, 0));
        }
        return;
    }

    if (phase == 5 || phase == 6 || phase == 7) {
        const bool on = ((currentTime / 170U) % 2U) == 0U;
        const int r = on ? 220 : 40;
        for (int i = 0; i < LED_COUNT; i++) {
            pixels.setPixelColor(i, pixels.Color(r, 0, 0));
        }
        return;
    }

    float phaseSpeed = 0.008f;
    if (phase == 1)
        phaseSpeed = 0.016f;
    else if (phase == 2)
        phaseSpeed = 0.010f;
    else if (phase == 3)
        phaseSpeed = 0.013f;

    const float t = (float)(currentTime - otaPhaseSince) * phaseSpeed;
    const float twoPi = 6.28318530718f;
    int progressLeds = (int)((((float)pct) / 100.0f) * (float)LED_COUNT + 0.5f);
    progressLeds = constrain(progressLeds, 0, LED_COUNT);

    for (int i = 0; i < LED_COUNT; i++) {
        const float a = t + ((float)i * twoPi / (float)LED_COUNT);
        int r = 18 + (int)((sinf(a) + 1.0f) * 95.0f);
        int b = 28 + (int)((sinf(a + 1.57079632679f) + 1.0f) * 95.0f);
        int g = 0;

        if (i < progressLeds) {
            r = min(255, r + 40);
            g = min(255, g + 36);
            b = min(255, b + 65);
        }
        pixels.setPixelColor(i, pixels.Color(r, g, b));
    }
}

void LEDHandler::sweepEffect(int level) {
    const int BASE_BRIGHTNESS = 40;
    const int SWEEP_BRIGHTNESS = 100;
    const int TRAIL_BRIGHTNESS = 70;

    int currentScanSpeed = SCAN_SPEED;
    if (level >= 3) currentScanSpeed = SCAN_SPEED - (level - 2) * 15;

    int r = ringLevels[level].r;
    int g = ringLevels[level].g;
    int b = ringLevels[level].b;
    float intensity = ringLevels[level].intensity;

    for (int i = 0; i < LED_COUNT; i++) {
        float breathe = sin(millis() * 0.001) * 0.3 + 0.7;
        if (level >= 3) breathe *= (random(80, 100) / 100.0) * (1.0 + (level - 2) * 0.2);

        for (int j = 0; j < LED_COUNT; j++) {
            int baseBrightness = BASE_BRIGHTNESS * breathe * intensity;
            if (level >= 3 && random(100) < (level - 2) * 10) baseBrightness *= 1.5;
            pixels.setPixelColor(j, pixels.Color(r * baseBrightness / 255, g * baseBrightness / 255, b * baseBrightness / 255));
        }

        float sweepIntensity = (level >= 3) ? (1.0 + (level - 2) * 0.3) : 1.0;
        int sweepBrightness = SWEEP_BRIGHTNESS * breathe * intensity * sweepIntensity;
        pixels.setPixelColor(i, pixels.Color(r * sweepBrightness / 255, g * sweepBrightness / 255, b * sweepBrightness / 255));

        for (int t = 1; t <= 5; t++) {
            int pos = (i - t + LED_COUNT) % LED_COUNT;
            float fadeRatio = (5.0 - t) / 5.0;
            float trailIntensity = (level >= 3) ? (1.0 + (level - 2) * 0.2) : 1.0;
            int trailBrightness = TRAIL_BRIGHTNESS * fadeRatio * breathe * intensity * trailIntensity;
            pixels.setPixelColor(pos, pixels.Color(r * trailBrightness / 255, g * trailBrightness / 255, b * trailBrightness / 255));
        }
        pixels.show();
        delay(currentScanSpeed);
    }
}

void LEDHandler::handleLevel5() {
    unsigned long currentTime = millis();
    bool flash = (currentTime % 200) < 100;
    int flashBrightness = flash ? 255 : 100;

    for (int j = 0; j < LED_COUNT; j++) {
        pixels.setPixelColor(j, pixels.Color(flashBrightness, 0, 0));
    }

    int position = (currentTime / 50) % LED_COUNT;
    pixels.setPixelColor(position, pixels.Color(255, 255, 255));
    pixels.setPixelColor(position, pixels.Color(255, 0, 0));

    for (int t = 1; t <= 5; t++) {
        int pos = (position - t + LED_COUNT) % LED_COUNT;
        int trailBrightness = 255 - (t * 40);
        pixels.setPixelColor(pos, pixels.Color(trailBrightness, 0, 0));
    }
    pixels.show();
}

void LEDHandler::showAutoCalibrationReady() {
    Logger::info("LED: Auto calibration ready (yellow chase)");
    chaseEffect(255, 255, 0, 3);
}

void LEDHandler::showAutoCalibrationCountdown() {
    Logger::info("LED: Auto calibration countdown (blue flash)");
    flashRing(0, 0, 255, 3);
}

void LEDHandler::showAutoCalibrationCountdownTick() {
    flashRing(0, 0, 255, 1);
}

void LEDHandler::showAutoCalibrationInProgress() {
    Logger::info("LED: Auto calibration in progress (blue progress)");
    progressFill(0, 0, 255);
}

void LEDHandler::showAutoCalibrationActivity(uint8_t progressPct) {
    if (!initialized) return;
    if (otaVisualActive) return;
    autoCalibrationPattern(millis(), progressPct);
    pixels.show();
}

void LEDHandler::showAutoCalibrationSuccess() {
    Logger::info("LED: Auto calibration success (green flash)");
    flashRing(0, 255, 0, 3);
}

void LEDHandler::showAutoCalibrationFailure() {
    Logger::info("LED: Auto calibration failure (red flash)");
    flashRing(255, 0, 0, 3);
}

void LEDHandler::showManualCalibrationReady() {
    Logger::info("LED: Manual calibration ready (purple chase)");
    chaseEffect(128, 0, 128, 3);
}

void LEDHandler::showManualCalibrationCountdown() {
    Logger::info("LED: Manual calibration countdown (orange flash)");
    flashRing(255, 165, 0, 3);
}

void LEDHandler::showManualCalibrationInProgress() {
    Logger::info("LED: Manual calibration in progress (orange figure-8)");
    figureEightFill(255, 165, 0);
}

void LEDHandler::showManualCalibrationAlmostDone() {
    Logger::info("LED: Manual calibration almost done (orange pulse)");
    pulseEffect(255, 165, 0);
}

void LEDHandler::showNormalOperation() {
    Logger::info("LED: Normal operation (teal breathing)");
    breathingEffect(0, 255, 255);
}

void LEDHandler::autoCalibrationPattern(unsigned long currentTime, uint8_t progressPct) {
    const int baseR = 22, baseG = 0, baseB = 38;
    const int head = (int)((currentTime / 45U) % (unsigned long)LED_COUNT);
    int progressLeds = (int)((((float)progressPct) / 100.0f) * (float)LED_COUNT + 0.5f);
    progressLeds = constrain(progressLeds, 0, LED_COUNT);

    for (int i = 0; i < LED_COUNT; i++) {
        int r = baseR, g = baseG, b = baseB;

        if (i < progressLeds) {
            r += 18;
            g += 48;
            b += 8;
        }

        int d = head - i;
        if (d < 0) d += LED_COUNT;
        if (d == 0) {
            r = 235;
            g = 255;
            b = 255;
        } else if (d == 1) {
            r = 40;
            g = 230;
            b = 255;
        } else if (d == 2) {
            r = 24;
            g = 165;
            b = 220;
        } else if (d == 3) {
            r = 16;
            g = 92;
            b = 160;
        }

        pixels.setPixelColor(i, pixels.Color(constrain(r, 0, 255),
                                             constrain(g, 0, 255),
                                             constrain(b, 0, 255)));
    }
}

void LEDHandler::flashRing(int r, int g, int b, int times) {
    for (int i = 0; i < times; i++) {
        setColor(r, g, b);
        delay(300);
        setColor(0, 0, 0);
        delay(300);
    }
}

void LEDHandler::chaseEffect(int r, int g, int b, int loops) {
    for (int j = 0; j < loops; j++) {
        for (int i = 0; i < LED_COUNT; i++) {
            pixels.clear();
            pixels.setPixelColor(i, pixels.Color(r, g, b));
            pixels.show();
            delay(50);
        }
    }
}

void LEDHandler::progressFill(int r, int g, int b) {
    pixels.clear();
    pixels.show();
    for (int i = 0; i < LED_COUNT; i++) {
        pixels.setPixelColor(i, pixels.Color(r, g, b));
        pixels.show();
        delay(50);
    }
}

void LEDHandler::figureEightFill(int r, int g, int b) {
    pixels.clear();
    pixels.show();

    for (int i = 0; i < LED_COUNT / 2; i++) {
        pixels.clear();
        pixels.setPixelColor(i, pixels.Color(r, g, b));
        pixels.setPixelColor(LED_COUNT - 1 - i, pixels.Color(r, g, b));
        pixels.show();
        delay(50);
    }
}

void LEDHandler::pulseEffect(int r, int g, int b) {
    for (int brightness = 0; brightness < 255; brightness += 10) {
        for (int i = 0; i < LED_COUNT; i++) {
            pixels.setPixelColor(i, pixels.Color(r * brightness / 255, g * brightness / 255, b * brightness / 255));
        }
        pixels.show();
        delay(10);
    }

    for (int brightness = 255; brightness > 0; brightness -= 10) {
        for (int i = 0; i < LED_COUNT; i++) {
            pixels.setPixelColor(i, pixels.Color(r * brightness / 255, g * brightness / 255, b * brightness / 255));
        }
        pixels.show();
        delay(10);
    }
}

void LEDHandler::breathingEffect(int r, int g, int b) {
    for (int i = 0; i < 2; i++) {
        for (int brightness = 0; brightness < 255; brightness += 5) {
            setColor(r * brightness / 255, g * brightness / 255, b * brightness / 255);
            delay(10);
        }
        for (int brightness = 255; brightness > 0; brightness -= 5) {
            setColor(r * brightness / 255, g * brightness / 255, b * brightness / 255);
            delay(10);
        }
    }
}

void LEDHandler::breathingPattern(int r, int g, int b, unsigned long currentTime) {
    float breath = (sin(currentTime * 0.001) + 1.0) / 2.0;
    int brightness = (int)(breath * 100.0) + 20;

    for (int i = 0; i < LED_COUNT; i++) {
        int rr = r * brightness / 255;
        int gg = g * brightness / 255;
        int bb = b * brightness / 255;
        maybeApplyDirectionShade(i, rr, gg, bb, true);
        pixels.setPixelColor(i, pixels.Color(rr, gg, bb));
    }
}

void LEDHandler::sweepPattern(int r, int g, int b, unsigned long currentTime, int speed, int level) {
    int position = (currentTime / speed) % LED_COUNT;

#if LED_DIRECTION_MODE == 0
    int baseFrac = 20;
#else
    int baseFrac = 10 + level * 12;
#endif
    for (int i = 0; i < LED_COUNT; i++) {
        int rr = r * baseFrac / 100;
        int gg = g * baseFrac / 100;
        int bb = b * baseFrac / 100;
        maybeApplyDirectionShade(i, rr, gg, bb, false);
        pixels.setPixelColor(i, pixels.Color(rr, gg, bb));
    }

    {
        int rh = r, gh = g, bh = b;
        maybeApplyDirectionShade(position, rh, gh, bh, false);
        pixels.setPixelColor(position, pixels.Color(rh, gh, bh));
    }

    for (int t = 1; t <= 3; t++) {
        int pos = (position - t + LED_COUNT) % LED_COUNT;
        float fade = (4.0 - t) / 4.0;
        int tr = (int)(r * fade), tg = (int)(g * fade), tb = (int)(b * fade);
        maybeApplyDirectionShade(pos, tr, tg, tb, false);
        pixels.setPixelColor(pos, pixels.Color(tr, tg, tb));
    }
}

void LEDHandler::flashPattern(int r, int g, int b, unsigned long currentTime) {
    bool on = (currentTime % 250) < 125;

    for (int i = 0; i < LED_COUNT; i++) {
        int rr = on ? r : r / 4;
        int gg = on ? g : g / 4;
        int bb = on ? b : b / 4;
        maybeApplyDirectionShade(i, rr, gg, bb, false);
        pixels.setPixelColor(i, pixels.Color(rr, gg, bb));
    }
}

void LEDHandler::setColor(int r, int g, int b) {
    for (int i = 0; i < LED_COUNT; i++) {
        pixels.setPixelColor(i, pixels.Color(r, g, b));
    }
    pixels.show();
}

void LEDHandler::setLED(int led, int r, int g, int b) {
    if (led >= 0 && led < LED_COUNT) {
        pixels.setPixelColor(led, pixels.Color(r, g, b));
        pixels.show();
    }
}
