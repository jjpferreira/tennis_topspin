#include "../include/calibration_store.h"

#include <Preferences.h>

namespace {
constexpr const char* kNs = "tns_cal";
constexpr const char* kVerKey = "imp_v";
constexpr const char* kCountsKey = "imp_cpg";
constexpr const char* kImpactKey = "imp_mg100";
constexpr const char* kContactKey = "imp_full";
constexpr uint8_t kImpactCalibrationVersion = 1;
}  // namespace

bool CalibrationStore::loadImpactCalibration(ImpactCalibration& out) {
    Preferences prefs;
    if (!prefs.begin(kNs, true)) {
        return false;
    }
    const uint8_t ver = prefs.getUChar(kVerKey, 0);
    if (ver != kImpactCalibrationVersion) {
        prefs.end();
        return false;
    }

    out.countsPerG = prefs.getFloat(kCountsKey, out.countsPerG);
    out.impactMgAt100 = prefs.getUShort(kImpactKey, out.impactMgAt100);
    out.contactFullScaleMg = prefs.getUShort(kContactKey, out.contactFullScaleMg);
    prefs.end();
    return true;
}

bool CalibrationStore::saveImpactCalibration(const ImpactCalibration& cfg) {
    Preferences prefs;
    if (!prefs.begin(kNs, false)) {
        return false;
    }
    prefs.putUChar(kVerKey, kImpactCalibrationVersion);
    prefs.putFloat(kCountsKey, cfg.countsPerG);
    prefs.putUShort(kImpactKey, cfg.impactMgAt100);
    prefs.putUShort(kContactKey, cfg.contactFullScaleMg);
    prefs.end();
    return true;
}
