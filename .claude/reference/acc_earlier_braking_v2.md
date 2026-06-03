## ACC Earlier Braking v2 — TTC-Based Lead Relevance + Resume-from-Stop Protection

**Branch:** `rtizi-dev`
**Date:** 2026-04-30

### Problem

The v1 fix used a simplistic `lead_is_relevant` check:
- Only checked `leadOne.vLead`, ignoring `leadTwo`
- No distance or TTC check — a lead 300m away triggered cruise obstacle removal
- `v_ego < v_cruise` blocked braking at cruise speed
- Model braking used `self.mpc.status` (any lead) instead of refined relevance

### Changes

#### `selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py`

1. Added `self.lead_relevant = False` initialization (line 252)
2. Replaced simple `vLead < v_ego` with TTC + distance-based `_lead_relevant()` helper:
   - Lead must be valid (`status = True`)
   - Lead must be slower than ego (`v_rel > 0`)
   - TTC < 10s OR distance < 10m
3. Applied to both `leadOne` and `leadTwo` with OR logic
4. Cruise obstacle removal gated on `self.lead_relevant`

#### `selfdrive/controls/lib/longitudinal_planner.py`

1. Changed `self.mpc.status` → `self.mpc.lead_relevant` for model braking gate
2. Added resume-from-stop protection: when `v_ego < 2.5 m/s` AND lead is pulling away (`vLead > v_ego`), model braking is blocked so ACC acceleration takes priority
3. If lead is stopped (vLead = 0), braking still takes priority even from stop

### Key Behaviors

| Scenario | lead_relevant | Cruise Obstacle | Model Braking |
|----------|:---:|:---:|:---:|
| No lead | False | Present | Skipped |
| Lead faster than ego | False | Present | Skipped |
| Lead far ahead, TTC > 10s | False | Present | Skipped |
| Stopped/slower lead within range | True | Removed | Active if model ≤ 0 |
| Resume from stop, lead pulling away | False | Present | Blocked |
| Resume from stop, lead stopped | True | Removed | Active |
| At cruise speed, slower lead ahead | True | Removed | Active if model ≤ 0 |
