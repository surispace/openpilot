# Driver Override Hold

`HondaOverrideHoldSecs` is a Honda steering-override coexistence setting that
fixes steering vibration caused by openpilot re-engaging the moment the driver
relaxes their grip.

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

After a driver override, openpilot keeps yielding for a configurable hold time
before it starts taking control back. During the hold, torque stays at
`HondaOverrideTorqueScale` (normally 0) and the fade-up does not start. Only
when the hold expires does the normal `HondaOverrideFadeUpSecs` ramp run.
Re-arming is automatic: any new press while holding simply resumes the override
and re-arms the full hold.

```text
Fade down                                     Hold (no torque)          Fade up
|--------------------------|----|---------------------------------------------|
force on wheel     release                    hold time                 full torque
```

The no-torque hold is what converts the sharp "who has the wheel" handshake
into a one-directional handoff: the driver always owns the wheel first, and
openpilot only asks for it back after a deliberate, uninterrupted pause.

## Setting

| Param | Default | Range | Unit |
| :--- | :---: | :---: | :---: |
| `HondaOverrideHoldSecs` | 1.0 | 0.0–10.0 | s |

- `0.0` disables the hold: re-engagement starts immediately on release, exactly
  as before.
- 1.0–2.0 s is the practical handoff window for normal corrections.
- The hold only applies to override release while lateral control stays active.
  If lateral control disengages, the override ramp state resets as before.

## Implementation

- Registry: `HondaOverrideHoldSecs` (FLOAT, persistent, backed up) in
  `openpilot/nrdr/params/specs.py`; generated Python keys/C++ include via
  `openpilot/nrdr/params/generate.py`.
- Live path: `openpilot/nrdr/car/opendbc.py` publishes it on the typed
  `HondaLiveTuning` boundary (`override_hold_s`, slow param group, 0–10 s clamp).
- Behavior: `update_steering_torque()` in
  `opendbc_repo/opendbc/sunnypilot/car/honda/controller_features.py`. While a
  press is active the hold timer is armed; on release the timer counts down and
  the fade-down continues to the override minimum; only after the timer expires
  does the fade-up ramp begin. `DT_CTRL` is the time base, so the hold is live
  and framerate-independent.

## Validation

- `openpilot/nrdr/tests/test_torque_output_filter.py` exercises the production
  steering source directly: `test_override_hold_waits_before_fading_back_in`
  verifies torque holds at the override minimum for the full hold and that
  fade-up begins only after it expires, for both 0.0 s (disabled) and 1.0 s.
- Boundary tests in `test_opendbc_boundary.py` pin the default (1.0 s) and the
  0–10 s clamp on the typed boundary.