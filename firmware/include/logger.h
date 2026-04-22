#pragma once

#include <Arduino.h>

class Logger {
public:
    static inline void info(const String& msg) {
        Serial.println(String("[INF] ") + msg);
    }

    static inline void warn(const String& msg) {
        Serial.println(String("[WRN] ") + msg);
    }

    static inline void error(const String& msg) {
        Serial.println(String("[ERR] ") + msg);
    }
};
