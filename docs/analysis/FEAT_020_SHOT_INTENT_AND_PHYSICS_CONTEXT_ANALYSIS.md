# FEAT-020 Analysis: Shot Intent and Physics Context

## Feature Summary

**Feature ID:** `FEAT-020`  
**Title:** Shot intent and physics context - target zones, net clearance, bounce, and drill mode  
**Status:** `[IN-PROGRESS]`

This feature adds coaching-oriented shot context around each event: shot intent labeling, target success checks, physics-informed indicators (net clearance and bounce kick), court-surface influence, and drill progression feedback.

## Current State (Implemented)

The following FEAT-020 scope is already implemented in `python_app/realtime_tennis_monitor.py`:

- **Shot type tagging:** automatic inference for `Forehand` / `Backhand` / `Serve`.
- **Target-zone evaluation:** shot-level hit/miss check via `_is_target_zone_hit(...)`.
- **Physics context metrics:** `_estimate_net_clearance(...)` and `_estimate_bounce_kick(...)`.
- **Court surface selection:** `Hard`, `Clay`, `Grass` selector with bounce effect multiplier.
- **Drill mode:** preset `20 Topspin Cross-Court` with progress and completion feedback.
- **Session/export integration:** new fields exported to CSV (`shot_type`, `net_clearance_m`, `bounce_kick_m`, `target_zone_hit`).
- **UI integration:** current shot + history surfaces include target and physics context.

## Gap Assessment (What Is Still Missing)

Primary gaps for FEAT-020 to be considered fully complete from a coaching UX perspective:

1. **Visual target-zone overlays on court**
   - Current implementation calculates zone hit/miss but does not render explicit target zones on the court widget.
2. **Explicit shot-intent selection override**
   - Current shot type is inferred; no manual coach/player override at capture time.
3. **Multiple drill templates**
   - Only one drill is currently available; no configurable drill library.
4. **Drill persistence in session analytics**
   - Drill outcomes are visible live but not yet summarized across sessions in Stats BI.
5. **Model calibration knobs**
   - Net clearance and bounce are heuristic and not yet calibrated per player/bench setup.

## Risks and Constraints

- **Heuristic realism risk:** Net clearance and bounce are estimated proxies, not full physics simulation.
- **Sensor proxy dependency:** Inferred intent depends on current derived telemetry quality.
- **UX density risk:** Added metrics can overwhelm users without simple/advanced gating (mitigated by existing detail toggle).

## Recommended Implementation Order

1. **Court overlays (highest impact)**
   - Render visual target zones (cross-court/deep targets, serve boxes) in `CourtWidget`.
2. **Drill expansion**
   - Add 3-5 preconfigured drill templates with per-drill pass criteria.
3. **Manual shot intent override**
   - Add optional shot intent selector for coach-led sessions.
4. **Stats BI drill summaries**
   - Add drill success rates and trend cards by session/student.
5. **Calibration**
   - Add settings inputs for net/bounce estimation coefficients by surface.

## Acceptance Criteria (Proposed)

FEAT-020 should be considered implementation-complete when:

- Target zones are visible on-court and hit/miss aligns with rendered zones.
- At least one topspin drill and one serve drill are selectable and tracked.
- Shot intent can be inferred and optionally overridden.
- Net clearance and bounce are shown per shot and included in export/session data.
- Surface selection affects bounce consistently and is reflected in UI labels.

## Testing Plan

- **Functional UI test:** switch surfaces and confirm bounce kick changes directionally (`Clay > Hard > Grass`).
- **Drill logic test:** verify drill hit counter increments only on valid drill criteria.
- **Regression test:** ensure live/simulation mode switching still functions with drill/surface controls.
- **Export contract test:** verify new FEAT-020 columns are present and populated in CSV output.

## Notes

- FEAT-020 is partially delivered and already usable for coaching context.
- Remaining scope is mostly **visualization depth + configurability**, not core data-path plumbing.
