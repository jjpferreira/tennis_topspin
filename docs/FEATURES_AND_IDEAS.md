# Tennis Shot Bench Prototype — product backlog

**Reset (2026-04-23):** Backlog aligned to the **Tennis Shot Bench Prototype — Requirements Specification** (bench rig, Hall rotation + arm motion, ESP32 acquisition, Python desktop court, approximate shot model; out of scope: free-flight ball tracking, high-speed video, production enclosure, v1 mobile ship).

**Layers (spec §4):** Sensor → Embedded processing → Desktop application → Future mobile (reserved).

### Simulator & pipeline alignment (Python app)

The existing **Python simulator** is built around **sensor-driven simulation**, not direct measurement of a free-flying ball. That matches this prototype: rig + ESP32 produce **proxies**; the desktop app turns them into trajectory, court placement, and color-coded results.

**What the simulator expects (conceptually):**

- **Speed (or a proxy)** — used as the “ball speed” input to trajectory logic.
- **Arm angle** — maps to the simulator’s angle input.
- **Spin bias** (optional) — can remain synthetic or be tied to a future derived signal.

**Canonical mapping (define explicitly in code / calibration docs):**

| ESP32 / pipeline output | Python / simulator role |
|-------------------------|-------------------------|
| `rpm` (and/or `angular_velocity`) | **Speed** after conversion (not “true ball speed”) |
| `arm_angle` (from IMU fusion or A→B model) | **Angle** |
| Optional future field | **Spin** |

**Conversion layer (required):** The simulator assumes **speed is already a usable scalar** for physics/UI. The device will naturally emit **RPM** and **ω** first. You must implement an explicit bridge — **on the ESP32, in Python, or split** — for example `speed = 2 * pi * r * f` from radius + frequency, or a **calibrated linear map** `speed = rpm * K` (and tune `K` against bench behavior). Start with a placeholder `K` (e.g. `speed = rpm * 0.05`) and replace with calibration (**FEAT-010**, **FEAT-004**).

**End-to-end data flow:**

```
ESP32:  Hall → RPM / ω          Arm sensor → angle / arm velocity
              ↓                           ↓
        (optional local convert)   (optional local fusion)
              ↓                           ↓
        JSON / serial stream  →  Python: ingest → convert RPM→speed → simulator → court + trajectory + colors
```

**Tickets that own this glue:** **FEAT-004** (shot estimation / rig geometry), **FEAT-008** (ingest + refine), **FEAT-010** (constants such as `K`, radii, court scaling). Until that mapping is documented and implemented, treat “live simulator” integration as incomplete even if raw telemetry works.

---

## Features & Ideas

### [PLANNED] [HIGH] FEAT-001: Rotation measurement — Hall pulses, timing, RPM, and angular velocity

**Feature ID:** `FEAT-001` | **Status:** `[PLANNED]` | **Priority:** `[HIGH]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 5

**Description:** Meet **§5.1 Rotation measurement** and **§8.1**: Hall sensor detects magnets on the spinning element; ESP32 records pulse timing with **high-resolution timing** (`micros()` or equivalent); compute pulse interval, frequency, RPM, and angular velocity; **pulses per revolution** configurable in software; support calibration for pulses-per-revolution. Outputs: current RPM, angular velocity, timestamped rotation events. Traces to **Sensor A** / rotation role (**§12**).

**Related:** FEAT-007 (embedded integration), FEAT-006 (telemetry fields), FEAT-010 (rotation calibration), FEAT-011 (debounce / noise), FEAT-016 (MVP).

---

### [PLANNED] [HIGH] FEAT-002: Arm movement measurement — IMU on arm (Option A, MVP preferred)

**Feature ID:** `FEAT-002` | **Status:** `[PLANNED]` | **Priority:** `[HIGH]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 5

**Description:** Meet **§5.2 Option A**: read gyro from IMU on the arm; optionally accelerometer for extra analysis; derive arm angular velocity; estimate arm angle; support **estimated arm tip speed** using known arm geometry (constants configurable, not hardcoded deep in logic — **§13.4**). Outputs per spec: arm angle, arm angular velocity, arm travel timing as applicable, estimated arm tip speed. Traces to **Sensor B** when IMU is chosen (**§12**).

**Related:** FEAT-007 (firmware read path), FEAT-006 (stream fields: arm_angle, arm_speed, accel_*, gyro_*), FEAT-004 (shot model inputs), FEAT-010 (arm / IMU calibration), FEAT-011 (smoothing / drift awareness per **§15.1**), FEAT-016 (MVP).

---

### [IDEA] [LOW] FEAT-003: Arm movement — Option B/C (dual gates or Hall checkpoints)

**Feature ID:** `FEAT-003` | **Status:** `[IDEA]` | **Priority:** `[LOW]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 3

**Description:** Meet **§5.2** alternatives: **Option B** — detect arm at A and B, measure transition time, derive speed from distance/time; **Option C** — Hall checkpoints for home/strike reference; do not rely solely on Hall for continuous arm-speed profiling unless rig-justified. Defer until IMU path is validated or rig design favors gates.

**Related:** FEAT-002 (preferred path), FEAT-004 (same downstream shot inputs), FEAT-001 (Hall reuse for checkpoints only).

---

### [PLANNED] [HIGH] FEAT-004: Shot estimation — combine rotation + arm data into speed, direction, landing

**Feature ID:** `FEAT-004` | **Status:** `[PLANNED]` | **Priority:** `[HIGH]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** High | **Business Value:** 5

**Description:** Meet **§5.3 Shot estimation** and **§8.3**: model accepts RPM or angular velocity from the mechanism and arm motion inputs; **configurable rig geometry**; produces estimated shot speed and direction and **predicted landing position** in virtual court space; explicitly an **approximation**, tunable for bench use (**§2**, **§15.2**). May split firmware vs desktop refinement per **§13.2** modularity.

**Related:** FEAT-001 (rotation inputs), FEAT-002 (arm inputs), FEAT-005 (renders outputs), FEAT-008 (Python refinement layer), FEAT-010 (simulation-side calibration).

---

### [PLANNED] [HIGH] FEAT-005: Virtual tennis visualization — court dashboard, shots, trajectory, history, modes

**Feature ID:** `FEAT-005` | **Status:** `[PLANNED]` | **Priority:** `[HIGH]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 5

**Description:** Meet **§5.4** and **§7.3**: tennis court layout; predicted shot placement; **color coding** for speed band, validity, future clustering; trajectory or path indication; repeated shots and **shot history**; **randomized simulation mode** for demo plus **live sensor-driven mode**; session clear/reset; show current measured values where required (**§7.3**).

**Related:** FEAT-004 (estimated outcomes), FEAT-008 (desktop shell), FEAT-009 (sim vs live), FEAT-012 (export/history tooling), FEAT-016 (MVP).

---

### [PLANNED] [HIGH] FEAT-006: Data streaming — USB serial MVP, structured JSON (or compact CSV), field contract

**Feature ID:** `FEAT-006` | **Status:** `[PLANNED]` | **Priority:** `[HIGH]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 5

**Description:** Meet **§5.5**: stream from ESP32 to desktop; **MVP preferred: USB serial**; optional later BLE / Wi-Fi WebSocket (**§5.5**, **§17**). Payload machine-readable: **JSON lines** preferred, or compact CSV-like if performance requires. Example fields per spec: `timestamp`, `rpm`, `angular_velocity`, `arm_angle`, `arm_speed`, `accel_x`…`gyro_z`. Protocol should be **versionable** (**§13.2**).

**Related:** FEAT-007 (transmitter), FEAT-008 (consumer), FEAT-013 (NFR / versioning), FEAT-014 (future BLE), FEAT-016 (MVP).

---

### [PLANNED] [HIGH] FEAT-007: ESP32 firmware — sensor init, interrupt paths, micros timing, telemetry, error handling

**Feature ID:** `FEAT-007` | **Status:** `[PLANNED]` | **Priority:** `[HIGH]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** High | **Business Value:** 5

**Description:** Meet **§6 Embedded software**: initialize sensors; read Hall and arm-motion sensor; **interrupt-based capture** where appropriate; **micros()** (or equivalent) for Hall timestamps; basic local calculations; continuous or interval transmission; **§6.2** fast arm motion without missing critical events; **non-blocking** real-time path; **§6.3** detect missing/stale/invalid data, graceful pulse loss, fallback/reset for calibration/startup.

**Related:** FEAT-001 (Hall path), FEAT-002 (arm path), FEAT-006 (output transport), FEAT-011 (filtering hooks), FEAT-016 (MVP).

---

### [PLANNED] [HIGH] FEAT-008: Python desktop application — connect, ingest, parse, estimation, render, history

**Feature ID:** `FEAT-008` | **Status:** `[PLANNED]` | **Priority:** `[HIGH]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** High | **Business Value:** 5

**Description:** Meet **§7.1**: connect to ESP32 data source; ingest live data; parse messages; calculate or refine shot estimation; render shot visually; support **historical shot review**. Host role per **§12**. Separates ingestion / calculation / UI per **§13.2** where practical.

**Related:** FEAT-006 (wire format), FEAT-004 (estimation), FEAT-005 (court UI), FEAT-009 (modes), FEAT-012 (logging/export), FEAT-016 (MVP).

---

### [PLANNED] [MEDIUM] FEAT-009: Application modes — simulation (randomized), live, optional replay

**Feature ID:** `FEAT-009` | **Status:** `[PLANNED]` | **Priority:** `[MEDIUM]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 4

**Description:** Meet **§7.2**: **Simulation mode** — randomized values, synthetic outcomes; **Live mode** — real ESP32 data, near-real-time dashboard; **Replay mode** optional/future per spec — replay recorded sessions (**§17** aligns with session storage later).

**Related:** FEAT-005 (UI surfaces modes), FEAT-008 (app shell), FEAT-012 (recordings for replay).

---

### [IN-PROGRESS] [HIGH] FEAT-010: Calibration — rotation, arm, and simulation tuning parameters

**Feature ID:** `FEAT-010` | **Status:** `[IN-PROGRESS]` | **Priority:** `[HIGH]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-28  
**Complexity:** High | **Business Value:** 5

**Description:** Meet **§9**: **Rotation** — pulses per revolution, magnet alignment, debounce thresholds; **Arm** — zero/home, strike reference, motion scaling, IMU baseline if used; **Simulation** — court scaling, speed-to-color mapping, depth and lateral spread coefficients. Calibration values configurable, not buried (**§13.4**).

**Related:** FEAT-001, FEAT-002, FEAT-004, FEAT-005 (thresholds in UI), FEAT-011 (debounce ties to rotation).

---

### [PLANNED] [MEDIUM] FEAT-011: Data quality and filtering — debounce, smoothing, outliers, fusion-ready design

**Feature ID:** `FEAT-011` | **Status:** `[PLANNED]` | **Priority:** `[MEDIUM]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 4

**Description:** Meet **§10**: pulse debouncing; smoothing unstable readings; configurable filters; outlier / implausible detection; design allowance for moving average, low-pass, Kalman-style fusion later (**§15.1** risks inform defaults).

**Related:** FEAT-001 (Hall debounce), FEAT-002 (IMU noise), FEAT-004 (clean inputs to model), FEAT-007 (firmware vs host split).

---

### [PLANNED] [MEDIUM] FEAT-012: Logging, diagnostics, and session export (CSV / JSON)

**Feature ID:** `FEAT-012` | **Status:** `[PLANNED]` | **Priority:** `[MEDIUM]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 4

**Description:** Meet **§11**: raw and derived logging; timestamped event records; session export (**CSV** / **JSON**); basic debug view: current RPM, arm values, **connection state**, **calibration state** (**§11**).

**Related:** FEAT-008 (desktop), FEAT-009 (replay later consumes exports), FEAT-010 (surface calibration state).

---

### [IN-PROGRESS] [HIGH] FEAT-018: Student profiles and session-to-session comparison with performance stats

**Feature ID:** `FEAT-018` | **Status:** `[IN-PROGRESS]` | **Priority:** `[HIGH]` | **Added:** 2026-04-28 | **Last Updated:** 2026-04-28  
**Complexity:** High | **Business Value:** 5

**Description:** Extend the simulator so coaches can load student profiles, save multiple sessions per student, and compare recent sessions using meaningful statistics (shots, speed, spin, consistency, and impact quality) to track progression and guide training decisions.

**Related:** FEAT-005 (dashboard UX), FEAT-008 (desktop app capabilities), FEAT-012 (session/log data handling), FEAT-016 (MVP evolution).

---

### [IN-PROGRESS] [HIGH] FEAT-019: Topspin coaching intelligence — spin type, cues, and benchmark score

**Feature ID:** `FEAT-019` | **Status:** `[IN-PROGRESS]` | **Priority:** `[HIGH]` | **Added:** 2026-04-29 | **Last Updated:** 2026-04-29  
**Complexity:** Medium | **Business Value:** 5

**Description:** Add live topspin-specific coaching outputs to the desktop app: classify shot spin type (topspin/flat/slice), compute racket-face proxy and swing-path brush proxy from available impact/angle signals, produce real-time coaching cues (e.g., "too flat", "open face", "good brush"), and surface a benchmark comparison score against a configurable "pro topspin" profile.

**Related:** FEAT-004 (shot estimation), FEAT-005 (visual feedback), FEAT-008 (desktop processing), FEAT-010 (calibration), FEAT-018 (player progression context).

---

### [IN-PROGRESS] [HIGH] FEAT-020: Shot intent and physics context — target zones, net clearance, bounce, and drill mode

**Feature ID:** `FEAT-020` | **Status:** `[IN-PROGRESS]` | **Priority:** `[HIGH]` | **Added:** 2026-04-29 | **Last Updated:** 2026-04-29  
**Complexity:** High | **Business Value:** 5

**Description:** Extend the simulator with practical coaching context: shot type tagging (forehand/backhand/serve), target-zone overlays, estimated net clearance, estimated post-bounce behavior, court-surface selector (hard/clay/grass), and focused drill mode feedback for repetition-based topspin practice.

**Analysis:** [FEAT-020 analysis](analysis/FEAT_020_SHOT_INTENT_AND_PHYSICS_CONTEXT_ANALYSIS.md)

**Related:** FEAT-005 (court visualization), FEAT-008 (desktop app), FEAT-009 (mode behavior), FEAT-012 (session analytics), FEAT-018 (student comparison).

---

### [PLANNED] [MEDIUM] FEAT-013: Non-functional — bench-real-time performance, modularity, extensibility

**Feature ID:** `FEAT-013` | **Status:** `[PLANNED]` | **Priority:** `[MEDIUM]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 4

**Description:** Meet **§13**: **§13.1** responsive bench demo, visually smooth live updates, sampling adequate for fast arm + rotation; **§13.2** separate sensor reading, calculation, and UI rendering; **stable versionable** comms (**§13.2**); **§13.3** extensibility path for iOS, BLE, extra sensors, richer physics, cloud/session storage; **§13.4** clean structure and configurable constants.

**Related:** FEAT-006 (protocol), FEAT-007 (embedded structure), FEAT-008 (desktop structure), FEAT-014, FEAT-015 (extensibility targets).

---

### [IDEA] [MEDIUM] FEAT-014: Optional transport — BLE streaming to desktop or mobile bridge

**Feature ID:** `FEAT-014` | **Status:** `[IDEA]` | **Priority:** `[MEDIUM]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** Medium | **Business Value:** 3

**Description:** Future enhancement per **§5.5** and **§17**: BLE as optional transport; same logical field contract as serial where possible. After MVP serial path is stable.

**Related:** FEAT-006 (baseline schema), FEAT-008 (new transport backend), FEAT-015 (mobile).

---

### [IDEA] [LOW] FEAT-015: Future mobile layer — iOS (or similar) consuming telemetry and court UI

**Feature ID:** `FEAT-015` | **Status:** `[IDEA]` | **Priority:** `[LOW]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** High | **Business Value:** 4

**Description:** Reserved **§4.4 Future mobile layer** and **§2** / **§17**: iOS app (or cross-platform) for BLE (or bridged) data, charts, court, replay — **not** initial prototype scope.

**Related:** FEAT-014 (BLE), FEAT-006 (data contract), FEAT-005 (UX reference).

---

### [PLANNED] [HIGH] FEAT-016: MVP vertical — Hall + IMU, structured serial, live court, shot plotting, metrics

**Feature ID:** `FEAT-016` | **Status:** `[PLANNED]` | **Priority:** `[HIGH]` | **Added:** 2026-04-23 | **Last Updated:** 2026-04-23  
**Complexity:** High | **Business Value:** 5

**Description:** Meet **§16 Recommended MVP**: hardware assumptions (ESP32, Hall on spinner, IMU on arm, magnets); firmware — pulse timing, RPM, IMU read, **structured serial output**; desktop — **live serial input**, **virtual tennis court**, **shot plotting**, **speed and arm metrics** display. Proves reliable sensing, combinable data, and visual simulation concept (**§16**). Aligns with **§18** one-paragraph summary.

**Related:** FEAT-001, FEAT-002, FEAT-004, FEAT-005, FEAT-006, FEAT-007, FEAT-008 (cross-cutting acceptance for first shippable bench demo).

---

## Bugs & Issues

_No open bugs filed. Add `BUG-001` style blocks here when issues are tracked._

---

## Completed Features ✅

### ✅ FEAT-017: ADXL335 impact telemetry and simulator impact visualization
**Feature ID:** `FEAT-017` | **Status:** `[COMPLETED]` | **Priority:** `[HIGH]` | **Added:** 2026-04-28 | **Completed:** 2026-04-28 | **Last Updated:** 2026-04-28

**Description:** Add ADXL335-based impact capture to firmware and stream impact payloads to the desktop simulator so shot rendering reflects where and how the ball was impacted (including intensity/redness visualization).

**Implementation completed:** Added a modular `ADXL335Sensor` firmware component with baseline sampling and per-hit impact capture; introduced BLE impact characteristic and payload contract; integrated impact packets in the Python monitor to influence live shot generation, display impact metadata, and render red impact intensity cues on court shots; extended history and CSV export with impact fields.

**Related:** FEAT-005 (court visualization), FEAT-006 (telemetry contract), FEAT-007 (firmware integration), FEAT-008 (desktop ingest and render), FEAT-010 (calibration tuning), FEAT-012 (export/history).

**Complexity:** High | **Business Value:** 5

---

## Notes

- **Simulator contract:** See **Simulator & pipeline alignment** above — RPM/ω → **speed** conversion is a deliberate product/engineering requirement, not an afterthought.
- **Out of scope (spec):** free-flight ball tracking, high-speed camera, full physics accuracy, production enclosure, v1 mobile deployment — do not fold into MVP acceptance without explicit scope change.
- **Risks (§15):** Hall ≠ true ball-flight speed; IMU drift; magnet placement; estimation limits — document in implementation/analysis when relevant.
- **Parser:** `python3 docs/kaban/parse_features_md.py` from repo root refreshes `docs/kaban/features.json` and `docs/kaban/kanban.html`.
