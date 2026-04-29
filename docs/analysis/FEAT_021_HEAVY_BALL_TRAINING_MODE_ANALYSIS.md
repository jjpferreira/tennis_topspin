# FEAT-021 Analysis — Heavy Ball Training Mode

## Summary

Heavy ball in this prototype is not directly measured as ball mass/force in flight. It is approximated from the hardware signals we already capture and the simulator's derived physics context. The most practical definition for coaching use is a threshold-based combination of:

- pace (gate speed blended into live speed),
- spin load (RPM/spin proxy),
- depth (landing position),
- impact quality proxy (impact redness/intensity from ADXL signal path).

This is enough to support an actionable drill mode today without new hardware.

## Current Hardware Signals Available

- Main hall sensor path provides rate/RPM-derived rotational metrics.
- Dual gate hall sensors provide short-distance transit timing and speed estimate.
- ADXL335 impact pipeline provides contact/intensity proxy that already feeds shot impact redness.
- Existing shot model produces landing coordinates and context fields (net clearance, bounce kick, spin type).

## Gap Before This Feature

- No dedicated heavy-ball drill mode in the target selector.
- No heavy-ball-specific hit criteria and goal progression.
- No heavy-ball target overlay/label in court visualization.
- Training helper text had no heavy-ball guidance.

## Implementation Approach

1. Add a new drill option `20 Heavy Ball` to target selectors (header chip + app settings training tab).
2. Add visual target overlay mode for heavy-ball zone.
3. Define heavy-ball hit criteria using available signals:
   - speed >= 58 mph
   - spin >= 1900 rpm-proxy
   - deep landing (`landing_y >= 7.2`)
   - central/deep corridor (`abs(landing_x) <= 2.8`)
   - impact quality proxy (`impact_redness >= 45`)
4. Reuse existing drill progress tracking (`hits/goal/attempts`) with goal = 20.
5. Add heavy-ball palette/label in target chip styling and helper text.

## Risks and Notes

- Thresholds are coaching heuristics for this rig; they should remain tunable after field testing.
- "Heavy ball" remains a proxy label in this MVP because we do not directly measure post-bounce opponent difficulty.
- Criteria may need per-level tuning (Newbie/Competitive/Professional) in a follow-up iteration.

## Acceptance Criteria

- User can select `20 Heavy Ball` in both main target chip and settings training controls.
- Court shows heavy-ball overlay when mode is active.
- Drill progress increments only when heavy-ball thresholds are met.
- UI labels and chip color update correctly for heavy-ball mode.
- Session summary keeps drill mode/hits/attempts/hit-rate with heavy-ball sessions.
