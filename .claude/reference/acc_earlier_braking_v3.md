## ACC Earlier Braking v3 — Extended TTC + Tighter Danger Zone

**Branch:** `rtizi-dev`
**Date:** 2026-05-02

### Problem

v2 earlier braking wasn't triggering early enough at ~50 mph approaching a stopped lead. The TTC=10s threshold meant detection at ~223m, and LEAD_DANGER_FACTOR=0.85 left too much slack in the MPC danger zone constraint.

### Changes

#### `selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py`

1. **TTC threshold: 10.0s → 12.0s** (line 376)
   - Lead relevance detection triggers 20% earlier
   - At 50 mph → stopped lead: detection moves from 223m → 268m (+45m)

2. **ACC_LEAD_DANGER_FACTOR: 0.85 → 0.90** (line 43)
   - MPC danger zone constraint tightens ~6%
   - MPC itself brakes earlier when lead is present, even before model override

### Impact at Common Speeds → Stopped Lead

| Ego Speed | v_rel | Detection Distance (TTC=12s) |
|-----------|-------|------------------------------|
| 50 mph (22.4 m/s) | 22.4 m/s | **268 meters** |
| 40 mph (17.9 m/s) | 17.9 m/s | **215 meters** |
| 30 mph (13.4 m/s) | 13.4 m/s | **161 meters** |

### Edge Case Safety

| Scenario | TTC | lead_relevant |
|----------|-----|:---:|
| Lead 300m ahead, 5 mph slower | 136s | False |
| Lead 200m ahead, 10 mph slower | 44s | False |
| Lead 150m ahead, 15 mph slower | 22s | False |
| Lead 100m ahead, stopped | 4.5s | True |
| Resume from stop, lead pulling away | — | Blocked by guard |

### Key Behaviors (unchanged from v2)

| Scenario | lead_relevant | Cruise Obstacle | Model Braking |
|----------|:---:|:---:|:---:|
| No lead | False | Present | Skipped |
| Lead faster than ego | False | Present | Skipped |
| Lead far ahead, TTC > 12s | False | Present | Skipped |
| Stopped/slower lead within range | True | Removed | Active if model ≤ 0 |
| Resume from stop, lead pulling away | False | Present | Blocked |
| Resume from stop, lead stopped | True | Removed | Active |
| At cruise speed, slower lead ahead | True | Removed | Active if model ≤ 0 |
