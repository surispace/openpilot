# Stop Light Threshold Gate Fix — Prevent Model Conservatism From Blocking Acceleration

## Honda Pilot 2019 (NIDEC Platform)

**Date:** 2026-05-05
**Status:** 📋 SUPERSEDED by `comprehensive_longitudinal_fix.md`
**Fixes:** Slow acceleration after `stop_light_earlier_detection.md` changes
**Based on:** Root cause analysis of `min(mpc, e2e)` braking bias

---

## 1. Problem

After implementing `stop_light_earlier_detection.md`, the car exhibits two issues:

1. **No lead, open road**: Car won't accelerate to set speed — gently decelerates or coasts instead
2. **Lead present**: Car slows down excessively, more than necessary for safe following

### Root Cause

The `min(mpc, e2e)` logic in the no-lead path and the `model_is_not_accelerating <= 0.0` gate in the with-lead path both let the model's **conservative open-road policy** override MPC's acceleration requests. The driving model frequently outputs slightly negative `desiredAcceleration` (-0.1 to -0.3 m/s²) even on clear roads, while MPC correctly requests positive acceleration to reach/maintain cruise speed.

```
No-lead trace:
  MPC:  +1.0 m/s²  (chasing cruise obstacle, below set speed)
  E2E:  -0.1 m/s²  (model's conservative baseline)
  min(+1.0, -0.1) = -0.1  →  car decelerates instead of accelerating!

With-lead trace:
  MPC:  +0.5 m/s²  (radar-informed safe following)
  E2E:  -0.3 m/s²  (model being conservative about lead)
  model_is_not_accelerating = True   (-0.3 <= 0.0)
  model_requests_less_accel  = True   (-0.3 < +0.5)
  → use_model_braking = True → car slows unnecessarily
```

The Plan B acceleration smoothing parameters (`A_CRUISE_MAX_VALS`, `CRUISE_MAX_ACCEL`, `accel_clip` rate limit) never get a chance to work because the model's value is selected **before** those caps are applied.

---

## 2. Fix: Threshold Gate

### Strategy

Add a **-0.5 m/s² threshold** on `output_a_target_e2e` — only let the model override MPC when it shows **clear braking intent** (deceleration stronger than -0.5 m/s²), not just conservative coasting. The `shouldStop` signal from the model is always respected regardless of threshold.

### Why -0.5 m/s²?

| Model output | Interpretation | Should override MPC? |
|---|---|---|
| +0.5 m/s² | Model wants to accelerate | No — let MPC handle it |
| 0.0 to -0.3 m/s² | Conservative coasting / uncertainty | **No** — this is the problem range |
| -0.5 to -1.5 m/s² | Gentle braking intent (early red light detection) | **Yes** — this is the desired early detection |
| -1.5 to -3.0 m/s² | Clear braking (red light, obstacle) | **Yes** — strong braking needed |

The -0.5 threshold cleanly separates "model is just being conservative" from "model actually wants to slow down."

---

## 3. Code Changes

### File: [`selfdrive/controls/lib/longitudinal_planner.py`](selfdrive/controls/lib/longitudinal_planner.py)

#### 3.1 Add threshold constant (after line 25)

```python
MIN_ALLOW_THROTTLE_SPEED = 2.5
MODEL_BRAKE_THRESHOLD = -0.5  # m/s², model must want at least this much decel to override MPC
```

#### 3.2 Fix no-lead path (lines 215-217)

**Current:**
```python
      else:
        output_a_target = min(output_a_target_mpc, output_a_target_e2e)
        self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
```

**Replace with:**
```python
      else:
        # No lead: model decel only when model shows clear braking intent
        # (stronger than -0.5 m/s²) or explicitly signals stop.
        # Prevents model conservatism from blocking normal acceleration.
        model_wants_to_brake = output_a_target_e2e < MODEL_BRAKE_THRESHOLD
        if model_wants_to_brake or output_should_stop_e2e:
          output_a_target = min(output_a_target_mpc, output_a_target_e2e)
          self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
        else:
          output_a_target = output_a_target_mpc
          self.output_should_stop = output_should_stop_mpc
```

#### 3.3 Fix with-lead path (lines 203-214)

**Current:**
```python
      if lead_present:
        use_model_braking = (
            model_is_not_accelerating
            and model_requests_less_accel
            and not resuming_from_stop
        )
```

**Replace with:**
```python
      if lead_present:
        model_wants_to_brake = output_a_target_e2e < MODEL_BRAKE_THRESHOLD
        use_model_braking = (
            model_wants_to_brake
            and model_requests_less_accel
            and not resuming_from_stop
        )
```

#### 3.4 Remove now-unused variable (line 188)

`model_is_not_accelerating` is no longer used in the with-lead path. It can be removed or kept (harmless). Recommend removing for cleanliness:

```python
      lead_present = self.mpc.lead_relevant
      model_requests_less_accel = output_a_target_e2e < output_a_target_mpc
```

---

## 4. Behavioral Impact

### 4.1 No Lead, Open Road (Fixed)

```
MPC:  +1.0 m/s²  (below cruise speed)
E2E:  -0.1 m/s²  (conservative baseline)
model_wants_to_brake = False  (-0.1 >= -0.5)
shouldStop = False
→ output_a_target = +1.0 m/s²  →  Plan B smoothing applies → car accelerates normally
```

### 4.2 No Lead, Red Light Ahead (Preserved)

```
MPC:  +0.5 m/s²  (no obstacle, maintaining)
E2E:  -0.8 m/s²  (early red light detection)
model_wants_to_brake = True  (-0.8 < -0.5)
→ output_a_target = min(+0.5, -0.8) = -0.8  →  gentle early decel preserved
```

### 4.3 No Lead, Red Light — Strong Braking (Preserved)

```
MPC:  +0.2 m/s²
E2E:  -2.0 m/s², shouldStop = True
model_wants_to_brake = True  (-2.0 < -0.5)
→ output_a_target = min(+0.2, -2.0) = -2.0
→ output_should_stop = True or mpc  →  stopping state engages
```

### 4.4 No Lead, Green Light After Stop (Preserved)

```
MPC:  +1.0 m/s²  (resume cruise)
E2E:  +0.5 m/s², shouldStop = False
model_wants_to_brake = False  (+0.5 >= -0.5)
→ output_a_target = +1.0 m/s²  →  car accelerates from stop
```

### 4.5 Lead Present, Normal Following (Fixed)

```
MPC:  +0.5 m/s²  (radar-informed following)
E2E:  -0.3 m/s²  (conservative about lead)
model_wants_to_brake = False  (-0.3 >= -0.5)
→ use_model_braking = False
→ output_a_target = +0.5 m/s²  →  normal lead following
```

### 4.6 Lead Present, Lead Braking (Preserved)

```
MPC:  -0.2 m/s²  (MPC reacting to lead slowing)
E2E:  -1.5 m/s²  (model sees lead braking hard)
model_wants_to_brake = True  (-1.5 < -0.5)
model_requests_less_accel = True  (-1.5 < -0.2)
→ use_model_braking = True
→ output_a_target = -1.5 m/s²  →  earlier braking preserved
```

---

## 5. Edge Case Analysis

| Scenario | Model Output | Threshold Result | Behavior |
|---|---|---|---|
| Model flickers -0.4 → -0.6 → -0.4 | Crosses threshold | One cycle of model braking | Acceptable — single cycle at 20Hz is imperceptible |
| Model outputs -0.5 exactly | -0.5 | `False` (-0.5 is not < -0.5) | MPC used — borderline case, conservative choice is safe |
| shouldStop=True but accel=-0.3 | shouldStop triggers | Model used (shouldStop gate) | Correct — stop signal always respected |
| Downhill, model wants -0.4 coast | -0.4 | `False` | MPC used — MPC also accounts for coasting via pitch |
| Curve, model wants -0.6 | -0.6 | `True` | Model used — model reduces for curves, MPC also reduces via `limit_accel_in_turns`, `min()` picks lower |

---

## 6. What This Does NOT Affect

| System | Impact |
|---|---|
| Blended mode (experimental ON) | **None** — code path at lines 218-220 unchanged |
| Plan B acceleration smoothing | **Restored** — MPC output now reaches `A_CRUISE_MAX_VALS` caps and `accel_clip` rate limit |
| DEC mode switching | **None** |
| `resuming_from_stop` gate | **Unchanged** — still blocks model braking when lead pulls away |
| `shouldStop` from MPC | **Unchanged** — MPC's stop detection remains the safety net |
| Honda Pilot parameters | **None** |

---

## 7. Implementation Steps

1. Add `MODEL_BRAKE_THRESHOLD = -0.5` constant after line 25 in [`longitudinal_planner.py`](selfdrive/controls/lib/longitudinal_planner.py:25)
2. Remove `model_is_not_accelerating` variable from line 188
3. Replace `model_is_not_accelerating` with `model_wants_to_brake` in the `use_model_braking` condition (line 204-205)
4. Replace the no-lead `else` block (lines 215-217) with the threshold-gated version
5. Test scenarios from §4
