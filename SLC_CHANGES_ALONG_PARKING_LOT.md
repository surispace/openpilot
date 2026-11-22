# SLC Changes Along with Parking Lot

## Completed changes (port committed to FrogPilot-Testing branch)

### Commit `853ffdfec` / `6ee0dbbf2` — SLC raises cruise above manual SET speed + UI/HUD sync

**`frogpilot/controls/lib/frogpilot_vcruise.py`:**
- `slc_value` is now the base of `targets` instead of being capped at manual `v_cruise`.
- `slc_value = max(slc_target + slc_offset, CRUISING_SPEED)` when SLC active.
- CSC only lowers cruise for curves (`csc_active and csc_target < slc_value`); it no longer ceilings cruise at the driver-set speed.
- Cruise can now rise **above** the manual SET speed to speed limit + offset / overridden speed.

**`selfdrive/controls/controlsd.py`:**
- UI/HUD (`controlsState.vCruise` / `hudControl.setSpeed`) syncs to `frogpilotPlan.vCruise` (the SLC target) every frame when:
  - `CC.enabled` (cruise is engaged) — prevents UI jump on fresh start before cruise set
  - `speed_limit_controller` toggle ON
  - `slcSpeedLimit > 0` — prevents stale SLC value from overwriting driver-set/vEgo-based value when SLC target is none
  - `not cscControllingSpeed` — UI/HUD holds steady during CSC curves; internal car slows but display doesn't flicker

### Commit `d856a758e` — Skip SLC confirmation prompt for speed limit changes <= 10 MPH

**`frogpilot/controls/lib/speed_limit_controller.py`:**
- Added `SLC_CONFIRMATION_THRESHOLD_MPH = 10`
- `handle_limit_change` now only requires driver confirmation when `abs(desired_target - self.target) > 10 MPH`.
- Changes at or under 10 MPH auto-apply with no confirmation banner.
- Confirmation toggles (`speed_limit_confirmation_lower` / `speed_limit_confirmation_higher`) still gate prompts for changes exceeding 10 MPH.

### Commit `b5014840b` — Remove v_ego_diff from slc_value to stop UI/HUD fluctuation

**`frogpilot/controls/lib/frogpilot_vcruise.py`:**
- Removed `- v_ego_diff` from `slc_value` computation — `slc_value` now equals `max(slc_target + slc_offset, CRUISING_SPEED)` without subtracting speedometer error.
- Removed now-unused `v_ego_diff` variable (`v_ego_cluster - v_ego`).
- Fix: UI/HUD no longer flickers 54↔55 MPH from frame-to-frame speedometer/actual-speed jitter. UI shows stable speed-limit + offset value.

### Commit `07e018396` — Show new speed limit sign immediately during confirmation pending

**`frogpilot/controls/frogpilot_planner.py`:**
- `slcSpeedLimit` = `unconfirmed_speed_limit if unconfirmed_speed_limit > 0 else slc_target` — speed limit sign shows NEW limit immediately during SLC confirmation pending window (>10 MPH change). Cruise target stays at old confirmed limit until driver accepts (+) or denies (-).
- Pending limit sign shows `unconfirmedSlcSpeedLimit` with pending text underneath.
- UI max (cruise) stays gated waiting for approval; speed limit sign shows new location limit immediately.

### Commit `63ecc74fe` — Show green confirmation banner for SLC pending limit

**`selfdrive/selfdrived/events.py`:**
- Added `speed_limit_changed_alert` callback function — reads `sm["frogpilotPlan"].slcSpeedLimit` and returns dynamic Alert:
  - `slcSpeedLimit <= 0` → empty alert (no banner)
  - `unconfirmedSlcSpeedLimit > 0` (pending) → `"Press '+' to accept {limit}, '-' to Deny"`
  - Otherwise → `"Speed Limit Changed {speed_str}"`
- Changed `FROGPILOT_EVENTS[speedLimitChanged]` from static `Alert(...)` to `speed_limit_changed_alert` callback (both base and MICI override tables)
- Alert uses `FrogPilotAlertStatus.frogpilot`, `AlertSize.small`, `Priority.LOW`, `VisualAlert.none`, `AudibleAlert.none` — no audible alert

**`frogpilot/controls/lib/frogpilot_events.py`:**
- Changed condition from `speed_limit_changed_timer == DT_MDL` to `speed_limit_changed_timer > 0` so alert shows during entire pending window (30s), not just one frame at start

### Commit `0b8fe44a4` — SLC confirmation pending - UI sync, banner, and bug fixes

**`frogpilot/controls/frogpilot_planner.py`:**
- `slcSpeedLimit` = `unconfirmed_speed_limit if sm["controlsState"].enabled and unconfirmed_speed_limit > 0 else slc_target` — adds cruise-engaged gate so banner doesn't show when cruise disengaged

**`frogpilot/controls/lib/frogpilot_events.py`:**
- Banner trigger now requires `sm["controlsState"].enabled and speed_limit_changed_timer > 0` — no zero-value banner when cruise disengaged

**`selfdrive/selfdrived/events.py`:**
- `speed_limit_changed_alert` reads `slcSpeedLimit` (not `unconfirmedSlcSpeedLimit` directly), returns empty alert when `slcSpeedLimit <= 0`, shows "Press '+' to accept {limit}, '-' to Deny" when unconfirmed > 0, otherwise "Speed Limit Changed {speed_str}"

### Commit `e929daf9a` — UI: CSC Active indicator next to UI max speed

**`selfdrive/ui/onroad/hud_renderer.py`:**
- Added `csc_label` font size (32) and `csc_active` font size (22) to `FontSizes`
- Added `CSC_ACTIVE` orange color (`rl.Color(255, 140, 0, 255)`) to `Colors`
- In `_draw_set_speed`, when `plan.cscControllingSpeed` and `csc_status` toggle is ON:
  - Renders "CSC" (bold white, larger) above "ACTIVE" (smaller orange, fits width of "CSC")
  - Positioned immediately to the right of the UI max speed box
  - Gone (nothing shown) when CSC is not controlling speed

### Commit `57e2ec9b6` — Port base SLC, LKAS, and driver monitoring improvements

- `.gitignore` — added common Python/build/IDE exclusions
- `always_on_lateral.py` — `cruise_main_prev = False` so always-on LKAS arms immediately when cruise main already ON at car start
- `monitoring/helpers.py` — AWARENESS/DISTRACTED timeouts increased to 60s (pre 30s, prompt 45s, terminal 60s)
- `controlsd.py` — lanesVisible = `CC.enabled or alwaysOnLateralEnabled` so lane markings stay visible at standstill when always-on LKAS enabled

### Commit `ITEM-4-IMPLEMENTED` — Driver Override During SLC Confirmation Pending

**Problem:** When SLC active and driver presses `+`/`-` to override cruise above `slc_value`, override is discarded because `slc_value` replaces `v_cruise` input.

**Desired:** Driver override persists until accept/deny/timeout. ANY speed limit change triggers confirmation banner while override active.

**`frogpilot/controls/lib/frogpilot_vcruise.py`:**
- Added `driver_override_active` state var (`__init__`).
- In SLC active block: computes `slc_candidate = max(overridden_speed, slc_target + offset, CRUISING_SPEED)`.
- When no confirmation pending and `abs(v_cruise - slc_candidate) > 0.03` (driver has moved speed away from limit via `+/-`): latches `driver_override_active = True`.
- While override active: `slc_value = v_cruise` (driver's held speed, not capped at limit).
- Otherwise: `slc_value = slc_candidate`.
- Resets override when SLC toggle OFF/disabled.

**`selfdrive/controls/controlsd.py`:**
- Skips the `v_cruise_kph = planner.vCruise` wipe every frame when driver-adjusted cruise deviates from SLC limit (`abs(v_cruise_kph - slc_limit_kph) > 0.1 kph`). Preserves the existing `drive_helpers` `+/-` increment (`cruise_increase`/`cruise_increase_long`) so the driver's override speed can establish and persist.

**`frogpilot/controls/lib/speed_limit_controller.py`:**
- `handle_limit_change`: when `driver_override_active` and a speed limit change occurs (different source/target), forces `confirmation_required = True` regardless of the 10 MPH threshold or confirm toggle state.
- On accept (`speed_limit_accepted`): clears `driver_override_active` and applies new limit as cruise target.
- On deny/timeout: keeps override active; cruise stays at override speed.
- `reset()`: clears `driver_override_active` when SLC disabled.

**Banner alert text (existing, no change):**
- `unconfirmedSlcSpeedLimit > 0` → `"Press '+' to accept {limit}, '-' to Deny"`
- Otherwise → `"Speed Limit Changed {speed_str}"`

---

## Deferred implementation items (parking lot)

### Item 2: Driver +/- override hold until SLC target changes

**Problem:** When SLC active (`slc_target > 0`), `slc_value` immediately overwrites driver's `+/-` set speed. Pressing `+/-` has no effect while SLC has an active target.

**Desired:** Driver presses `+/-` → capture override speed, hold until SLC target changes, then release override and apply new `slc_value`.

**Files to change:** `frogpilot/controls/lib/frogpilot_vcruise.py` — add `slc_override_active`, `slc_override_speed`, `prev_slc_target` state vars + override logic in `update()`.

---

### Item 3: Green confirmation banner + button gating during SLC pending — IMPLEMENTED

See Completed changes section above (commits `07e018396`, `63ecc74fe`, `0b8fe44a4`).

---

### Item 4: Driver Override During SLC Confirmation Pending — IMPLEMENTED

See Completed changes section above (commit `ITEM-4-IMPLEMENTED`).

#### Scenario Matrix (✓ = covered)

**Cruise Not Engaged + Confirm Toggle OFF**

| Step | Trigger | UI Speed Limit Sign | UI Max/HUD (cruise speed) | Pending Banner | `+` Button | `-` Button |
|------|---------|---------------------|----------------------|----------------|------------|------------|
| 1 | Cruise not engaged, confirm toggle OFF, limit 55 | 55 MPH (raw limit, immediate) | N/A | No | N/A | N/A | ✓ |
| 2 | New limit 70 (>10 MPH) | 70 MPH (immediate) | N/A | No | N/A | N/A | ✓ |

**Cruise Engaged + Confirm Toggle OFF**

| Step | Trigger | UI Speed Limit Sign | UI Max/HUD (cruise speed) | Pending Banner | `+` Button | `-` Button |
|------|---------|---------------------|----------------------|----------------|------------|------------|
| 1 | Cruise engaged, confirm toggle OFF, limit 55, no override | 55 MPH | 55 MPH | No | Normal adjust | Normal adjust | ✓ |
| 2 | New limit 70 (>10 MPH), no override | **70 MPH (immediate)** | **70 MPH (auto-applied)** | No | Normal adjust at 70 | Normal adjust at 70 | ✓ |
| 3 | Driver presses `+` 5x → cruise 75 MPH | 70 MPH | **75 MPH (driver override)** | No | Normal adjust at 75 | Normal adjust at 75 | ✓ |
| 4 | New limit 80 (>10 MPH) while override active | **80 MPH (immediate)** | **75 MPH (override held)** | **Yes: "Press '+' to accept 80, '-' to Deny"** | Accept → override cleared, UI Max = **80 MPH** | Deny → UI Max = **75 MPH (override held)** | ✓ |
| 5 | New limit 75 (≤10 MPH change) while override active | **75 MPH (immediate)** | **75 MPH (override held)** | **Yes: "Press '+' to accept 75, '-' to Deny"** | Accept → override cleared, UI Max = **75 MPH** | Deny → UI Max = **75 MPH (override held)** | ✓ |

**Cruise Engaged + Confirm Toggle ON**

| Step | Trigger | UI Speed Limit Sign | UI Max/HUD (cruise speed) | Pending Banner | `+` Button | `-` Button |
|------|---------|---------------------|----------------------|----------------|------------|------------|
| 1 | Cruise engaged, confirm toggle ON, limit 45 | 45 MPH | 45 MPH | No | Normal adjust | Normal adjust | ✓ |
| 2 | New limit 50 (≤10 MPH change), no override | **50 MPH (immediate)** | **50 MPH (auto-applied)** | No | Normal adjust at 50 | Normal adjust at 50 | ✓ |
| 3 | New limit 70 (>10 MPH), no override | **70 MPH (immediate)** | **50 MPH (gated)** | **Yes: "Press '+' to accept 70, '-' to Deny"** | Accept → UI Max = **70 MPH** | Deny → UI Max = **50 MPH** | ✓ |
| 4 | Driver presses `+` 5x → cruise 75 MPH (no pending, above limit) | 70 MPH | **75 MPH (driver override)** | No | Normal adjust at 75 | Normal adjust at 75 | ✓ |
| 5 | New limit 80 (>10 MPH) while override active | **80 MPH (immediate)** | **75 MPH (override held)** | **Yes: "Press '+' to accept 80, '-' to Deny"** | Accept → override cleared, UI Max = **80 MPH** | Deny → UI Max = **75 MPH (override held)** | ✓ |
| 6 | New limit 70 (≤10 MPH change) while override active | **70 MPH (immediate)** | **75 MPH (override held)** | **Yes: "Press '+' to accept 70, '-' to Deny"** | Accept → override cleared, UI Max = **70 MPH** | Deny → UI Max = **75 MPH (override held)** | ✓ |
| 7 | Waiting (no action) while override active | Latest limit | Override speed (held) | Yes | Accept → UI Max = new limit | Deny → UI Max = override speed (held) | ✓ |
| 8 | Timeout (30s) while override active | Latest limit | Override speed (held) | Times out → Deny → UI Max = override speed (held) | N/A | N/A | ✓ |

#### Rule
When driver override is active, ANY speed limit change triggers confirmation banner (regardless of diff size, regardless of confirm toggle state).

#### Key behaviors

1. **Driver override via `+`/`-` buttons**: Driver's set speed becomes an override that can exceed `slc_value`. Override persists until accept/deny/timeout.
2. **Banner trigger when override active**: ANY speed limit change triggers confirmation banner (regardless of diff size > 10 MPH or confirm toggle state).
3. **Accept**: Driver override cleared, cruise set to new limit.
4. **Deny**: Driver override stays active, cruise stays at override speed.
5. **Timeout (30s)**: Same as deny → override stays active.

---

### Item 5: Driver Offset Adjustment via +/- Buttons — PARKED

**Problem:** When SLC active (`slc_target > 0`), pressing `+`/`-` buttons does nothing because `slc_value` completely replaces the driver's `v_cruise` input (`frogpilot_vcruise.py:70`). The driver cannot manually adjust cruise speed above `slc_target + slc_offset` using `+`/`-` buttons.

#### Desired behavior

| # | Cruise Engaged | SLC Active | Driver Override Active | `+` Button | `-` Button | Result |
|---|----------------|------------|----------------------|------------|------------|--------|
| 1 | Yes | Yes | No | + | Increases offset → cruise goes up |
| 2 | Yes | Yes | No | - | Decreases offset → cruise goes down |
| 3 | Yes | Yes | Yes | + | Increases offset → cruise goes up |
| 4 | Yes | Yes | Yes | - | Decreases offset → cruise goes down |
| 5 | Yes | No | N/A | + | Increases `v_cruise_kph` | Normal adjust |
| 6 | Yes | No | N/A | - | Decreases `v_cruise_kph` | Normal adjust |

#### Key behaviors

1. **Offset adjustment**: When SLC is active and no pending confirmation, `+`/`-` buttons adjust `slc_offset` instead of `v_cruise_kph`. `slc_value = slc_target + slc_offset`.
2. **No pending confirmation**: Banner is not shown for offset-only changes.
3. **Confirmation pending**: `+`/`-` buttons act as accept/deny (existing behavior takes priority).
4. **Offset persists**: `offset_adjust` stays within the same drive session across cruise disengage/re-engage (reset() not called when SLC toggle ON).
5. **Offset reset**: `_offset_adjust = 0` on cruise disengage only if SLC toggle OFF; resets to 0 on car ignition OFF→ON (new `SpeedLimitController` → `__init__`).

#### Implementation approach

| File | Change |
|------|--------|
| `frogpilot/controls/lib/speed_limit_controller.py` | Add `self._offset_adjust = 0` field. Make `offset` a settable property: getter returns `base_offset + _offset_adjust`, setter computes `_offset_adjust = value - base_offset`. Reset `_offset_adjust = 0` in `__init__` and `reset()`. |
| `frogpilot/controls/lib/frogpilot_vcruise.py` | Add `ButtonType, CRUISE_INTERVAL_SIGN` import. In SLC active block with no pending confirmation, detect driver `+`/`-` button presses and adjust `self.slc.offset` directly. |
| `selfdrive/controls/lib/drive_helpers.py` | No changes needed — button detection done in `frogpilot_vcruise.py` directly. |
| `frogpilot/controls/frogpilot_planner.py` | No changes needed. |

---

## Already implemented (not parking lot)

## Already implemented (not parking lot)
