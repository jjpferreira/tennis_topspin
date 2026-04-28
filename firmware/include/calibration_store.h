#pragma once

#include <Arduino.h>
#include "./sensor/adxl335_sensor.h"

class CalibrationStore {
public:
    static bool loadImpactCalibration(ImpactCalibration& out);
    static bool saveImpactCalibration(const ImpactCalibration& cfg);
};
