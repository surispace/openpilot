# Plan: Smoother ACC Acceleration (No Lead / Lead Faster Than Ego)

**Branch:** `rtizi-dev`
**Date:** 2026-05-06
**Status:** ✅ IMPLEMENTED — Plan A applied. See commits below.

---

## 1. Problem

ACC acceleration feels too aggressive when there is no lead or the lead is going faster than ego. The car "lurches" or accelerates with more punch than desired, especially from a stop or when resuming speed after a lead clears.

---

## 2. Files and Parameters Inspected

| File | Line(s) | Parameter | Role |
|------|---------|-----------|------|
| [`selfdrive/controls/lib/longitudinal_planner.py`](selfdrive/controls/lib/longitudinal_planner.py:21-22) | 21-22 | `A_CRUISE_MAX_VALS`, `A_CRUISE_MAX_BP` | Hard acceleration caps per speed |
| [`selfdrive/controls/lib/longitudinal_planner.py`](selfdrive/controls/lib/longitudinal_planner.py:65) | 65 | `FirstOrderFilter(init_v, 2.0, dt)` | Desired velocity smoothing (2s time constant) |
| [`selfdrive/controls/lib/longitudinal_planner.py`](selfdrive/controls/lib/longitudinal_planner.py:126-127) | 126-127 | `accel_clip = [ACCEL_MIN, get_max_accel(v_ego)]` | Per-cycle acceleration bounds |
| [`selfdrive/controls/lib/longitudinal_planner.py`](selfdrive/controls/lib/longitudinal_planner.py:216-217) | 216-217 | `accel_clip ±0.05` rate limit | Final jerk smoothing (1.0 m/s³) |
| [`selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:34-39) | 34-39 | `X_EGO_OBSTACLE_COST`, `A_CHANGE_COST`, `J_EGO_COST` | MPC cost weights |
| [`selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:59-60) | 59-60 | `CRUISE_MIN_ACCEL`, `CRUISE_MAX_ACCEL` | Cruise obstacle velocity bounds |
| [`selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:283) | 283 | `cost_weights` (ACC mode) | MPC cost function weights |
| [`selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:355-360) | 355-360 | `v_lower`, `v_upper`, `v_cruise_clipped` | Cruise obstacle velocity clipping |

---

## 3. How ACC Acceleration Works (No Lead)

```
                    ┌─────────────────────────────────┐
                    │     A_CRUISE_MAX_VALS (cap)      │
                    │  [1.6, 1.2, 0.8, 0.6] m/s²     │
                    │  at [0, 10, 25, 40] m/s         │
                    └──────────────┬──────────────────┘
                                   │ clips final output
                                   ▼
┌──────────────┐    ┌──────────────────────┐    ┌──────────────┐
│ CRUISE_MAX   │───▶│  MPC Solver          │───▶│ accel_clip   │
│ ACCEL = 1.6  │    │  cost_weights:       │    │ rate limit   │
│ (×1.05=1.68) │    │  A_CHANGE_COST=200   │    │ ±0.05/cycle  │
│              │    │  J_EGO_COST=5.0      │    │ (=1.0 m/s³)  │
└──────────────┘    └──────────────────────┘    └──────────────┘
```

The cruise obstacle is a virtual "wall" positioned at the user-set cruise speed. Its velocity is clipped so it can "pull away" from ego at up to `CRUISE_MAX_ACCEL × 1.05 = 1.68 m/s²`. The MPC then plans a trajectory to chase this obstacle, subject to cost penalties and hard caps.

---

## 4. Current Parameter Values

### 4.1 Max Acceleration Caps — [`longitudinal_planner.py:21-22`](selfdrive/controls/lib/longitudinal_planner.py:21)

| Speed (m/s) | Speed (mph) | Max Accel |
|-------------|-------------|-----------|
| 0 m/s | 0 mph | **1.6 m/s²** |
| 10 m/s | 22 mph | **1.2 m/s²** |
| 25 m/s | 56 mph | **0.8 m/s²** |
| 40 m/s | 89 mph | **0.6 m/s²** |

### 4.2 Cruise Obstacle Velocity Bounds — [`long_mpc.py:59-60`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:59)

| Parameter | Value | Effective (×1.05) |
|-----------|-------|-------------------|
| `CRUISE_MIN_ACCEL` | −1.2 m/s² | −1.26 m/s² |
| `CRUISE_MAX_ACCEL` | **1.6 m/s²** | **1.68 m/s²** |

### 4.3 MPC Cost Weights (ACC mode) — [`long_mpc.py:283`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:283)

| Cost | Weight | What it penalizes |
|------|--------|-------------------|
| `X_EGO_OBSTACLE_COST` | **3.0** | Distance to obstacle (cruise wall) |
| `X_EGO_COST` | 0 | Position tracking error |
| `V_EGO_COST` | 0 | Velocity tracking error |
| `A_EGO_COST` | **0** | Acceleration magnitude — **NO PENALTY** |
| `A_CHANGE_COST` | **200** × jerk_factor | Change in acceleration (Δa between steps) |
| `J_EGO_COST` | **5.0** × jerk_factor | Jerk magnitude |

### 4.4 Output Rate Limiting — [`longitudinal_planner.py:216-217`](selfdrive/controls/lib/longitudinal_planner.py:216)

```
accel_clip[idx] = clip(accel_clip[idx], prev - 0.05, prev + 0.05)
```
At 20Hz: max jerk = **1.0 m/s³**

### 4.5 Desired Velocity Filter — [`longitudinal_planner.py:65`](selfdrive/controls/lib/longitudinal_planner.py:65)

```
FirstOrderFilter(init_v, 2.0, dt)  // time constant = 2.0s
```

---

## 5. Root Cause: Why Acceleration Feels Aggressive

1. **`CRUISE_MAX_ACCEL = 1.6`** — the cruise obstacle pulls away at 1.68 m/s², forcing the MPC to chase aggressively
2. **`A_EGO_COST = 0`** — no penalty on sustained high acceleration; MPC has no incentive to accelerate gently
3. **`A_CHANGE_COST = 200`** — moderate jerk penalty; allows fairly quick acceleration ramp-up
4. **`A_CRUISE_MAX_VALS[0] = 1.6`** — at low speeds, the hard cap allows very punchy acceleration from stop

The MPC's cost function essentially says: "Get to the cruise obstacle as fast as possible, just don't jerk too hard doing it."

---

## 6. Proposed Plans

### Plan A: Conservative Smoothing (Recommended First Try)

| Parameter | Current | Proposed | Change | File:Line |
|-----------|---------|----------|--------|-----------|
| `CRUISE_MAX_ACCEL` | 1.6 | **1.2** | −25% | [`long_mpc.py:60`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:60) |
| `A_CRUISE_MAX_VALS[0]` | 1.6 | **1.2** | −25% | [`longitudinal_planner.py:21`](selfdrive/controls/lib/longitudinal_planner.py:21) |
| `A_CRUISE_MAX_VALS[1]` | 1.2 | **1.0** | −17% | [`longitudinal_planner.py:21`](selfdrive/controls/lib/longitudinal_planner.py:21) |
| `A_CRUISE_MAX_VALS[2]` | 0.8 | **0.7** | −12% | [`longitudinal_planner.py:21`](selfdrive/controls/lib/longitudinal_planner.py:21) |
| `A_CRUISE_MAX_VALS[3]` | 0.6 | **0.5** | −17% | [`longitudinal_planner.py:21`](selfdrive/controls/lib/longitudinal_planner.py:21) |
| `A_CHANGE_COST` | 200 | **300** | +50% | [`long_mpc.py:39`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:39) |
| `J_EGO_COST` | 5.0 | **8.0** | +60% | [`long_mpc.py:38`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:38) |

**New `A_CRUISE_MAX_VALS` table:**
| Speed | Current | Proposed |
|-------|---------|----------|
| 0 mph (0 m/s) | 1.6 m/s² | **1.2 m/s²** |
| 22 mph (10 m/s) | 1.2 m/s² | **1.0 m/s²** |
| 56 mph (25 m/s) | 0.8 m/s² | **0.7 m/s²** |
| 89 mph (40 m/s) | 0.6 m/s² | **0.5 m/s²** |

**Expected feel:** Noticeably smoother initial acceleration from stop. Less "lurch" when ACC engages. Still responsive enough for normal driving. ~25% reduction in peak acceleration, ~50% stronger smoothing.

---

### Plan B: Aggressive Smoothing (If Plan A Still Feels Punchy)

| Parameter | Current | Proposed | Change | File:Line |
|-----------|---------|----------|--------|-----------|
| `CRUISE_MAX_ACCEL` | 1.6 | **1.0** | −37% | [`long_mpc.py:60`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:60) |
| `A_CRUISE_MAX_VALS` | [1.6,1.2,0.8,0.6] | **[1.0,0.8,0.6,0.5]** | −25-37% | [`longitudinal_planner.py:21`](selfdrive/controls/lib/longitudinal_planner.py:21) |
| `A_CHANGE_COST` | 200 | **400** | +100% | [`long_mpc.py:39`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:39) |
| `J_EGO_COST` | 5.0 | **10.0** | +100% | [`long_mpc.py:38`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:38) |
| `accel_clip` rate | ±0.05 | **±0.03** | −40% | [`longitudinal_planner.py:217`](selfdrive/controls/lib/longitudinal_planner.py:217) |

**Expected feel:** Very smooth, luxury-car-like acceleration. Minimal jerk. May feel slightly sluggish to drivers who prefer responsive acceleration.

---

### Plan C: Speed-Dependent Smoothing (Most Nuanced)

Keep higher acceleration at very low speeds (0-5 mph for natural creep), but reduce more aggressively at cruising speeds:

| Parameter | Current | Proposed | File:Line |
|-----------|---------|----------|-----------|
| `A_CRUISE_MAX_BP` | [0, 10, 25, 40] | **[0, 5, 15, 30, 40]** | [`longitudinal_planner.py:22`](selfdrive/controls/lib/longitudinal_planner.py:22) |
| `A_CRUISE_MAX_VALS` | [1.6, 1.2, 0.8, 0.6] | **[1.4, 1.0, 0.7, 0.5, 0.4]** | [`longitudinal_planner.py:21`](selfdrive/controls/lib/longitudinal_planner.py:21) |
| `CRUISE_MAX_ACCEL` | 1.6 | **1.2** | [`long_mpc.py:60`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:60) |
| `A_CHANGE_COST` | 200 | **300** | [`long_mpc.py:39`](selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py:39) |

---

## 7. What Each Parameter Changes (Driving Feel)

| Parameter | What happens if reduced/increased |
|-----------|----------------------------------|
| `CRUISE_MAX_ACCEL` ↓ | Cruise obstacle "pulls away" slower → MPC plans gentler acceleration profile. **Most impactful single change.** |
| `A_CRUISE_MAX_VALS` ↓ | Hard cap on final output. Prevents MPC from commanding high acceleration even if it wants to. |
| `A_CHANGE_COST` ↑ | MPC penalizes acceleration *changes* more → smoother transitions between accel/decel. Reduces "jerky" feel. |
| `J_EGO_COST` ↑ | MPC penalizes jerk directly → smoother velocity profiles. |
| `accel_clip` rate ↓ | Final safety net. Limits how fast acceleration can change frame-to-frame. |

---

## 8. Safety Considerations

| Concern | Analysis |
|---------|----------|
| Too slow to reach cruise speed? | Plan A reduces peak accel by 25% — still reaches set speed, just takes ~1-2s longer. |
| Hesitation in traffic? | Only affects no-lead / lead-faster scenarios. Earlier braking (lead slower) unchanged. |
| Resume from stop too sluggish? | Plan A keeps 1.2 m/s² from stop — still responsive. Plan C preserves 1.4 m/s² for creep. |
| Experimental Mode affected? | No — these are ACC-mode-only parameters. Blended mode uses different cost weights. |
| Earlier braking affected? | No — braking path uses `output_a_target_e2e` override, not these acceleration caps. |

---

## 9. Recommendation

Start with **Plan A**. The single most impactful change is `CRUISE_MAX_ACCEL: 1.6 → 1.2` — this alone may solve the problem. If still too aggressive, escalate to Plan B. If creep from stop feels too sluggish with Plan A, use Plan C instead.

---

## 10. Testing Scenarios

1. **Accelerate from stop, no lead** — Verify smooth, non-jerky acceleration
2. **Resume after lead clears at 30 mph** — Verify smooth speed recovery
3. **Lead faster than ego pulls away** — Verify no aggressive chase
4. **Stop-and-go traffic** — Verify natural creep and acceleration
5. **Approach stopped lead** — Verify earlier braking still works (unchanged)
6. **Experimental Mode ON** — Verify no regression (unchanged)
