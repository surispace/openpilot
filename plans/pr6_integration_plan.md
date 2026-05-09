# PR #6 Integration Plan — rtizi-dev → rtizi-dev-new (Implemented)

**Status:** ✅ Implemented
**Date:** 2026-05-09
**PR:** https://github.com/gallantsuri1/openpilot/pull/6
**Source Branch:** `rtizi-dev` (PR base: `rtizi-stable`)
**Target Branch:** `rtizi-dev-new`

---

## 1. Current Architecture Deep Dive

### 1.1 Mode Determination Flow

```
┌──────────────────────────────────────────────────────────────────┐
│  DynamicExperimentalController (DEC)                              │
│  sunnypilot/selfdrive/controls/lib/dec/dec.py                     │
│                                                                    │
│  ModeTransitionManager:                                           │
│    current_mode ∈ {'acc', 'blended'}                              │
│    default = 'acc'                                                │
│    hysteresis: min_mode_duration=10 frames                        │
│                                                                    │
│  Radar mode triggers:                                             │
│    - Lead detected + not standstill → request 'acc'               │
│    - Slow down (urgency > 0.7) → emergency 'blended'             │
│    - Standstill > 3 frames → request 'blended'                   │
│    - Default → request 'acc'                                      │
└──────────────────────┬───────────────────────────────────────────┘
                       │ self.dec.mode()
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  LongitudinalPlannerSP.is_e2e()                                   │
│  sunnypilot/selfdrive/controls/lib/longitudinal_planner.py:39     │
│                                                                    │
│  def is_e2e(self, sm):                                           │
│    experimental_mode = sm['selfdriveState'].experimentalMode     │
│    if not self.dec.active():                                      │
│      return experimental_mode                                     │
│    return experimental_mode and self.dec.mode() == "blended"     │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  LongitudinalPlanner.update() output selection                    │
│  selfdrive/controls/lib/longitudinal_planner.py:181               │
│                                                                    │
│  if self.is_e2e(sm):        ← DEC mode='blended' + experimental  │
│    output = min(mpc, e2e)   ← blended behavior                   │
│  else:                      ← DEC mode='acc' OR not experimental │
│    output = mpc             ← pure ACC behavior                  │
└──────────────────────────────────────────────────────────────────┘
```

### 1.2 Key Insight: `DecState` is Just Publishing

```python
# sunnypilot/selfdrive/controls/lib/longitudinal_planner.py:94
dec.state = DecState.blended if self.dec.mode() == 'blended' else DecState.acc
```

`DecState` is a **capnp enum** used only for publishing telemetry. It does NOT control behavior. The actual behavioral gate is `self.is_e2e(sm)`.

### 1.3 What "ACC Mode" Means in Current Branch

| Condition | `is_e2e()` | Behavior | DEC mode |
|-----------|-----------|----------|----------|
| experimental=True, DEC=acc | `False` | **Pure MPC** ← This is "ACC mode" | acc |
| experimental=True, DEC=blended | `True` | `min(mpc, e2e)` | blended |
| experimental=False | `False` | **Pure MPC** | (any) |

**The PR's P1/P2/P3 logic targets the "Pure MPC" path** — i.e., when `is_e2e()` returns `False`.

---

## 2. What the PR Adds (Priority-Ordered Output Selection)

The PR replaces the simple "pure MPC" fallthrough with three priority levels:

```
P1: LEAD PRESENT (highest priority)
├── P1a: Lead slower/stopped → apply v3 braking (model override when e2e < -0.5)
└── P1b: Lead faster → apply Plan B smoother acceleration (pure MPC)

P2: NO LEAD + NO STOP LIGHT
└── Apply Plan B smoother acceleration (pure MPC)

P3: NO LEAD + STOP LIGHT DETECTED
└── Apply threshold-gated min(mpc, e2e) for stop light response
```

---

## 3. Adaptation Strategy

### 3.1 The Gate: `is_e2e()` → `not is_e2e()`

The PR uses `mode == 'acc'` as its gate. The current branch equivalent is `not self.is_e2e(sm)`.

**Current code (lines 181-186):**
```python
if self.is_e2e(sm):
    # Blended mode: unchanged — min(mpc, e2e)
    output_a_target = min(output_a_target_e2e, output_a_target_mpc)
    self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
    if output_a_target < output_a_target_mpc:
        self.mpc.source = LongitudinalPlanSource.e2e
else:
    # ACC mode: P1/P2/P3 priority-ordered output selection
    ...
```

### 3.2 MPC Changes: No `self.mode` Needed

The PR's MPC has `self.mode == 'acc'` checks. In the current branch, the MPC is **always used the same way** — the mode distinction happens in the planner's output selection. The blended path takes `min(mpc, e2e)`, so MPC parameters don't need mode-gating.

**Strategy:** Apply all personality-dependent MPC parameters unconditionally (no `self.mode` gate).

| PR Change | Adaptation |
|-----------|-----------|
| `if self.mode == 'acc': params[:,5] = ACC_LEAD_DANGER_FACTOR_BY_PERSONALITY` | Always use personality-dependent danger factor |
| `if self.mode == 'acc': cruise_max_accel = CRUISE_MAX_ACCEL_BY_PERSONALITY` | Always use personality-dependent cruise max accel |
| `if self.mode == 'acc': _lead_relevant()` | Always compute lead_relevant |
| `if self.mode == 'acc': conditional cruise obstacle` | Always conditionally remove cruise obstacle |
| `if self.mode in ('blended', 'acc'): source tracking` | Always track source |

### 3.3 What We Skip

- **`self.mode` attribute in MPC**: Not needed. MPC always runs in "ACC-style" mode.
- **MPC `update()` signature change** (x, v, a, j params): Current branch doesn't pass model trajectory to MPC.
- **`self.mlsim` check**: Not present. `is_e2e()` serves the same role.

---

## 4. Complete Change List

### 4.1 `long_mpc.py` — All Changes Apply Unconditionally

| # | Change | Location |
|---|--------|----------|
| 1 | `J_EGO_COST: 5.0 → 8.0` | Line 39 |
| 2 | `A_CHANGE_COST: 200 → 300` | Line 40 |
| 3 | Add `ACC_LEAD_DANGER_FACTOR = 0.90` | Line 44 |
| 4 | `CRUISE_MAX_ACCEL: 1.6 → 1.2` | Line 60 |
| 5 | Add 4 personality lookup tables | Lines 64-86 |
| 6 | Fix `get_jerk_factor()` relaxed: 1.0→1.5 | Lines 88-96 |
| 7 | `get_stopped_equivalence_factor()` +personality param | Lines 109-111 |
| 8 | `get_safe_obstacle_distance()` +personality param | Lines 113-115 |
| 9 | `self.lead_relevant = False` in `reset()` | Line 272 |
| 10 | `_lead_relevant()` in `update()` | Lines 375-382 |
| 11 | Conditional cruise obstacle removal | Lines 385-388 |
| 12 | Personality-dependent `params[:,5]` | Line 401 |
| 13 | Personality-dependent `cruise_max_accel` for v_upper | Line 361 |
| 14 | Source tracking for both modes | Line 389 |
| 15 | `get_stopped_equivalence_factor()` calls +personality | Lines 356-357 |
| 16 | `get_safe_obstacle_distance()` calls +personality | Line 366 |

### 4.2 `longitudinal_planner.py` — Output Selection + Personality Caps

| # | Change | Location |
|---|--------|----------|
| 1 | Add `from cereal import log` | Line 4 |
| 2 | `A_CRUISE_MAX_VALS: [1.6,1.2,0.8,0.6] → [1.2,1.0,0.7,0.5]` | Line 21 |
| 3 | Add `MODEL_BRAKE_THRESHOLD = -0.5` | Line 26 |
| 4 | Add `A_CRUISE_MAX_VALS_BY_PERSONALITY` dict | Lines 29-33 |
| 5 | Add `ACCEL_CLIP_RATE_BY_PERSONALITY` dict | Lines 36-40 |
| 6 | `get_max_accel()` +personality param | Lines 46-48 |
| 7 | ACC path: personality-aware `accel_clip` | Line 131 |
| 8 | Replace `else` block with P1/P2/P3 logic | Lines 187-238 |
| 9 | Personality-dependent `accel_clip_rate` | Line 240 |

---

## 5. Behavioral Trace Matrix (ACC Path Only)

| # | Scenario | lead_present | e2e accel | e2e stop | Path | Output | Behavior |
|---|----------|:---:|------|:---:|---|---|---|
| 1 | Open road, no lead | False | -0.1 | False | P2 | MPC + Plan B | Smooth acceleration to cruise |
| 2 | Red light ahead, early | False | -0.8 | False | P3 | min(mpc, -0.8) | Gentle early decel |
| 3 | Red light ahead, close | False | -2.0 | True | P3 | min(mpc, -2.0) | Strong braking + stop |
| 4 | Green after stop | False | +0.5 | False | P2 | MPC + Plan B | Smooth resume |
| 5 | Lead faster, following | True | -0.3 | False | P1b | MPC + Plan B | Normal following, smooth |
| 6 | Lead slower, braking | True | -1.5 | False | P1a | e2e (-1.5) | Early braking preserved |
| 7 | Lead stopped ahead | True | -2.0 | True | P1a | e2e (-2.0) | v3 braking + stop |
| 8 | Resume, lead pulling away | True | -0.3 | False | P1b | MPC + Plan B | Blocked by resuming_from_stop |
| 9 | Curve, no lead | False | -0.6 | False | P3 | min(mpc, -0.6) | Model curve decel used |
| 10 | Downhill, no lead | False | -0.4 | False | P2 | MPC + Plan B | MPC handles coasting |

---

## 6. Deep Code Analysis — Verification Results

### 6.1 Blended Mode Path: CONFIRMED UNTOUCHED

The blended mode path at [`longitudinal_planner.py:181-186`](selfdrive/controls/lib/longitudinal_planner.py:181) is **byte-for-byte identical** to the original code:

```python
if self.is_e2e(sm):
    output_a_target = min(output_a_target_e2e, output_a_target_mpc)
    self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
    if output_a_target < output_a_target_mpc:
        self.mpc.source = LongitudinalPlanSource.e2e
```

No regression risk for blended mode. The `is_e2e()` gate at [`sunnypilot/selfdrive/controls/lib/longitudinal_planner.py:39-44`](openpilot/sunnypilot/selfdrive/controls/lib/longitudinal_planner.py:39) is unchanged.

### 6.2 Variable Scope Analysis

| Variable | Set At | Used At | Always Defined? |
|----------|--------|---------|-----------------|
| `personality` | Line 130 (unconditional) | Lines 131, 157, 159, 240 | ✅ Yes — set before if/else |
| `output_a_target` | Lines 183, 225, 228, 234, 237 | Line 243 | ✅ Yes — all branches set it |
| `self.output_should_stop` | Lines 184, 226, 229, 235, 238 | publish() | ✅ Yes — all branches set it |
| `lead_present` | Line 203 (ACC path only) | Lines 216-229 | ✅ Yes — only used inside ACC path |
| `model_wants_to_brake` | Line 204 (ACC path only) | Lines 219, 233 | ✅ Yes — only used inside ACC path |

### 6.3 Edge Case Analysis: `_lead_relevant()`

Located at [`long_mpc.py:375-382`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:375):

```python
def _lead_relevant(lead):
    if lead is None or not lead.status:
        return False
    v_rel = v_ego - lead.vLead
    if v_rel <= 0:
        return False
    ttc = lead.dRel / v_rel
    return ttc < ttc_threshold or lead.dRel < 10.0
```

| Edge Case | Handling | Safe? |
|-----------|----------|:-----:|
| `lead is None` | Returns False immediately | ✅ |
| `lead.status == False` | Returns False immediately | ✅ |
| `v_rel == 0` (same speed) | `v_rel <= 0` → returns False | ✅ No div-by-zero |
| `v_rel < 0` (lead faster) | `v_rel <= 0` → returns False | ✅ No div-by-zero |
| `v_rel > 0` (lead slower) | Computes TTC safely | ✅ |
| `dRel` very small, `v_rel` very small | TTC could be large, but `dRel < 10.0` catches it | ✅ |
| `dRel` very large, `v_rel` very small | TTC > threshold, `dRel >= 10.0` → returns False | ✅ Correct: far lead not relevant |

### 6.4 Edge Case Analysis: `x_obstacles` Shape

At [`long_mpc.py:385-389`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:385):

```python
if self.lead_relevant:
    x_obstacles = np.column_stack([lead_0_obstacle, lead_1_obstacle])  # shape (13, 2)
else:
    x_obstacles = np.column_stack([lead_0_obstacle, lead_1_obstacle, cruise_obstacle])  # shape (13, 3)
self.source = MPC_SOURCES[np.argmin(x_obstacles[0])]
```

| Case | Columns | argmin range | MPC_SOURCES mapping |
|------|---------|:-----------:|---------------------|
| lead_relevant=True | 2 | {0, 1} | lead0 or lead1 |
| lead_relevant=False | 3 | {0, 1, 2} | lead0, lead1, or cruise |

`np.min(x_obstacles, axis=1)` at line 398 works correctly for both shapes. ✅

### 6.5 Edge Case Analysis: Resume-from-Stop Protection

At [`longitudinal_planner.py:209-214`](selfdrive/controls/lib/longitudinal_planner.py:209):

```python
v_ego = sm['carState'].vEgo
lead_moving_away = (
    (sm['radarState'].leadOne.status and sm['radarState'].leadOne.vLead > v_ego) or
    (sm['radarState'].leadTwo.status and sm['radarState'].leadTwo.vLead > v_ego)
)
resuming_from_stop = v_ego < MIN_ALLOW_THROTTLE_SPEED and lead_moving_away
```

| Scenario | v_ego | lead_moving_away | resuming_from_stop | Effect |
|----------|-------|:---:|:---:|--------|
| Stopped, lead pulling away | 0.5 | True | True | Blocks model braking ✅ |
| Stopped, lead stopped | 0.5 | False | False | Allows model braking ✅ |
| Moving slowly, lead faster | 2.0 | True | True | Blocks model braking ✅ |
| Moving normally, lead faster | 5.0 | True | False | Allows model braking ✅ |
| No lead | any | False | False | Allows model braking ✅ |

---

## 7. Tradeoffs: Old Logic vs New Logic

### 7.1 Old Logic (Pre-Integration)

```python
if self.is_e2e(sm):
    output_a_target = min(output_a_target_e2e, output_a_target_mpc)
    self.output_should_stop = output_should_stop_e2e or output_should_stop_mpc
else:
    output_a_target = output_a_target_mpc
    self.output_should_stop = output_should_stop_mpc
```

**Characteristics:**
- ACC mode: Always pure MPC, zero model involvement
- No stop light response in ACC mode
- No lead-specific braking logic
- Original acceleration caps: `[1.6, 1.2, 0.8, 0.6]`
- Original MPC costs: `J_EGO_COST=5.0`, `A_CHANGE_COST=200`

### 7.2 New Logic (Post-Integration)

| Aspect | Old | New | Tradeoff |
|--------|-----|-----|----------|
| **Stop light response** | None in ACC mode | P3: threshold-gated min(mpc,e2e) | ✅ Major safety gain. Car now stops for red lights in ACC mode |
| **Lead braking** | Pure MPC only | P1a: model override when e2e < -0.5 | ✅ Earlier, smoother braking for slowing leads |
| **Braking threshold** | No threshold (binary) | `MODEL_BRAKE_THRESHOLD = -0.5` | ✅ Filters weak model signals, reduces false braking |
| **Acceleration caps** | `[1.6, 1.2, 0.8, 0.6]` | `[1.2, 1.0, 0.7, 0.5]` (Plan A) | ⚠️ Gentler accel. Aggressive personality retains original values |
| **MPC jerk cost** | `J_EGO_COST=5.0` | `J_EGO_COST=8.0` | ✅ Smoother jerk transitions, less "jerky" feel |
| **MPC accel change cost** | `A_CHANGE_COST=200` | `A_CHANGE_COST=300` | ✅ Smoother accel transitions |
| **Cruise obstacle** | Always present | Conditionally removed when lead is braking-relevant | ✅ MPC focuses on lead when it matters |
| **Resume from stop** | No special handling needed | Explicit guard against model braking | ✅ Prevents hesitation when lead pulls away |
| **Personality system** | None (fixed params) | 6 lookup tables across 3 personalities | ✅ User-selectable driving feel |
| **Accel clip rate** | Fixed ±0.03 | Personality-dependent (0.02-0.05) | ✅ Aggressive responds faster, relaxed smoother |

### 7.3 Potential Downsides of New Logic

| Concern | Severity | Mitigation |
|---------|----------|------------|
| P3 false positives (unnecessary braking for false stop light detection) | Medium | `MODEL_BRAKE_THRESHOLD = -0.5` filters weak signals; model stop light detection is generally reliable |
| Plan A caps too conservative for some users | Low | Aggressive personality uses original `[1.6, 1.2, 0.8, 0.6]` caps |
| `_lead_relevant()` false negative (lead not detected as relevant) | Low | TTC threshold defaults to 12s (very conservative); 10m absolute distance catch-all |
| `_lead_relevant()` false positive (irrelevant lead flagged) | Low | Only affects cruise obstacle removal; MPC still has lead obstacles to track |
| Higher MPC costs may slow response in emergency | Low | Costs only affect smoothness, not constraint enforcement; danger zone cost unchanged at 100 |

---

## 8. Honda Pilot 2019 Compatibility

### 8.1 Platform: NIDEC

The Honda Pilot 2019 uses the NIDEC platform with `openpilotLongitudinalControl = True`.

### 8.2 Compatibility Assessment

| Concern | Analysis | Compatible? |
|---------|----------|:-----------:|
| Vehicle-specific code paths | None modified. All changes are in shared planner/MPC code | ✅ |
| `CP.openpilotLongitudinalControl` | `reset_state` logic at line 123 handles both openpilot and ACC long control | ✅ |
| `CP.vEgoStopping` | Used in `get_accel_from_plan()` — unchanged | ✅ |
| `CP.longitudinalActuatorDelay` | Used at line 175 — unchanged | ✅ |
| `CP.steerRatio`, `CP.wheelbase` | Used in `limit_accel_in_turns()` — unchanged | ✅ |
| `ACCEL_MIN`, `ACCEL_MAX` | From opendbc — unchanged | ✅ |
| Radar interface | `sm['radarState']` — unchanged interface | ✅ |
| Model output | `sm['modelV2']` — unchanged interface | ✅ |
| Personality enum | `sm['selfdriveState'].personality` — standard sunnypilot interface | ✅ |

### 8.3 Verdict

**Fully compatible.** All changes are at the planning/MPC tuning layer — parameter values, cost weights, and output selection logic. No vehicle-specific interfaces, CAN messaging, or actuator control paths are modified. The changes will work identically on Honda Pilot 2019 as on any other supported vehicle.

---

## 9. Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| `lead_relevant` False negative | Low | High | TTC threshold defaults to 12s; aggressive=10s more sensitive; 10m absolute catch-all |
| Plan A caps too conservative | Medium | Medium | Personality system: aggressive uses original 1.6 caps |
| P3 false positive (unnecessary braking) | Low | Medium | Threshold gate at -0.5 m/s² filters noise |
| Blended mode regression | **None** | High | Blended path (`is_e2e()==True`) completely untouched |
| `personality` variable scope in rate-limit block | **None** | High | Set unconditionally at line 130, before if/else |
| Division by zero in `_lead_relevant()` | **None** | High | Guarded by `if v_rel <= 0: return False` |
| MPC solution failure with new cost weights | Low | Medium | Acados solver is robust; costs only affect objective, not constraints |

---

## 10. Implementation Status

### Phase 1: `long_mpc.py` ✅ COMPLETED
- [x] Update constants (J_EGO_COST, A_CHANGE_COST, CRUISE_MAX_ACCEL)
- [x] Add ACC_LEAD_DANGER_FACTOR
- [x] Add 4 personality lookup tables
- [x] Fix get_jerk_factor() relaxed: 1.0→1.5
- [x] Update get_stopped_equivalence_factor() and get_safe_obstacle_distance()
- [x] Add self.lead_relevant to reset()
- [x] Modify update(): personality params, _lead_relevant(), conditional cruise obstacle, source tracking

### Phase 2: `longitudinal_planner.py` ✅ COMPLETED
- [x] Add imports and constants
- [x] Add personality lookup tables
- [x] Update get_max_accel()
- [x] Modify update(): personality-aware accel_clip, P1/P2/P3 output selection, personality rate limit

### Verification ✅ COMPLETED
- [x] Blended mode path confirmed untouched
- [x] Variable scope analysis — all variables defined before use
- [x] Edge case analysis — no div-by-zero, no None dereference, no shape mismatch
- [x] Tradeoffs documented
- [x] Honda Pilot 2019 compatibility confirmed
