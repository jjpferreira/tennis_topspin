"""Single source of truth for physical-rig constants on the Python side.

The firmware has its own copy of these in `firmware/include/config.h` because
the C++ build cannot read this Python module. **Both files must stay in
sync.** A regression test (see `tests/test_python_app_ble_regressions.py`)
asserts that the two values match exactly so a drift fails CI before the
mismatch reaches the dashboard.

The Python app uses these values for:
  * UI defaults before the first firmware reading arrives.
  * Sanity bounds when validating user-entered overrides in settings.
  * Offline analysis tools that don't talk to the firmware.

When the firmware is online its runtime value (loaded from NVS, override-able
over BLE) is treated as ground truth and the Python copy is only used as a
fallback. So changing this constant has no effect on a live session UNTIL
the firmware is reflashed and the matching `KY003_GATE_DISTANCE_CM` macro is
rebuilt.

Why a separate module instead of inlining in realtime_tennis_monitor.py:
  * Keeps physical-rig facts visible at one well-known location.
  * Lets future Python tools (logging, analysis, CLI) import the same value.
  * Makes the regression test trivially short and obvious.
"""

from __future__ import annotations


# Centre-to-centre spacing between the two KY-003 gate sensors, in cm.
# Update both this value AND firmware/include/config.h::KY003_GATE_DISTANCE_CM
# whenever the physical rig changes. Speed = distance / transit_time; getting
# this wrong scales every recorded shot speed by the same factor.
#
# At 4.3 cm spacing the firmware's 500 us min-transit guard caps measurable
# speed at ~310 km/h, which leaves plenty of headroom for serves. The
# previous 1.0 cm rig silently dropped anything faster than 72 km/h.
GATE_DISTANCE_CM: float = 4.3


# Default RPM pulses-per-revolution for the main hall sensor. Mirrors
# firmware/include/config.h::KY003_RPM_PULSES_PER_REV. The dashboard divides
# the firmware's reported edge rate by this number to display revolutions
# per minute.
RPM_PULSES_PER_REV: int = 1
