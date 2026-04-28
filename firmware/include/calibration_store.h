#pragma once

#include <Arduino.h>
#include "./adxl335/adxl335_sensor.h"

class CalibrationStore {
public:
    static bool loadImpactCalibration(ImpactCalibration& out);
    static bool saveImpactCalibration(const ImpactCalibration& cfg);
    static bool loadRuntimeConfig(float& gateDistanceCm, uint16_t& rpmPulsesPerRev);
    static bool saveRuntimeConfig(float gateDistanceCm, uint16_t rpmPulsesPerRev);
};
