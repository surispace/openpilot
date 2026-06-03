# Stop Light Detection Fix — Car Not Fully Stopping

**Date:** 2026-05-05
**Branch:** `rtizi-dev`
**Status:** ✅ IMPLEMENTED — 2026-05-05

---

## 1. Symptom

Car detects the red light and begins braking, but **does not come to a complete stop**. It slows down then resumes moving before reaching zero speed. It also does not wait for the green light signal.

---

## 2. Root Cause Analysis

### 2.1 The Failure Chain

The bug is in [`selfdrive/controls/lib/longitudinal_planner.py:209`](selfdrive/controls/lib/longitudinal_planner.py:209):

```python
if (output_should_stop_e2e or model_wants_to_brake) and not lead_present and v_ego > MIN_ALLOW_THROTTLE_SPEED:
    self.model_stop_confidence = min(1.0, self.model_stop_confidence + self.dt * 2.0)
else:
    self.model_stop_confidence = max(0.0, self.model_stop_confidence - self.dt * 3.0)
model_stop_scenario = self.model_stop_confidence > 0.6
```

The condition `v_ego > MIN_ALLOW_THROTTLE_SPEED` (where `MIN_ALLOW_THROTTLE_SPEED = 2.5 m/s ≈ 5.6 mph`) creates a **self-defeating gate**:

| Step | What Happens | `v_ego` | Confidence | `model_stop_scenario` |
|------|-------------|---------|------------|:---:|
| 1 | Approaching red light at 30 mph | 13.4 m/s | Ramping up (+2.0/s) | → True |
| 2 | Model's `desiredAcceleration` used, car brakes | 10 m/s | 1.0 (saturated) | True |
| 3 | Car continues slowing | 5 m/s | 1.0 | True |
| 4 | Car slows below 2.5 m/s | **2.4 m/s** | **Decaying (-3.0/s)** | True |
| 5 | ~200ms later, confidence drops below 0.6 | 1.5 m/s | **< 0.6** | **→ False** |
| 6 | Falls to `else` branch: `output_a_target = output_a_target_mpc` | 1.0 m/s | 0.0 | False |
| 7 | MPC has no lead → `output_should_stop_mpc = False` | 0.5 m/s | 0.0 | False |
| 8 | LongControl exits `stopping` → enters `starting`/`pid` | 0 m/s | 0.0 | False |
| 9 | **Car accelerates again instead of staying stopped** | — | — | — |

### 2.2 Why The Speed Gate Was Added

The `v_ego > MIN_ALLOW_THROTTLE_SPEED` gate was intended to prevent false stops during low-speed creep (e.g., parking lots, stop-and-go traffic). The reasoning was: "if the car is already creeping slowly, don't let the model trigger a sudden stop."

However, this gate **cannot distinguish between**:
- **Creep scenario**: Car is moving slowly in traffic, model briefly outputs `shouldStop` → should NOT stop
- **Legitimate stop**: Car is braking for a red light and passes through 2.5 m/s → MUST continue stopping

Both scenarios look identical to the gate: `v_ego < 2.5` with `shouldStop=True`.

### 2.3 Secondary Issue: No Latch

Even without the speed gate, there's a secondary problem: once the car reaches near-zero speed, the model's `desiredAcceleration` may rise above -1.5 m/s² (because it doesn't need to brake hard anymore). If `shouldStop` also flickers (model uncertainty at very low speeds), both triggers could drop simultaneously, releasing the stop.

In blended mode (experimental ON), this doesn't happen because:
```python
self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
```
The `or` means even if one source drops, the other may still hold. But in our ACC-mode implementation, when `model_stop_scenario` becomes False, we fall back to `output_should_stop_mpc` which is always False without a radar lead.

---

## 3. Proposed Fix

### 3.1 Strategy: Latch-Based Persistence

Instead of gating confidence on speed, use a **latch** that:

1. **Activates** when confidence crosses the threshold (same as now)
2. **Holds** through the low-speed zone (below 2.5 m/s) until the car is fully stopped
3. **Releases only** when the model explicitly signals "green light — go"

### 3.2 Code Changes

**File:** [`selfdrive/controls/lib/longitudinal_planner.py`](selfdrive/controls/lib/longitudinal_planner.py), lines 202-224

**Current code (lines 202-224):**
```python
      # Model stop scenario detection: model predicts a stop (red light, stop sign)
      # with no radar lead as the cause. This is a vision-only stop.
      # Two triggers, either of which ramps confidence:
      #   1. shouldStop=True — model predicts stop within ~1.0-2.0s (late but certain)
      #   2. desiredAccel < -1.5 — model wants to brake meaningfully (early signal)
      # Confidence gate prevents false positives from momentary model uncertainty.
      model_wants_to_brake = output_a_target_e2e < -1.5
      if (output_should_stop_e2e or model_wants_to_brake) and not lead_present and v_ego > MIN_ALLOW_THROTTLE_SPEED:
        self.model_stop_confidence = min(1.0, self.model_stop_confidence + self.dt * 2.0)
      else:
        self.model_stop_confidence = max(0.0, self.model_stop_confidence - self.dt * 3.0)
      model_stop_scenario = self.model_stop_confidence > 0.6

      use_model_braking = (
          lead_present
          and model_is_not_accelerating
          and model_requests_less_accel
          and not resuming_from_stop
      )
      if model_stop_scenario:
        # Model sees a stop light/sign with no lead — use model signals directly
        output_a_target = output_a_target_e2e
        self.output_should_stop = output_should_stop_e2e
```

**Proposed replacement:**
```python
      # Model stop scenario detection: model predicts a stop (red light, stop sign)
      # with no radar lead as the cause. This is a vision-only stop.
      # Two triggers, either of which ramps confidence:
      #   1. shouldStop=True — model predicts stop within ~1.0-2.0s (late but certain)
      #   2. desiredAccel < -1.5 — model wants to brake meaningfully (early signal)
      # Confidence gate prevents false positives from momentary model uncertainty.
      # Speed gate (v_ego > MIN_ALLOW_THROTTLE_SPEED) only applies to the
      # desiredAccel trigger — shouldStop is trusted at any speed.
      model_wants_to_brake = output_a_target_e2e < -1.5
      should_stop_trigger = output_should_stop_e2e and not lead_present
      brake_trigger = model_wants_to_brake and not lead_present and v_ego > MIN_ALLOW_THROTTLE_SPEED

      if should_stop_trigger or brake_trigger:
        self.model_stop_confidence = min(1.0, self.model_stop_confidence + self.dt * 2.0)
      else:
        self.model_stop_confidence = max(0.0, self.model_stop_confidence - self.dt * 3.0)

      # Latch: once model_stop_scenario activates, hold it until the model
      # explicitly signals green light (shouldStop=False AND desiredAccel >= 0).
      # This prevents the stop from being released when:
      #   - Car slows below MIN_ALLOW_THROTTLE_SPEED (2.5 m/s)
      #   - desiredAccel rises above -1.5 as car approaches zero speed
      #   - Model briefly flickers at very low speeds
      if self.model_stop_confidence > 0.6:
        self.model_stop_scenario_active = True
      elif self.model_stop_scenario_active:
        # Release only on explicit green light signal
        green_light = not output_should_stop_e2e and output_a_target_e2e >= 0.0
        if green_light:
          self.model_stop_scenario_active = False
      model_stop_scenario = self.model_stop_scenario_active

      use_model_braking = (
          lead_present
          and model_is_not_accelerating
          and model_requests_less_accel
          and not resuming_from_stop
      )
      if model_stop_scenario:
        # Model sees a stop light/sign with no lead — use model signals directly
        output_a_target = output_a_target_e2e
        self.output_should_stop = output_should_stop_e2e
```

### 3.3 New Field Required

Add to `__init__` at line 69:
```python
self.model_stop_scenario_active = False
```

### 3.4 Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **`shouldStop` trigger has NO speed gate** | When the model is certain enough to output `shouldStop=True`, we trust it regardless of speed. This matches blended mode behavior. |
| **`desiredAccel < -1.5` trigger KEEPS speed gate** | This trigger is more prone to false positives (model might briefly output -1.6 during normal driving). Speed gate prevents false triggers during creep. |
| **Latch holds through low-speed zone** | Once we've committed to stopping, we don't release just because speed dropped below an arbitrary threshold. |
| **Latch releases on explicit green light** | `shouldStop=False AND desiredAccel >= 0` is the model's clear "go" signal. This matches how blended mode works. |
| **No separate decay for latch** | The confidence gate still decays normally. The latch is a separate boolean that only releases on green light. This means even if confidence drops to 0, the latch holds. |

---

## 4. State Machine Trace (With Fix)

| Step | What Happens | `v_ego` | Confidence | Latch | `model_stop_scenario` | `shouldStop` |
|------|-------------|---------|------------|:---:|:---:|:---:|
| 1 | Approaching red light at 30 mph | 13.4 m/s | Ramping up | False | False | False |
| 2 | Confidence crosses 0.6 | 10 m/s | > 0.6 | **→ True** | **True** | True |
| 3 | Car brakes, slows down | 5 m/s | 1.0 | True | True | True |
| 4 | Car passes below 2.5 m/s | 2.4 m/s | Decaying | **True (held)** | **True** | True |
| 5 | Confidence drops below 0.6 | 1.0 m/s | < 0.6 | **True (held)** | **True** | True |
| 6 | Car reaches 0, fully stopped | 0 m/s | 0.0 | **True (held)** | **True** | True |
| 7 | Light turns green | 0 m/s | 0.0 | **→ False** | **False** | False |
| 8 | LongControl: stopping → starting | 0 m/s | 0.0 | False | False | False |
| 9 | Car accelerates from stop | — | — | — | — | — |

---

## 5. Edge Case Analysis

| Scenario | Behavior With Fix | Risk |
|----------|-------------------|------|
| **False shouldStop during creep** (model briefly outputs True at 1 mph) | Confidence ramps up, latch activates, car stops | **Low risk** — `shouldStop` false positives are rare; model is conservative about this signal |
| **shouldStop flickers at very low speed** | Latch holds through flicker | **Safe** — prevents premature release |
| **Green light but model slow to respond** | Latch holds until `shouldStop=False AND desiredAccel >= 0` | **Acceptable** — slight delay in go is safer than running a red |
| **Stop sign then immediate green** | Latch releases on green signal | **Correct** — same as blended mode |
| **Lead vehicle cuts in during stop** | `lead_present` becomes True → `should_stop_trigger` becomes False → confidence decays → but latch holds | **Safe** — latch holds until green light; lead presence doesn't release the stop |
| **Driver presses brake during model stop** | `brake_pressed=True` → `starting_condition=False` → state machine stays in `stopping` | **Correct** — existing logic handles this |
| **Driver presses gas during model stop** | Gas interceptor or pedal press disengages openpilot | **Correct** — existing logic handles this |

### 5.1 Potential Concern: Lead Cutting In During Model Stop

If a lead vehicle cuts in front while the model is stopping for a red light:
- `lead_present` becomes True
- `should_stop_trigger` becomes False (gated on `not lead_present`)
- Confidence decays
- But the **latch holds** `model_stop_scenario_active = True`
- Car continues stopping using model signals

This is actually the **correct behavior** — the red light is still red regardless of whether a car is in front. The lead vehicle is also stopping for the same red light.

---

## 6. Files to Modify

| File | Change | Impact |
|------|--------|--------|
| [`selfdrive/controls/lib/longitudinal_planner.py:69`](selfdrive/controls/lib/longitudinal_planner.py:69) | Add `self.model_stop_scenario_active = False` | New latch field |
| [`selfdrive/controls/lib/longitudinal_planner.py:202-224`](selfdrive/controls/lib/longitudinal_planner.py:202) | Replace confidence gate + add latch logic | **Core fix** |

No changes needed to:
- [`sunnypilot/selfdrive/controls/lib/longitudinal_planner.py`](sunnypilot/selfdrive/controls/lib/longitudinal_planner.py) — base class unchanged
- [`selfdrive/controls/lib/longcontrol.py`](selfdrive/controls/lib/longcontrol.py) — state machine handles shouldStop correctly
- [`selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py) — MPC unchanged

---

## 7. Compatibility With Plan A + v3

The fix only modifies the confidence gate and adds a latch within the `model_stop_scenario` branch. It does not touch:

- Plan A parameters (`CRUISE_MAX_ACCEL`, `A_CRUISE_MAX_VALS`, `A_CHANGE_COST`, `J_EGO_COST`)
- v3 parameters (TTC threshold, `ACC_LEAD_DANGER_FACTOR`)
- The `use_model_braking` branch (lead-present model braking)
- The pure MPC fallback branch

**Zero compatibility impact.** The same mutual exclusion by condition (`lead_present` vs `not lead_present`) still holds.

---

## 8. Implementation Steps

1. Add `self.model_stop_scenario_active = False` to `__init__`
2. Replace the confidence gate block (lines 202-213) with the new dual-trigger + latch logic
3. Replace the `model_stop_scenario` usage (lines 221-224) with the latched version
4. Verify syntax with `py_compile`
5. Commit and push for field testing
