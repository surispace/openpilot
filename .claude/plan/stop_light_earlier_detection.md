# Stop Light Earlier Detection & Smoother Braking — ACC Mode

## Honda Pilot 2019 (NIDEC Platform)

**Date:** 2026-05-05
**Status:** ✅ IMPLEMENTED — 2026-05-05
**Depends on:** Commit `7347521f` (latch-based model stop persistence)
**Based on:** `stop_light_analysis_report.md` pipeline analysis

---

## 1. The Gap: Why ACC Mode Brakes Worse Than Blended Mode

### 1.1 Two Completely Different Output Paths

The key branch is at `longitudinal_planner.py:181`:

```python
if mode == 'acc' or not self.mlsim:
    # ...confidence gate, dual-trigger, latch...
else:
    # blended + mlsim: zero gate, immediate model decel
    output_a_target = min(output_a_target_mpc, output_a_target_e2e)
    self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
```

### 1.2 Blended Mode (Experimental ON) — What Works

```python
# line 252-253: always picks whoever wants more braking, zero latency
output_a_target = min(output_a_target_mpc, output_a_target_e2e)
self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
```

- No threshold, no confidence ramp, no latch
- Model deceleration of -0.5 m/s² is used even if MPC wants 0.0
- MPC's shouldStop acts as safety net for the final halt

### 1.3 ACC Mode (Experimental OFF) — What Fails

The current flow for no-lead scenarios:

```
Model sees red light  →  desiredAccel = -0.8 (gentle initial decel)
                              ↓
                     brake_trigger? → NO (-0.8 > -1.5 threshold)
                     should_stop_trigger? → NO (model not at v<0.05 yet)
                              ↓
                     confidence = 0.0  →  output = PURE MPC
                              ↓
                     MPC maintains cruise speed (no obstacle = no reason to brake)
```

~2 seconds later:
```
Model sees red light  →  desiredAccel = -2.0, shouldStop = True
                              ↓
                     confidence ramps 0.3s → latch activates
                              ↓
                     FINALLY uses model deceleration — but 2s LATE
```

**Root cause**: The `brake_trigger` threshold (-1.5 m/s²) and confidence ramp (0.3s) create a 2+ second delay between model perception and actuated braking in ACC mode. Below -1.5, the model's gentler deceleration signals are completely ignored.

---

## 2. The Fix: Replicate Blended Mode's No-Gate Logic In ACC Mode

### 2.1 Strategy

For **no-lead scenarios** in ACC mode: use the same `min(mpc, e2e)` logic that blended mode uses. The model's deceleration is always available — if it wants to brake more than MPC, use it immediately with zero gating.

### 2.2 What Changes

Remove the confidence-ramp / dual-trigger / latch system from the no-lead path. Replace with a simple `min()`.

**Before (lines 203-250 — simplified):**
```python
# Complex dual-trigger + confidence + latch
brake_trigger = output_a_target_e2e < -1.5 and not lead_present and v_ego > 2.5
should_stop_trigger = output_should_stop_e2e and not lead_present

if should_stop_trigger or brake_trigger:
    self.model_stop_confidence = min(1.0, self.model_stop_confidence + self.dt * 2.0)
else:
    self.model_stop_confidence = max(0.0, self.model_stop_confidence - self.dt * 3.0)

# Latch with green light release
if self.model_stop_confidence > 0.6:
    self.model_stop_scenario_active = True
elif self.model_stop_scenario_active:
    if not output_should_stop_e2e and output_a_target_e2e >= 0.0:
        self.model_stop_scenario_active = False
model_stop_scenario = self.model_stop_scenario_active

# Output selection
if model_stop_scenario:
    output_a_target = output_a_target_e2e          # full model takeover
    self.output_should_stop = output_should_stop_e2e
elif use_model_braking:
    output_a_target = output_a_target_e2e          # lead-braking
    self.output_should_stop = output_should_stop_mpc
else:
    output_a_target = output_a_target_mpc          # PURE MPC ← PROBLEM
    self.output_should_stop = output_should_stop_mpc
```

**After:**
```python
# No-lead: use blended-style min() — model decel used immediately, zero gate
# With-lead: use existing use_model_braking logic (unchanged)
if lead_present:
    use_model_braking = (
        model_is_not_accelerating
        and model_requests_less_accel
        and not resuming_from_stop
    )
    if use_model_braking:
        output_a_target = output_a_target_e2e
        self.output_should_stop = output_should_stop_mpc
    else:
        output_a_target = output_a_target_mpc
        self.output_should_stop = output_should_stop_mpc
else:
    # No lead: model decel always available (same as blended mode line 252)
    output_a_target = min(output_a_target_mpc, output_a_target_e2e)
    self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
```

### 2.3 Removed Code

All of the following are deleted:
- `self.model_stop_confidence` field and ramp logic
- `self.model_stop_scenario_active` field and latch logic
- `model_stop_scenario` flag
- `brake_trigger` / `should_stop_trigger` conditions
- The entire `model stop scenario detection` block (lines 203-233)

### 2.4 Why This Is Safe

| Concern | Analysis |
|---------|----------|
| False braking from model misreading | Model decel only wins when it's MORE negative than MPC. MPC typically wants 0 acceleration at cruise. A false decel of -0.3 would win over 0.0, but that's gentle coasting — not dangerous |
| Phantom braking from curves | Model reduces speed for curves. MPC also reduces speed for turns (`limit_accel_in_turns`). The `min()` picks the lower of both — at worst, slightly more decel in curves |
| False braking from downhill | Coasting downhill: model may want 0 or negative. MPC also accounts for coasting. Both are safe |
| Lead appears during approach | Lead-present gate immediately switches to `use_model_braking` logic (proven safe) |
| Model flickers at low speed | `output_should_stop_e2e or output_should_stop_mpc` — MPC's stop detection is the safety net. Even if model flickers shouldStop, MPC's shouldStop is reliable |
| Resume from stop with lead pulling away | `resuming_from_stop` gate already blocks model braking in with-lead path |

### 2.5 Expected Behavior After Fix

```
Model sees red light  →  desiredAccel = -0.8 (gentle initial decel)
MPC sees no obstacle   →  output_a_target_mpc = 0.0 (maintain speed)
                              ↓
                     min(0.0, -0.8) = -0.8  →  car starts gentle decel
                              ↓
                     ~2 seconds saved vs current ACC mode
                              ↓
Model sees red light  →  desiredAccel = -2.0, shouldStop = True
                     min(MPC, -2.0) = -2.0  →  car continues smooth decel
                              ↓
                     MPC shouldStop kicks in  →  stopping state
                              ↓
                     Smooth stop, identical feel to blended mode
```

---

## 3. Comparison: Blended Mode vs Fixed ACC Mode

| Aspect | Blended Mode | Fixed ACC Mode |
|--------|-------------|----------------|
| No-lead accel selection | `min(mpc, e2e)` | `min(mpc, e2e)` ✓ |
| No-lead shouldStop | `e2e or mpc` | `e2e or mpc` ✓ |
| With-lead accel selection | `min(mpc, e2e)` | `use_model_braking` gated (safer, lead context) |
| With-lead shouldStop | `e2e or mpc` | MPC only (safer for lead scenarios) |
| Acceleration caps | `[ACCEL_MIN, ACCEL_MAX]` | `[ACCEL_MIN, get_max_accel(v_ego)]` (Plan B) |
| Rate limit jerking | ±0.03 (Plan B) | ±0.03 (Plan B) |

The with-lead path differs slightly — blended uses `min()` always, ACC keeps existing gated `use_model_braking`. This is intentional: with a lead present, the gated approach is safer because radar context validates the need to brake.

---

## 4. Code Changes Required

### File: `selfdrive/controls/lib/longitudinal_planner.py`

**Remove from `__init__` (lines 69-70):**
```python
self.model_stop_confidence = 0.0      # DELETE
self.model_stop_scenario_active = False  # DELETE
```

**Remove the entire model stop detection block (lines 203-233):**
All code between `# Model stop scenario detection` comment and the `use_model_braking` assignment is deleted.

**Replace output selection (lines 241-250) with:**
```python
      if lead_present:
        use_model_braking = (
            model_is_not_accelerating
            and model_requests_less_accel
            and not resuming_from_stop
        )
        if use_model_braking:
          output_a_target = output_a_target_e2e
          self.output_should_stop = output_should_stop_mpc
        else:
          output_a_target = output_a_target_mpc
          self.output_should_stop = output_should_stop_mpc
      else:
        output_a_target = min(output_a_target_mpc, output_a_target_e2e)
        self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
```

**Net diff**: ~35 lines removed (confidence/latch system), ~12 lines added (simplified output selection). Same behavior as blended mode for no-lead scenarios.

### Files NOT changed:
- `longitudinal_mpc_lib/long_mpc.py` — no mpc changes
- `modeld/modeld.py` — no model changes
- `drive_helpers.py` — no helper changes

---

## 5. What This Does NOT Affect

| System | Impact |
|--------|--------|
| ACC smoother acceleration (Plan B) | **None** — `A_CRUISE_MAX_VALS`, `CRUISE_MAX_ACCEL`, accel clip rate all unchanged |
| Earlier braking v3 | **None** — TTC threshold, LEAD_DANGER_FACTOR unchanged. With-lead path unchanged |
| Blended mode (experimental ON) | **None** — code path at line 251-253 unchanged |
| DEC mode switching | **None** |
| Honda Pilot parameters | **None** |

---

## 6. Safety Verification

### 6.1 Test Scenarios

| # | Scenario | Expected Behavior |
|---|----------|-------------------|
| 1 | No lead, red light ahead at 50 mph | Smooth decel from ~150m, comfortable stop |
| 2 | No lead, empty road at cruise | MPC maintains speed, model may request slight decel → gentle coasting |
| 3 | Lead present, red light ahead | `use_model_braking` gates model decel (unchanged) — safe lead-following |
| 4 | Resume from stop, lead pulling away | `resuming_from_stop` gate prevents model override (unchanged) |
| 5 | Curve at speed, no lead | MPC reduces for turn; model may also reduce — `min()` picks lowest |
| 6 | Downhill, no lead | MPC accounts for coasting; model may add slight decel — safe |
| 7 | Model flickers/false positive | `min()` only activates if model wants MORE braking. False -0.3 decel vs MPC 0.0 = gentle coast, not dangerous |
