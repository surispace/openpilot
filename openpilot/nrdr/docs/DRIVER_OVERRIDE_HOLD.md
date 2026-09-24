# Driver Override Hold

Honda steering-override coexistence behavior that prevents steering vibration
caused by openpilot re-engaging the moment the driver relaxes their grip.

## The problem

Driver override is detected from raw steering torque crossing a threshold
(`NrdrDriverOverrideThreshold`). The release edge is instant: a single frame
below the threshold clears the override and the fade-up ramp starts. When the
driver holds the wheel while making small corrections, their applied torque
naturally jitters across the threshold several times a second. Each crossing
produces:

override detected -> torque fades down -> slight release -> torque fades back up
(0.1 s default) -> fight resumes -> repeat.

That loop is the ~10 Hz tug-of-war felt as steering vibration on sensitive EPS
platforms.

## The fix

While the driver is pressing, the fade-down behaves as before. After release,
`HondaOverrideFadeUpSecs` now serves a dual role: openpilot first waits that
long with torque held at `HondaOverrideTorqueScale` (normally 0), and only then
runs its normal fade-up ramp over the same value.

```text
Fade down            Hold (no torque)          Fade up
|---------------------|--|------------------------------------------------------|
force on wheel  release    fade_up seconds          ramp over fade_up seconds
```

So with `HondaOverrideFadeUpSecs = 1.0`, control returns after 1 s of no
assist followed by a 1 s smooth ramp. Re-arming is automatic: any new press
during the hold simply resumes the override and re-arms the full hold.

## Setting

| Param | Default | Range | Unit |
| :--- | :---: | :---: | :---: |
| `HondaOverrideFadeUpSecs` | 0.1 | 0.0–10.0 | s |

- The value is both the hold time and the fade-up ramp time; 1.0–2.0 s is the
  practical handoff window for normal corrections.
- `0.0` disables both the hold and the ramp (torque returns immediately), as it
  always did.
- The hold only applies to override release while lateral control stays active.
  If lateral control disengages, the override ramp state resets as before.

No new parameter is introduced: the native C++ params registry and the device
`libparams_c` binary are unchanged, so this needs no device recompile.

## Implementation

- Behavior: `update_steering_torque()` in
  `opendbc_repo/opendbc/sunnypilot/car/honda/controller_features.py`. While a
  press is active the hold timer is armed from `live.override_fade_up_s`; on
  release the timer counts down and the fade-down continues to the override
  minimum; only after the timer expires does the fade-up ramp begin.
  `DT_CTRL` is the time base, so the hold is live and framerate-independent.

## Validation

- `openpilot/nrdr/tests/test_torque_output_filter.py` exercises the production
  steering source directly: `test_override_fade_up_also_holds_before_fading_back_in`
  verifies torque holds at the override minimum for the full hold and that
  fade-up begins only after it expires, for both 0.1 s and 1.0 s.