# Fix: Honda Pilot Experimental Mode Cruise Speed Bug

## Problem

When driving a **2019 Honda Pilot** with:
- Speed Limit Assist enabled
- **Experimental Mode ON**
- Pressing SET button to engage cruise at current speed

**Expected behavior**: Cruise speed sets to current driving speed
**Actual behavior**: Cruise speed sets to 65 mph (105 kph) regardless of current speed

When Experimental Mode is **OFF**, it also doesn't work correctly (same issue).

---

## Root Cause

### Honda Pilot Configuration (Nidec system)

In `opendbc/car/honda/interface.py` lines 58-61:
```python
else:  # Nidec cars
  ret.openpilotLongitudinalControl = True
  ret.pcmCruise = True  # ← This is misleading
```

The 2019 Honda Pilot is a **Honda Nidec** platform car, which has:
- `pcmCruise = True` (indicates stock PCM handles cruise speed)
- `openpilotLongitudinalControl = True` (openpilot controls acceleration/braking)

### Bug #1: `initialize_v_cruise` Returns Early

In `openpilot/selfdrive/car/cruise.py` line 140-141:
```python
def initialize_v_cruise(self, CS, experimental_mode: bool, dynamic_experimental_control: bool) -> None:
  # initializing is handled by the PCM
  if self.CP.pcmCruise:
    return  # ← Returns early for Honda Pilot!
```

Because `pcmCruise = True`, the function **returns early** and never initializes `v_cruise_kph` to the current driving speed.

### Bug #2: `update_v_cruise` Overwrites with PCM Speed

Even after fixing Bug #1, the `update_v_cruise` method runs every frame and was **overwriting** the initialized value:

```python
if not self.CP.pcmCruise or (not self.CP_SP.pcmCruiseSpeed and _enabled):
  # openpilot's own speed logic
else:
  self.v_cruise_kph = CS.cruiseState.speed * CV.MS_TO_KPH  # ← Overwrites with PCM speed!
```

For Honda Pilot:
- `not self.CP.pcmCruise` = `False`
- `_enabled` is `False` on the first frame (button press handling)
- Condition becomes `False or (True and False)` = `False`
- Falls through to **else** branch and reads from stock PCM cruise speed

When `_enabled` is False, the system reads `CS.cruiseState.speed` from CAN messages, which comes from the stock PCM's cruise control setting (showing 65mph/105kph default).

---

## Solution

### Fix #1: Modified `initialize_v_cruise` early-return condition

**Before:**
```python
def initialize_v_cruise(self, CS, experimental_mode: bool, dynamic_experimental_control: bool) -> None:
  # initializing is handled by the PCM
  if self.CP.pcmCruise:
    return
```

**After:**
```python
def initialize_v_cruise(self, CS, experimental_mode: bool, dynamic_experimental_control: bool) -> None:
  # initializing is handled by the PCM
  # Exception: Honda Nidec has pcmCruise=True but openpilot controls longitudinal,
  # so it still needs initialization
  if self.CP.pcmCruise and not self.CP.openpilotLongitudinalControl:
    return
```

### Fix #2: Modified `update_v_cruise` to use openpilot speed for Honda Nidec

**Before:**
```python
if not self.CP.pcmCruise or (not self.CP_SP.pcmCruiseSpeed and _enabled):
  # if stock cruise is completely disabled, then we can use our own set speed logic
  self._update_v_cruise_non_pcm(CS, _enabled, is_metric)
```

**After:**
```python
# Non-PCM cars, or PCM cars where openpilot controls longitudinal (e.g., Honda Nidec)
# should use our own set speed logic instead of reading from stock PCM
use_op_own_speed = not self.CP.pcmCruise or self.CP.openpilotLongitudinalControl
if use_op_own_speed or (not self.CP_SP.pcmCruiseSpeed and _enabled):
  # if stock cruise is completely disabled, then we can use our own set speed logic
  self._update_v_cruise_non_pcm(CS, _enabled, is_metric)
  self.update_speed_limit_assist_v_cruise_non_pcm()
  self.v_cruise_cluster_kph = self.v_cruise_kph
  self.update_button_timers(CS, enabled)
else:
  # Read cruise speed from stock PCM (e.g., Toyota, Honda with stock ACC)
  self.v_cruise_kph = CS.cruiseState.speed * CV.MS_TO_KPH
  self.v_cruise_cluster_kph = CS.cruiseState.speedCluster * CV.MS_TO_KPH
```

This ensures:
- **Honda Nidec** (`pcmCruise=True`, `openpilotLongitudinalControl=True`): Uses openpilot's own speed logic ✓
- **True PCM cars** (`pcmCruise=True`, `openpilotLongitudinalControl=False`): Reads from stock PCM ✓
- **Non-PCM cars** (`pcmCruise=False`): Uses openpilot's own speed logic ✓

---

## How to Apply

You need to **restart the openpilot services** for the changes to take effect:

### Option 1: Reboot the device (easiest)
```bash
sudo reboot
```

### Option 2: Restart just the car process
SSH into your device and run:
```bash
sudo systemctl restart manager
```

Or if running manually:
```bash
# Kill the existing card process
pkill -f "card.py"

# The manager will automatically restart it
```

---

## Verification

After restarting, test by:

1. Drive at a speed (e.g., 45 mph)
2. Enable Experimental Mode in Toggles
3. Press SET to engage cruise control
4. Check the displayed cruise speed - it should show **45 mph** (your current speed)
5. Now try with Experimental Mode OFF - it should still show **45 mph**

---

## Debugging

If it still doesn't work, you can add temporary debug logging:

```python
# In update_v_cruise, after line 54:
print(f"[DEBUG] pcmCruise={self.CP.pcmCruise}, openpilotLong={self.CP.openpilotLongitudinalControl}")
print(f"[DEBUG] use_op_own_speed={use_op_own_speed}, _enabled={_enabled}")
print(f"[DEBUG] v_cruise_kph={self.v_cruise_kph}, CS.cruiseState.speed={CS.cruiseState.speed}")
```

Then check the logs when you press SET:
```bash
logread | grep -i "DEBUG\|v_cruise\|cruise"
```

---

## Technical Details

### Honda Pilot 2019 Configuration
- **Platform**: Honda Nidec
- `pcmCruise = True` (stock PCM cruise is present)
- `openpilotLongitudinalControl = True` (openpilot controls accel/brake)
- `pcmCruiseSpeed = False` (default, not explicitly set)

### Code Flow
1. Press SET button at current speed
2. `card.py` detects enable transition → calls `initialize_v_cruise()`
3. `initialize_v_cruise()` sets `v_cruise_kph` to current speed ✅
4. Every frame: `update_v_cruise()` maintains the value (doesn't overwrite from PCM) ✅
5. `CS.vCruise` is set from `v_cruise_helper.v_cruise_kph`
6. Controls uses this as the target cruise speed

### What Changed
- **Old behavior**:
  - `initialize_v_cruise` returned early (didn't set speed)
  - `update_v_cruise` read from `CS.cruiseState.speed` (stock PCM), which showed 65mph default
- **New behavior**:
  - `initialize_v_cruise` properly sets speed to current driving speed
  - `update_v_cruise` uses openpilot's own speed logic because `openpilotLongitudinalControl=True`

---

## Files Modified

1. **`openpilot/selfdrive/car/cruise.py`**
   - Updated `initialize_v_cruise()` method to check `openpilotLongitudinalControl`
   - Updated `update_v_cruise()` to use openpilot speed for Honda Nidec
   - Added comments explaining the Honda Nidec exception

2. **`openpilot/selfdrive/car/tests/test_cruise_speed.py`**
   - Added `test_initialize_v_cruise_honda_nidec()` - verifies Honda Nidec initialization works
   - Added `test_pcm_cruise_no_initialization()` - verifies true PCM cars still skip initialization

---

## Testing

Created verification script `test_honda_nidec_standalone.py` that validates:

1. ✅ Honda Nidec with Experimental Mode ON: Sets cruise to current speed
2. ✅ Honda Nidec with Experimental Mode OFF: Sets cruise to current speed
3. ✅ True PCM cruise: Correctly skips initialization
4. ✅ Low speed clamping: Speeds below minimum are clamped correctly
5. ✅ Old buggy behavior demonstration: Confirmed the fix resolves the 65mph issue

---

## Impact

This fix affects:
- **Honda Pilot 2016-22** (Nidec)
- **Honda Passport 2019-25** (Nidec)
- **Honda Ridgeline 2017-25** (Nidec)
- **Honda Civic 2016-18** (Nidec)
- **Honda Clarity 2018-21** (Nidec)
- **Acura RDX 2016-18** (Nidec)

All these cars have `pcmCruise=True` but `openpilotLongitudinalControl=True`, so they will now correctly set cruise speed to current driving speed when engaging with Experimental Mode enabled.

---

## Notes

- This is a **two-line logic change** with clear intent
- Backwards compatible: True PCM cars are unaffected
- No changes to Honda-specific code needed - the fix is in the generic cruise helper
- Follows existing code patterns and conventions
- Both fixes are required - fixing only `initialize_v_cruise` is not sufficient because `update_v_cruise` overwrites the value
