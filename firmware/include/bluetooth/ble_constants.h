#pragma once

// Tennis BLE service
#define TENNIS_SERVICE_UUID      "7f4af201-1fb5-459e-8fcc-c5c9c331914b"

// Telemetry characteristics
#define TENNIS_STATE_UUID        "7be5483e-36e1-4688-b7f5-ea07361b26a1" // uint8  0/1
#define TENNIS_COUNT_UUID        "7be5483e-36e1-4688-b7f5-ea07361b26a2" // uint32 hit count
#define TENNIS_RATE_X10_UUID     "7be5483e-36e1-4688-b7f5-ea07361b26a3" // uint16 events/sec * 10
#define TENNIS_IMPACT_UUID       "7be5483e-36e1-4688-b7f5-ea07361b26a5" // packed impact payload

// Control characteristic (UTF-8 write commands)
#define TENNIS_COMMAND_UUID      "7be5483e-36e1-4688-b7f5-ea07361b26a4"
