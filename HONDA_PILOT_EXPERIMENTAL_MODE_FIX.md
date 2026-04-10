# Fix: Honda Pilot Experimental Mode Cruise Speed Bug

## Problem

When driving a **2019 Honda Pilot** with:
- Speed Limit Assist enabled
- **Experimental Mode ON**
- Pressing SET button to engage cruise at current speed

**Expected behavior**: Cruise speed sets to current driving speed  
**Actual behavior**: Cruise speed sets to 65 mph (105 kph) regardless of current speed

When Experimental Mode is **OFF**, it works correctly (sets to current speed).

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

### The Bug

In `openpilot/selfdrive/car/cruise.py` line 140-141:
```python
def initialize_v_cruise(self, CS, experimental_mode: bool, dynamic_experimental_control: bool) -> None:
  # initializing is handled by the PCM
  if self.CP.pcmCruise:
    return  # ← Returns early for Honda Pilot!
```

Because `pcmCruise = True`, the function **returns early** and never initializes `v_cruise_kph` to the current driving speed.

When Experimental Mode is ON:
- `initialize_v_cruise()` is called but returns immediately
- `v_cruise_kph` stays at `V_CRUISE_UNSET` (255) or previous value
- The system falls back to using `V_CRUISE_INITIAL_EXPERIMENTAL_MODE = 105` kph = **65 mph**

When Experimental Mode is OFF:
- The stock PCM cruise system handles the set speed via CAN messages
- openpilot reads it from `CS.cruiseState.speed`
- Works correctly

---

## Solution

Modified the early-return condition to check if openpilot actually controls longitudinal:

### Before:
```python
def initialize_v_cruise(self, CS, experimental_mode: bool, dynamic_experimental_control: bool) -> None:
  # initializing is handled by the PCM
  if self.CP.pcmCruise:
    return
```

### After:
```python
def initialize_v_cruise(self, CS, experimental_mode: bool, dynamic_experimental_control: bool) -> None:
  # initializing is handled by the PCM
  # Exception: Honda Nidec has pcmCruise=True but openpilot controls longitudinal,
  # so it still needs initialization
  if self.CP.pcmCruise and not self.CP.openpilotLongitudinalControl:
    return
```

This ensures:
- **Honda Nidec** (`pcmCruise=True`, `openpilotLongitudinalControl=True`): **Initializes** cruise speed to current speed ✓
- **True PCM cars** (`pcmCruise=True`, `openpilotLongitudinalControl=False`): **Skips** initialization (PCM handles it) ✓

---

## Files Modified

1. **`openpilot/selfdrive/car/cruise.py`**
   - Updated `initialize_v_cruise()` method to check `openpilotLongitudinalControl`
   - Added comment explaining the Honda Nidec exception

2. **`openpilot/selfdrive/car/tests/test_cruise_speed.py`**
   - Added `test_initialize_v_cruise_honda_nidec()` - verifies Honda Nidec initialization works
   - Added `test_pcm_cruise_no_initialization()` - verifies true PCM cars still skip initialization

---

## Testing

Created verification script `test_honda_nidec_fix.py` that validates:

1. ✅ Honda Nidec with Experimental Mode ON: Sets cruise to current speed
2. ✅ Honda Nidec with Experimental Mode OFF: Sets cruise to current speed  
3. ✅ True PCM cruise: Correctly skips initialization
4. ✅ Low speed clamping: Speeds below minimum are clamped correctly

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

- This is a **one-line logic change** with clear intent
- Backwards compatible: True PCM cars are unaffected
- No changes to Honda-specific code needed - the fix is in the generic cruise helper
- Follows existing code patterns and conventions
