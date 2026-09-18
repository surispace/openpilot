# Honda Pilot (2019, Nidec) — Longitudinal Control: Tune for Early, Smooth Braking

How the nrdr longitudinal stack works, every setting that shapes braking, and
three test rounds for the symptom: *the car does nothing until it is right
behind the lead, then applies a late "creep" brake*.

> This is research software. Test on closed roads first, one knob at a time,
> and keep notes. Logging `longitudinalPlan`, `carState`, and `radarState` is
> the fastest way to see the effect of each change.

---

## 1. The longitudinal stack in nrdr (what actually brakes)

```
personality (Aggressive/Standard/Relaxed/Econ)  <- LongitudinalPersonality param / wheel distance button
        |
        v
LongitudinalPlanner -> NrdrLongitudinalPlanner          (cruise accel ceiling, accel limits)
        |                    |
        v                    v
LongitudinalMpc -> NrdrLongitudinalMpc                   (follow-distance / brake planning, the big one)
        |                    |
        v                    v
NrdrLongControl (PID)  <-  damping, stop state machine    (tracks the planned accel)
        |
        v
Honda Nidec carcontroller (opendbc)                      (gas/brake pedal shaping, brake rate clamp)
```

Two different braking decisions exist:

1. **Approach to a moving/stopped lead** — decided by the MPC
   (`longitudinal_mpc.py` + `long_mpc.py`). It builds an "obstacle" boundary
   ahead of the lead and chooses when to start shedding speed so the car stays
   ahead of that boundary. This is where "brake later, then creep" comes from.
2. **Final stop to zero** — decided by `longcontrol.py` +
   `longitudinal_stopping.py` when `vEgo < HondaVEgoStopping` (default 0.5 m/s).
   This is the physical "creep" ramp near standstill and is shaped by the
   stopping-rate params.

Both must be tuned together. The MPC decides *when* braking starts; the
stopping controller decides how *smoothly* it finishes.

> Check that the car is actually on openpilot longitudinal control
> (gas-pedal interceptor + openpilot ACC). If a Nidec runs the stock OEM ACC
> instead, the MPC/planner knobs below do nothing — only the carcontroller
> "Nidec shaping" settings still apply.

---

## 2. Where settings live

| Surface | Where | Examples |
| --- | --- | --- |
| On-device UI | Settings → nrdr → Longitudinal Tuning | Stopping Decel Rate, Stop Accel, Planner Stopping Rate, vEgo Stopping/Starting, Nidec ECU-Matched Long, Full Brake Authority, Roen Accel Limits, Distance 1–4 PID scales |
| Sunnylink app | Cruise page → nrdr Longitudinal Tuning + Driving Personality | Same params; `LongitudinalPersonality` lives in the Cruise section |
| Deep tune file | `/data/nrdr_long_tune.json`, edited on-device with the CLI (`python -m openpilot.nrdr.features.longitudinal.long_tune set key=value`) | `t_follow_offsets`, `jerk_factors`, `comfort_brake`, `stop_distance`, `lead_consumption.*`, `stopping.*`, `a_cruise_max_scale` |

CLI quick reference (run on the comma device):

```sh
python -m openpilot.nrdr.features.longitudinal.long_tune show
python -m openpilot.nrdr.features.longitudinal.long_tune set t_follow_offsets.standard=0.3 jerk_factors.standard.j_ego=1.4 comfort_brake=2.2
python -m openpilot.nrdr.features.longitudinal.long_tune reset   # delete file -> compiled defaults
```

`LongTune` reloads the file every 20 planner frames (~0.2 s), so changed values
go live almost immediately. Numbers outside a field's clamped range are
rejected and reported in the log line `nrdr_long_tune: loaded ...`.

---

## 3. Every braking-relevant setting

### 3.1 Driving personality (biggest lever)

`LongitudinalPersonality` sets the base following time-gap (`t_follow`) and
jerk cost used by the MPC (`longitudinal_mpc.py`):

| Personality | t_follow (s) | base jerk factor | PID scale default |
| --- | --- | --- | --- |
| 1 / Aggressive | 0.75 | 0.4 | 200 % |
| 2 / Standard | 1.45 | 1.0 | 100 % |
| 3 / Relaxed | 1.75 | 1.0 | 80 % |
| 4 / Econ | 2.25 | 1.5 | 50 % |

Longer `t_follow` alone makes the car start braking earlier and lighter because
the MPC keeps the planned occupant boundary further back. **Relaxed / Econ is
the first, no-cost step toward "brake ahead".**

### 3.2 Deep MPC tune (`/data/nrdr_long_tune.json`)

Authoritative field definitions and ranges are in
`openpilot/nrdr/features/longitudinal/long_tune.py`.

| Key | Default | Range | Effect on approach braking |
| --- | --- | --- | --- |
| `t_follow_offsets.<personality>` | 0.0 | −0.35 … +0.5 (s) | Adds seconds of gap on top of the personality baseline. **Raise for earlier/gentler decel** (`t_follow = max(0.9, base + offset)`). |
| `jerk_factors.<personality>.a_change` | personality base | 0.2 … 3.0 | Cost weight on acceleration change (× 200). **Higher = smoother, starts braking sooner** because hard changes are "expensive". |
| `jerk_factors.<personality>.j_ego` | personality base | 0.2 … 3.0 | Cost weight on jerk (× 5). Same direction: higher = smoother. |
| `comfort_brake` | 2.5 | 2.0 … 3.0 (m/s²) | The decel the plan assumes is comfortable. **Lower (2.0–2.2) = larger reserved stopping distance `v²/2·brake` = earlier, lighter braking.** Raise only if the car feels like it hangs back too much. |
| `stop_distance` | 6.0 | 4.5 … 7.5 (m) | Constant stand-off added to the cruise boundary. **Raise (6.5–7.5) = brake earlier / keep more room.** |
| `a_cruise_max_scale` | [1,1,1,1] | 0.5 … 1.5 each | Scales cruise accel ceiling per speed band; affects acceleration, not braking. Leave 1.0. |
| `low_speed_jerk_scale` | 1.0 | 1.0 … 2.0 | Multiplies jerk factors below 2 m/s. **Keep at 1.0** (raising makes the last low-speed meters jerkier — the opposite of what you want). |
| `lead_consumption.m1_anchor` | 1.0 | 0 … 1 | How much the trajectory uses the filtered vs raw lead speed. Leave 1.0. |
| `lead_consumption.m1_alead_escape` | 1.0 | 0.5 … 2.0 | Above this lead acceleration the filter stops trusting filtered anchor. Leave 1.0. |
| `lead_consumption.m2_w_max` | 0.0 | 0 … 1 | Blend of the lead's *measured deceleration* into its predicted trajectory. **Raise (0.5–0.8) so a lead that starts braking makes the plan respond immediately** instead of waiting for the gap to shrink. |
| `lead_consumption.m2_alead_deadband` | 0.5 | 0.3 … 1.0 | Minimum lead |accel| before the m2 blend engages; higher = fewer false early brakes. |
| `lead_consumption.m2_drel_gate` | 40.0 | 20 … 80 (m) | Distance gate for the m2 blend. Raise toward 50–60 to let the blend act on farther leads. |
| `lead_consumption.m3_b_eff_max` | 2.5 | 2.5 … 4.5 (m/s²) | Extra effective brake applied once a persistent lead-braking event is confirmed. **Raise (3.5–4.5) for decisive, non-creep response to a braking lead** (works only when lead is present and `aLeadK` is sane). |
| `lead_consumption.m3_alead_gate` | −0.5 | −2.0 … −0.3 | Sensitivity of that confirm: **less negative (−0.35) = reacts to lighter lead braking.** |
| `stopping.l2_enable` | 1.0 | 0 / 1 | 0 reverts the final stop to the stock ramp (`_stock_stopping_accel`). Escape hatch if the new stop logic feels wrong. |
| `stopping.hold_accel` | −0.6 | −1.0 … −0.3 | Brake held while creeping/stopped. |
| `stopping.phase_switch_v` | 0.15 | 0.05 … 0.5 (m/s) | Where the pitch-compensated hard hold begins. |
| `stopping.proximity_scale_m` | 8.0 | 2 … 20 (m) | Distance within which the final ramp rate is scaled by `drel/proximity_scale_m` (the "creep"). **Raise (10–14) so the gentle ramp starts farther from the lead → smoother, earlier final slowdown.** |
| `stopping.pitch_margin` | 1.0 | 0 … 2.0 | Hill-hold strength. Leave default. |

### 3.3 Registry/UI params (canonical keys in `openpilot/nrdr/params/specs.py`)

| Param | Default | What it does for braking |
| --- | --- | --- |
| `HondaStoppingDecelRate` | 30 (→0.30 m/s²/s) | Physical brake-pressure ramp clamp in the carcontroller while the state is `stopping` (`brake_rate_up = live.stopping_decel_rate`). **Lower (20–25) = softer final brake grab.** |
| `HondaStoppingDecelRateLong` | 0.3 (0.0–5.0) | Planner-side ramp-down rate of the commanded decel at the end of a stop. **Lower (0.2–0.25) = longer, gentler fade; higher = quicker finish.** |
| `HondaStopAccel` | −2.0 (m/s²) | Brake demand held once stopped (hill-hold). |
| `HondaVEgoStopping` / `HondaVEgoStarting` | 0.5 / 0.5 (m/s) | Speeds where planner/longcontrol switch into and out of stopping state. **Raising both to ~0.6–0.7 engages the smooth stopping logic slightly earlier near the lead.** Don't overshoot or the car brakes at rolling speeds. |
| `NrdrHondaEcuMatchedLong` | OFF | **Nidec, calibrated on the 2019 Pilot.** ON rate-limits the accel command to the ECU ramp rates, applies a speed-dependent coast deadband, and coasts through gas/brake transitions to kill lurch. **This is the single most Pilot-specific "no late jerk" switch.** |
| `NrdrHondaFullBrakeAuthority` | ON | Lets Nidec use the full normalized brake range instead of upstream headroom. Keep ON unless you want reduced authority. |
| `NrdrRoenAccelerationLimits` | ON | Roen ISO planner + Nidec pedal accel envelopes. Affects acceleration ceilings only; does not hurt braking. Keep ON. |
| `HondaLiveLearningGas` | OFF w/ interceptor | While ON, the four Distance PID scales are frozen at 100 %. |
| `LongPidTuneScale*` (Distance 1–4) | 200/100/80/50 % | Scales longitudinal PID feedback (P+I). Only active with a gas interceptor and Live Learning Gas OFF. Changes tracking of the planned accel; **lower scales make the controller arrive at the planned brake more gently.** |
| `StaticFeedforwardLong` | ON | Keeps `kf` unscaled while personality scales scale P+I. |
| `NrdrCruiseOverspeedAllowance` | 0 mph | Only permissive overspeed past set speed; not braking-related. |
| `NrdrCruiseMismatchCorrection` | 100 % | Corrects a fixed 1 mph offset between set and actual cruise speed. |

---

## 4. Honda Pilot 2019 vs common settings

**Pilot 2019 specific (Nidec fingerprints — `HONDA_PILOT` is a
`HondaNidecPlatformConfig`, and it is in the gas-interceptor support set):**

- `NrdrHondaEcuMatchedLong` — explicitly "Calibrated on the 2019 Pilot; other
  Nidec cars may need tuning". This is your car's intended ON switch.
- `NrdrHondaFullBrakeAuthority`, `NrdrRoenAccelerationLimits` — apply to all
  supported Nidec cars with a gas interceptor; defaults (ON/ON) are the
  recommended settings for the Pilot.

**Common across Nidec / all cars:**

- `t_follow_offsets`, `jerk_factors`, `comfort_brake`, `stop_distance`,
  `lead_consumption.*` — generic MPC behavior, safe to use on any car running
  openpilot longitudinal.
- `HondaStoppingDecelRate(Long)`, `HondaStopAccel`, `HondaVEgoStopping/Starting`
  — the stopping phase, common to Honda.

> Do not copy another car's Nidec gas/brake shaping blindly (README ≥ v…  warns
> the same): the LSD/rack and pedal calibration differ. The MPC gap/jerk knobs,
> however, are car-agnostic.

---

## 5. Recommended target for "brake ahead, slow steady"

The standard fix for late creep-braking on approach is a combination that
(much) lengthens the planned gap and smooths accel changes:

1. Set **Relaxed** (or Econ) personality, or add a `t_follow_offset`.
2. Raise `jerk_factors` (a_change + j_ego) ≈ 1.3–2.0 for the personality you
   use — the MPC then must start slowing earlier to keep the motion smooth.
3. Lower `comfort_brake` to 2.0–2.2 and raise `stop_distance` to 6.5–7.5 —
   the plan reserves more room ahead.
4. (Optional, for reactivity) `m2_w_max` 0.5–0.8 + `m2_drel_gate` 50–60 so a
   braking lead is seen immediately.
5. On the 2019 Pilot: turn ON `NrdrHondaEcuMatchedLong`.
6. Soften the final ramp: `HondaStoppingDecelRate` 20–25,
   `HondaStoppingDecelRateLong` 0.2–0.25, optionally raise
   `stopping.proximity_scale_m` to 10–14 and `HondaVEgoStopping/Starting` to
   0.6.

---

## 6. How to change these in the UI (on-device)

### 6.1 Navigation

1. Open the **Settings** app on the comma device.
2. Tap **nrdr** in the settings list → main nrdr page shows three buttons:
   **Lateral Tuning**, **Longitudinal Tuning**, **Special**.
3. Tap **Longitudinal Tuning** to open the panel. Scroll with a swipe/drag;
   the panel opens at the top each time you enter it.

The same rows are mirrored in the Sunnylink app under
**Cruise → nrdr Longitudinal Tuning** if you prefer that surface.

### 6.2 Interaction model

- **Toggles** — tap the switch to flip it. The value is written to the param
  immediately.
- **Options (− value +)** — tap the **+** or **−** button on the right side of
  a row; each tap changes the value by that row's step and saves instantly.
  There is no confirm/OK button.
- Changes take effect within ~0.5 s (nrdr live-params worker polls the
  registry; no reboot needed). Only **Live Learning Gas** is gated offroad —
  the rest of the panel is editable while driving, though nrdr applies lateral
  edits at the next engagement boundary.

### 6.3 Panel rows, top → bottom

Toggles:

| Row | Param | Notes |
| --- | --- | --- |
| Live Learning Gas | `HondaLiveLearningGas` | OFF recommended with gas interceptor; only editable offroad. While ON, Distance 1–4 PID scales are forced 100 % |
| Keep Feedforward Static | `StaticFeedforwardLong` | Keep ON |
| **Nidec ECU-Matched Long** | `NrdrHondaEcuMatchedLong` | **Tap ON for the 2019 Pilot** (calibrated for it) |
| Full Nidec Brake Authority | `NrdrHondaFullBrakeAuthority` | Keep ON |
| Roen Nidec Acceleration Limits | `NrdrRoenAccelerationLimits` | Keep ON |
| Honda Bosch-A Radar | `HondaBoschARadar` | ON by default; disable if tracks look wrong |
| Honda Dashboard Variant B | `NrdrHondaDashVariantB` | Placeholder, no effect |

Options (value, step, what the number means):

| Row | Param | Range / step | Default |
| --- | --- | --- | --- |
| Distance 1 / Aggressive PID Scale | `LongPidTuneScaleAggressive` | 0–500, step 5 (%) | 200 |
| Distance 2 / Standard PID Scale | `LongPidTuneScaleStandard` | 0–500, step 5 (%) | 100 |
| Distance 3 / Relaxed PID Scale | `LongPidTuneScaleRelaxed` | 0–500, step 5 (%) | 80 |
| Distance 4 / Econ PID Scale | `LongPidTuneScaleEcon` | 0–500, step 5 (%) | 50 |
| Set-Speed Overshoot Allowance | `NrdrCruiseOverspeedAllowance` | 0–10, step 1 (mph) | 0 |
| Cruise Mismatch Correction | `NrdrCruiseMismatchCorrection` | 95.0–105.0, step 0.1 (%) | 100.0 |
| Stopping Decel Rate | `HondaStoppingDecelRate` | 0–100, step 1 → /100 (m/s²/s) | 30 |
| Stop Accel | `HondaStopAccel` | −4.00–0.00, step 0.01 (m/s²) | −2.0 |
| Planner Stopping Rate | `HondaStoppingDecelRateLong` | 0.00–5.00, step 0.01 (m/s²/s) | 0.3 |
| vEgo Stopping | `HondaVEgoStopping` | 0.00–3.00, step 0.01 (m/s) | 0.5 |
| vEgo Starting | `HondaVEgoStarting` | 0.00–3.00, step 0.01 (m/s) | 0.5 |

Decimals (Stop Accel, Planner Stopping Rate, vEgo Stopping/Starting, Cruise
Mismatch Correction) use float scaling: **each + / − tap moves by 0.01**, so
e.g. Planner Stopping Rate 0.3 → 0.2 takes 10 taps.

### 6.4 What the UI cannot set

The MPC gap/jerk knobs (`t_follow_offsets`, `jerk_factors`, `comfort_brake`,
`stop_distance`, `lead_consumption.*`, `stopping.*`) have **no UI row**. They
live in `/data/nrdr_long_tune.json` and are edited on the device via SSH:

```sh
python -m openpilot.nrdr.features.longitudinal.long_tune show
python -m openpilot.nrdr.features.longitudinal.long_tune reset        # back to compiled defaults
python -m openpilot.nrdr.features.longitudinal.long_tune set \
  t_follow_offsets.standard=0.3 \
  jerk_factors.standard.a_change=1.4 \
  jerk_factors.standard.j_ego=1.4 \
  comfort_brake=2.2
```

`show` prints the loaded values and any rejected fields; `set` accepts the
dotted keys exactly as written above and clamps out-of-range input.

---

## 7. Three test rounds

Each round is a full config, ordered mild → strong. Apply round 1, drive it,
then move up. Reset with `long_tune reset` and UI defaults if a round feels
wrong. `t_follow_offsets`/`jerk_factors` keys are shown for "standard" — use
the personality you actually drive. **How to operate the panel and where each
row sits is in §6 above** (UI rows are tapped with +/− or the toggle; MPC keys
go through the `long_tune set` CLI).

### Round 1 — Mild: gently earlier, barely changes feel

UI (nrdr Longitudinal Tuning):
- Distance personality: **Relaxed** (or set via driving personality)
- `NrdrHondaEcuMatchedLong` = **ON** (Pilot 2019)
- `HondaStoppingDecelRate` = **25**, `HondaStoppingDecelRateLong` = **0.25**

Tune file (CLI):
```sh
python -m openpilot.nrdr.features.longitudinal.long_tune set \
  t_follow_offsets.standard=0.25 \
  jerk_factors.standard.a_change=1.3 \
  jerk_factors.standard.j_ego=1.3 \
  comfort_brake=2.2 \
  stop_distance=6.5
```

### Round 2 — Moderate: clearly braking ahead, smooth final stop

UI:
- Distance personality: **Econ**
- `NrdrHondaEcuMatchedLong` = **ON**
- `HondaStoppingDecelRate` = **20**, `HondaStoppingDecelRateLong` = **0.2**
- `HondaVEgoStopping` = **0.6**, `HondaVEgoStarting` = **0.6**

Tune file:
```sh
python -m openpilot.nrdr.features.longitudinal.long_tune set \
  t_follow_offsets.standard=0.4 \
  jerk_factors.standard.a_change=1.6 \
  jerk_factors.standard.j_ego=1.6 \
  comfort_brake=2.0 \
  stop_distance=7.5 \
  lead_consumption.m2_w_max=0.6 \
  lead_consumption.m2_drel_gate=50 \
  stopping.proximity_scale_m=12
```

### Round 3 — Strong: maximum early braking + immediate response to a braking lead

UI:
- Distance personality: **Relaxed** (keeps a sensible highway gap while the
  offsets below stretch it further)
- `NrdrHondaEcuMatchedLong` = **ON**
- `NrdrHondaFullBrakeAuthority` = **ON**
- `HondaStoppingDecelRate` = **18**, `HondaStoppingDecelRateLong` = **0.18**
- `HondaVEgoStopping` / `HondaVEgoStarting` = **0.65** / **0.65**

Tune file:
```sh
python -m openpilot.nrdr.features.longitudinal.long_tune set \
  t_follow_offsets.standard=0.5 \
  jerk_factors.standard.a_change=2.0 \
  jerk_factors.standard.j_ego=2.0 \
  comfort_brake=2.0 \
  stop_distance=7.5 \
  lead_consumption.m2_w_max=0.8 \
  lead_consumption.m2_alead_deadband=0.4 \
  lead_consumption.m2_drel_gate=60 \
  lead_consumption.m3_b_eff_max=4.0 \
  lead_consumption.m3_alead_gate=-0.35 \
  stopping.proximity_scale_m=14
```

### How to read the result

Braking "ahead" looks like this in logs: speed starts falling while the lead is
still 30–50 m away (not 10 m), `longitudinalPlan.source` stays on `lead0`,
decel climbs gradually (jerk-limited) instead of slamming on, and the final
`vEgo → 0` ramp is long and flat with no grab. If the car now keeps too much
distance, back `t_follow_offsets` down before touching `comfort_brake`; if a
round feels mushy at stops, reduce `proximity_scale_m` back toward 8–10.

---

## 8. Source map

| File | What it defines |
| --- | --- |
| `openpilot/nrdr/features/longitudinal/longitudinal_mpc.py` | MPC personality tables, lead-trajectory blending, effective brake |
| `openpilot/nrdr/features/longitudinal/longitudinal_planner.py` | Cruise overspeed, Roen accel limits, launch accel |
| `openpilot/nrdr/features/longitudinal/long_tune.py` | The `/data/nrdr_long_tune.json` schema, defaults, ranges, CLI |
| `openpilot/nrdr/features/longitudinal/longcontrol.py` | Stop/start state machine, PID + personality scales, stopping dispatch |
| `openpilot/nrdr/features/longitudinal/longitudinal_stopping.py` | Final-creep ramp math (speed + proximity scaling) |
| `openpilot/selfdrive/controls/lib/longitudinal_mpc_lib/long_mpc.py` | T_FOLLOW/JERK base values, cost weights, MPC glue |
| `openpilot/nrdr/params/specs.py` | Canonical registry defaults for all UI params |
| `openpilot/nrdr/params/snapshots.py` | Which params reach controlsd (CONTROL_GROUPS) vs plannerd (PLANNER_GROUPS) |
| `openpilot/nrdr/ui/settings/longitudinal_tuning.py` | On-device Longitudinal Tuning panel |
| `openpilot/nrdr/ui/sunnylink/pages/cruise.yaml` | Same settings in the Sunnylink app |
| `openpilot/nrdr/car/opendbc.py` | Bridge that feeds param values into the opendbc Nidec carcontroller |