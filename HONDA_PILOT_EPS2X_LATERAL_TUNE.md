# Honda Pilot (2019, EPS 2X) — Lateral Tune

Target: no steering vibration below 25 mph and steady, no-wobble steering at
highway speed after flashing `39990-TG7-A060_2X.rwd` (2× LKAS torque authority +
steer-to-standstill).

## Why the default 150% tune vibrates

The Nidec EPS is torque-commanded, so the plant openpilot closes the loop around
is *torque → angle* — a double integrator. Pure proportional feedback on a double
integrator is an undamped oscillator:

- Below ~10 mph tire self-aligning torque (the only natural damping) goes to zero,
  the feedforward (`kf·v²`) dies, and the integrator freezes — the wheel steers on
  **P alone and rings**.
- Raising P/I/F everywhere to 150% amplifies that ring; it does not add damping.
- Rate Damping (D) at stock 30% with a 30 mph fade means only ⅓ of the D term is
  active at 20 mph.
- The 2× firmware doubles the plant loop gain on top of all of this.
- Highway wobble comes from 150% P/I hunting plus Center Boost stacking +50% P
  near center (effective ~225% P band there).

The fix is damping (D), not gain: lower P/I/F back toward default and raise the D
term it was missing.

## Controller Tuning Dungeon

| Setting | Before | After | Min | Max | Why |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Low Speed P (<25 mph) | 150% | **100%** | 0 | 500 | P drives the low-speed ring; D buys back crispness |
| Low Speed I (<25 mph) | 150% | **80%** | 0 | 500 | I winds up and weaves at low speed |
| Low Speed F (<25 mph) | 150% | **100%** | 0 | 500 | kf·v² is negligible below 25 mph |
| Standard P (25–50 mph) | 150% | **120%** | 0 | 500 | taper back toward default |
| Standard I (25–50 mph) | 150% | **100%** | 0 | 500 | less mid-speed hunting |
| Standard F (25–50 mph) | 150% | **100%** | 0 | 500 | authority already doubled by firmware |
| Highway P (50 mph+) | 150% | **110%** | 0 | 500 | over-sharp corrections = wobble |
| Highway I (50 mph+) | 150% | **80–100%** | 0 | 500 | biggest weave contributor at speed |
| Highway F (50 mph+) | 150% | **100%** | 0 | 500 | authority already doubled by firmware |
| Rate Damping (D) Strength | 30% | **75%** | 0 | 300 | the actual fix for sub-25 mph vibration |
| Rate Damping Fade-Out Speed | 30 mph | **40 mph** | 0 | 60 | full D at 20 mph (now only ⅓ active) |
| Center Boost | 0.50 | **0.35** | 0.00 | 5.00 | it multiplies P near center (150→225% now) |
| Center Boost Threshold | 3.00° | 3.00° | 0.00 | 10.00 | fine as-is |
| Center Boost Min Speed | 40 mph | **50 mph** | 0 | 80 | keeps boost off mid-speed busy zones |
| Predictive Lateral Stiction | Off | Off | N/A | N/A | optional later for overshoot hunting |

## Steer Filters

| Setting | Before | After | Min | Max | Why |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Low Pass Filter (tau) | On | **On** | N/A | N/A | keep |
| Low Pass Filter Tau (<25 mph) | 0.10 | **0.06–0.08** | 0.00 | 5.00 | 0.10 is at the lag-oscillation threshold at low speed |
| Standard Tau (25–50 mph) | 0.10 | **0.08** | 0.00 | 5.00 | slightly less lag mid-speed |
| Highway Tau (50 mph+) | 0.05 | **0.05** | 0.00 | 5.00 | fine as-is |
| Legacy Steer Delta Limiter | Off | **Off** | N/A | N/A | superseded by LPF + notch |

## Round 2 (after road test — still vibrating <25 mph, wobble 25–50 mph)

Round 1 tuning alone did not fix it. Code audit found the real culprits, and all
three are **ON by default** and live in the device param page (not the Dungeon):

- **`NrdrTuneLearner` (default ON)** — accumulates a torque-trim map from driving
  and adds it on top of the PID output (`tune_learner.py`, applied at
  `latcontrol_pid.py:322`). The map was learned during the 150%-gain oscillating
  drives, so it now fights the new PID. Turn **OFF** and trigger
  `NrdrTuneLearnerReset` once to wipe the stale map.
- **`NrdrLearnStiffness` (default ON)** / **`NrdrLearnAngleOffset` (default ON)** —
  live-learned model inputs; mislearned values distort the desired angle so the
  PID keeps re-correcting → 25–50 mph wobble. Turn **OFF** (pins static).
- **Rate Damping fade** — with a 40 mph fade, D is zero across most of the 25–50
  band. The fade is linear, `(fade − vEgo)/fade`, so D must span the wobble band.

| Setting (key) | Before | After | Why |
| :--- | :---: | :---: | :--- |
| NrdrTuneLearner | ON | **OFF** | removes learned-trim overlay |
| NrdrTuneLearnerReset | — | **once** | wipes the polluted learned map |
| NrdrLearnStiffness | ON | **OFF** | pins model stiffness to static 1.0 |
| NrdrLearnAngleOffset | ON | **OFF** | pins angle offset to 0 |
| Rate Damping (D) Strength | 75% | **100%** | more damping; 2× firmware needs it |
| Rate Damping Fade-Out Speed | 40 mph | **55 mph** | covers the whole 25–50 band with D |
| Standard P (25–50) | 120% | **100%** | less hunting in the wobble band |
| Standard I (25–50) | 100% | **60%** | I winds up → weave |
| Standard Tau (25–50) | 0.08 | **0.10** | more smoothing; D now covers the band |
| Predictive Lat Stiction | OFF | try **ON** if buzz remains | one-sided torque removal near settled target |

If the sub-25 mph ring still persists after a 15-min steady drive: drop Low P
from 100 → 80 (not up), or push D to 150. Enable `NrdrLatStiction` only if the
low-speed buzz feel remains once the learner is off.

## Override Tuning

Override does not fix the vibration — it only reacts when the torque sensor
decides *you* are steering. During normal engaged driving it changes no torque.
But on a 2×-authority EPS, ringing torque spikes can trip the override threshold,
and a false trigger produces a sudden hard torque drop (0.10 s fade, 0% retain)
that reads as jerky steering.

| Setting | Before | After | Min | Max | Why |
| :--- | :---: | :---: | :---: | :---: | :--- |
| Increase Driver Override Hysteresis | Off | **On** | N/A | N/A | doubles threshold; fewer false drops from torque noise |
| Driver Override Threshold | 1400 | **1600–2000** | 100 | 5000 | headroom above doubled-firmware torque noise (nrdr profile uses 2000) |
| Override Threshold Center Boost | 1000 | **1200** | 100 | 5000 | keep below the main threshold; center band triggers most |
| Pass-through assist torque on override | On | **On** | N/A | N/A | keeps any override returning to normal feel |
| Override Torque Fade Down | 0.10 s | **0.10–0.20 s** | 0.00 | 10.00 | slow only if false drops remain; 0.10 s is a hard chop |
| Override Torque Fade Up | 0.10 s | **0.30–0.50 s** | 0.00 | 10.00 | fast re-engage reads as a jerk after you let go |
| Override Torque Retain | 0% | **0%** | 0 | 100 | full release is correct once it is a real override |

Recommended starting point: **Hysteresis On, Threshold 1600–2000, Center-Boost
Threshold 1200, Fade Up 0.4 s**, fade down 0.10 s, retain 0%. Only touch these if
you actually see the wheel drop torque mid-turn — the ring is fixed with Rate
Damping/P, not here.

## If a ~7 Hz growl remains

Enable the notch filter (Lateral Tuning → Steer Filters / `HondaNotchEnabled`):

| Setting | Value |
| :--- | :---: |
| HondaNotchEnabled | On |
| Notch Frequency | 7.5 Hz |
| Notch Q | 1.5 |

## Tuning order

1. Set Low band **P 100 / I 80 / F 100**, **D 75 / fade 40**, LPF low tau **0.06**.
   Drive below 25 mph.
2. Under 25 mph flat now → only if a hint of ring remains, raise D up to 100 and/or
   fade to 45. **Do not raise low-band P.**
3. Then Highway: **P 110 / I 80–100**, **Center Boost 0.35 @ 50 mph**. Drive 60+
   and confirm it stays steady with no hunting.
4. If a ~7 Hz growl still lingers at speed, enable the notch (above).

The 2× firmware already doubles authority — you don't need 150% gain to steer;
you need the damping (D) the gain doesn't provide.