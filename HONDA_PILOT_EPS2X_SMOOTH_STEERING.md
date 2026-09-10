# Honda Pilot (2019, EPS 2X) — Smooth-Steering Tune Campaign

Target: no steering vibration below 25 mph and steady, no-wobble steering at all
speeds after flashing `39990-TG7-A060_2X.rwd` (2× LKAS torque authority +
steer-to-standstill).

Worked example of the tune. Apply Round 1 → road test → Round 2 → road test →
Round 3 if more smoothness is still wanted. Each round builds on the previous —
set the later round's full table, not just the diff, so state is explicit.

## Why the stock 150% tune vibrates

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
- Mid/high-speed wobble comes from elevated P/I hunting plus Center Boost stacking
  +50% P near center.

The fix is damping (D), not gain: lower P/I/F back toward default and raise the D
term it was missing.

---

## Round 1 — baseline desmooth

Round-1 result on the Pilot: **reduced the sub-25 mph vibration a lot; a small
residual buzz remains below 25 mph and it is not yet fully smooth across the
25–50 band.**

### Controller Tuning Dungeon

| Setting | Stock | Round 1 | Min | Max |
| :--- | :---: | :---: | :---: | :---: |
| Low Speed P (<25 mph) | 150% | **100%** | 0 | 500 |
| Low Speed I (<25 mph) | 150% | **80%** | 0 | 500 |
| Low Speed F (<25 mph) | 150% | **100%** | 0 | 500 |
| Standard P (25–50 mph) | 150% | **120%** | 0 | 500 |
| Standard I (25–50 mph) | 150% | **100%** | 0 | 500 |
| Standard F (25–50 mph) | 150% | **100%** | 0 | 500 |
| Highway P (50 mph+) | 150% | **110%** | 0 | 500 |
| Highway I (50 mph+) | 150% | **80%** | 0 | 500 |
| Highway F (50 mph+) | 150% | **100%** | 0 | 500 |
| Rate Damping (D) Strength | 30% | **75%** | 0 | 300 |
| Rate Damping Fade-Out Speed | 30 mph | **40 mph** | 0 | 60 |
| Center Boost | 0.50 | **0.35** | 0.00 | 5.00 |
| Center Boost Threshold | 3.00° | 3.00° | 0.00 | 10.00 |
| Center Boost Min Speed | 40 mph | **50 mph** | 0 | 80 |
| Predictive Lateral Stiction | Off | **Off** | N/A | N/A |

### Steer Filters

| Setting | Stock | Round 1 | Min | Max |
| :--- | :---: | :---: | :---: | :---: |
| Low Pass Filter (tau) | On | **On** | N/A | N/A |
| Low Pass Filter Tau (<25 mph) | 0.10 | **0.06** | 0.00 | 5.00 |
| Standard Tau (25–50 mph) | 0.10 | **0.08** | 0.00 | 5.00 |
| Highway Tau (50 mph+) | 0.05 | **0.05** | 0.00 | 5.00 |
| Legacy Steer Delta Limiter | Off | **Off** | N/A | N/A |

### Override Tuning

| Setting | Stock | Round 1 | Min | Max |
| :--- | :---: | :---: | :---: | :---: |
| Increase Driver Override Hysteresis | Off | **On** | N/A | N/A |
| Driver Override Threshold | 1400 | **1600** | 100 | 5000 |
| Override Threshold Center Boost | 1000 | **1200** | 100 | 5000 |
| Pass-through assist torque on override | On | **On** | N/A | N/A |
| Override Torque Fade Down | 0.10 s | **0.10 s** | 0.00 | 10.00 |
| Override Torque Fade Up | 0.10 s | **0.40 s** | 0.00 | 10.00 |
| Override Torque Retain | 0% | **0%** | 0 | 100 |

---

## Round 2 — kill the learners, more D, tame Standard band

Round-2 reasoning (only try after Round 1 road test): the residual vibration is
not the knobs you already turned — it comes from **three default-ON settings that
live in the device param page, not the Tuning Dungeon**, which were fighting
Round 1:

- **`NrdrTuneLearner` (default ON)** — accumulates a torque-trim map from driving
  and adds it on top of the PID output (`tune_learner.py`, applied at
  `latcontrol_pid.py:322`). The map was learned during the 150%-gain oscillating
  drives, so it now pushes the wheel in ways the new PID isn't asking for. Turn
  **OFF** and trigger `NrdrTuneLearnerReset` once to wipe the stale map.
- **`NrdrLearnStiffness` (default ON)** / **`NrdrLearnAngleOffset` (default ON)** —
  live-learned model inputs; mislearned values distort the desired angle so the
  PID keeps re-correcting → 25–50 mph wobble. Turn **OFF** (pins static).
- **Rate Damping fade** — at 40 mph fade, D is near zero across most of the 25–50
  band (fade is linear, `(fade − vEgo)/fade`). D must span the wobble band.

### Full Round-2 table (set all of these)

**Controller Tuning Dungeon**

| Setting | Round 1 | Round 2 | Min | Max |
| :--- | :---: | :---: | :---: | :---: |
| Low Speed P (<25 mph) | 100% | **100%** | 0 | 500 |
| Low Speed I (<25 mph) | 80% | **80%** | 0 | 500 |
| Low Speed F (<25 mph) | 100% | **100%** | 0 | 500 |
| Standard P (25–50 mph) | 120% | **100%** | 0 | 500 |
| Standard I (25–50 mph) | 100% | **60%** | 0 | 500 |
| Standard F (25–50 mph) | 100% | **100%** | 0 | 500 |
| Highway P (50 mph+) | 110% | **100%** | 0 | 500 |
| Highway I (50 mph+) | 80% | **60%** | 0 | 500 |
| Highway F (50 mph+) | 100% | **100%** | 0 | 500 |
| Rate Damping (D) Strength | 75% | **100%** | 0 | 300 |
| Rate Damping Fade-Out Speed | 40 mph | **55 mph** | 0 | 60 |
| Center Boost | 0.35 | **0.35** | 0.00 | 5.00 |
| Center Boost Threshold | 3.00° | 3.00° | 0.00 | 10.00 |
| Center Boost Min Speed | 50 mph | **50 mph** | 0 | 80 |
| Predictive Lateral Stiction | Off | **Off** | N/A | N/A |

**Steer Filters**

| Setting | Round 1 | Round 2 | Min | Max |
| :--- | :---: | :---: | :---: | :---: |
| Low Pass Filter (tau) | On | **On** | N/A | N/A |
| Low Pass Filter Tau (<25 mph) | 0.06 | **0.06** | 0.00 | 5.00 |
| Standard Tau (25–50 mph) | 0.08 | **0.10** | 0.00 | 5.00 |
| Highway Tau (50 mph+) | 0.05 | **0.05** | 0.00 | 5.00 |
| Legacy Steer Delta Limiter | Off | **Off** | N/A | N/A |

**Device param page (not in the Dungeon)**

| Setting (key) | Round 1 | Round 2 | Why |
| :--- | :---: | :---: | :--- |
| NrdrTuneLearner | ON | **OFF** | removes learned-trim overlay |
| NrdrTuneLearnerReset | — | **once** | wipes the polluted learned map |
| NrdrLearnStiffness | ON | **OFF** | pins model stiffness to static 1.0 |
| NrdrLearnAngleOffset | ON | **OFF** | pins angle offset to 0 |

**Road-test rule:** after Round 2, drive a 15-min steady route covering several
speeds and curve radii before judging — the learner removal takes a few minutes
to stop influencing.

---

## Round 2.1 — low-band only (Round 2 feels good, but wobble remains <25 mph)

Round-2 result on the Pilot: **the Standard (25–50) band feels good; only a
slow wobble persists below 25 mph.** This is a slow sway, not a high-frequency
buzz — so it is I-term wind-up and P overshoot near center at low speed, not a
resonance. D is already at full strength at low speed (fade 55), and the notch
filter (`HondaNotchEnabled/Freq/Q`) is **not wired into this build** (params
exist but have no code consumer), so the fix is to reduce the *source* of the
sway rather than add more damping.

### Round 2.1 deltas — change only these, keep everything else at Round 2

**Controller Tuning Dungeon**

| Setting | Round 2 | Round 2.1 | Min | Max |
| :--- | :---: | :---: | :---: | :---: |
| Low Speed I (<25 mph) | 80% | **50%** | 0 | 500 |
| Low Speed P (<25 mph) | 100% | **85%** | 0 | 500 |
| Low Speed F (<25 mph) | 100% | **100%** | 0 | 500 |

**Steer Filters**

| Setting | Round 2 | Round 2.1 | Min | Max |
| :--- | :---: | :---: | :---: | :---: |
| Low Pass Filter Tau (<25 mph) | 0.06 | **0.08** | 0.00 | 5.00 |

**Keep exactly as Round 2** (do not touch): Standard P100/I60/F100, Highway
P100/I60/F100, Rate Damping (D) Strength **100**, D Fade-Out **55 mph**, Standard
tau **0.10**, Highway tau **0.05**, Center Boost **0.35 @ 50 mph**, and the three
device keys OFF (`NrdrTuneLearner`, `NrdrLearnStiffness`, `NrdrLearnAngleOffset`).

**If low band is still wobbly after Round 2.1:** enable **Predictive Lateral
Stiction (`NrdrLatStiction`)** — it is purpose-built for exactly this: it tapers
torque as the wheel closes on a stable target and holds it, killing the
low-speed settle-and-ring around center (it only ever removes torque, never
adds).

---

## Round 3 — maximum smoothness (use only if Round 2 is still not smooth enough)

Round-3 reasoning: Round 2 already removes the learned overlay and covers the
25–50 band with D. This round sacrifices some crispness for smoothness — more D,
a stronger low-speed low-pass, damping fade pulled across the whole speed range,
and the one-sided torque-removal stiction overlay to let the wheel settle without
ringing.

### Full Round-3 table (set all of these)

**Controller Tuning Dungeon**

| Setting | Round 2 | Round 3 | Min | Max |
| :--- | :---: | :---: | :---: | :---: |
| Low Speed P (<25 mph) | 100% | **80%** | 0 | 500 |
| Low Speed I (<25 mph) | 80% | **50%** | 0 | 500 |
| Low Speed F (<25 mph) | 100% | **100%** | 0 | 500 |
| Standard P (25–50 mph) | 100% | **90%** | 0 | 500 |
| Standard I (25–50 mph) | 60% | **50%** | 0 | 500 |
| Standard F (25–50 mph) | 100% | **100%** | 0 | 500 |
| Highway P (50 mph+) | 100% | **100%** | 0 | 500 |
| Highway I (50 mph+) | 60% | **50%** | 0 | 500 |
| Highway F (50 mph+) | 100% | **100%** | 0 | 500 |
| Rate Damping (D) Strength | 100% | **150%** | 0 | 300 |
| Rate Damping Fade-Out Speed | 55 mph | **60 mph** | 0 | 60 |
| Center Boost | 0.35 | **0.30** | 0.00 | 5.00 |
| Center Boost Threshold | 3.00° | **4.00°** | 0.00 | 10.00 |
| Center Boost Min Speed | 50 mph | **55 mph** | 0 | 80 |
| Predictive Lateral Stiction | Off | **On** | N/A | N/A |

**Steer Filters**

| Setting | Round 2 | Round 3 | Min | Max |
| :--- | :---: | :---: | :---: | :---: |
| Low Pass Filter (tau) | On | **On** | N/A | N/A |
| Low Pass Filter Tau (<25 mph) | 0.06 | **0.10** | 0.00 | 5.00 |
| Standard Tau (25–50 mph) | 0.10 | **0.12** | 0.00 | 5.00 |
| Highway Tau (50 mph+) | 0.05 | **0.08** | 0.00 | 5.00 |
| Legacy Steer Delta Limiter | Off | **Off** | N/A | N/A |

**Device param page (keep Round 2 state)**

| Setting (key) | Round 2 | Round 3 |
| :--- | :---: | :---: |
| NrdrTuneLearner | OFF | **OFF** |
| NrdrLearnStiffness | OFF | **OFF** |
| NrdrLearnAngleOffset | OFF | **OFF** |

**Road-test rule:** Round 3 makes the low-pass tau ≥ 0.10 (0.10 low, 0.12
standard), which is the edge of lag-induced oscillation. If it feels lazy instead
of smooth, back the taus down to Round-2 values and keep the higher D — D is the
safe smoothness, lag is the risky one.

---

## Tuning order / decision tree

```
Round 1 ──→ road test
  ├─ still buzzy <25 mph or wobble 25–50 ──→ Round 2 ──→ road test (15 min)
  │     ├─ Standard good but wobble <25 mph ──→ Round 2.1
  │     │     └─ still wobbly <25 mph ──→ enable Predictive Lateral Stiction
  │     ├─ feel still busy everywhere ──→ Round 3
  │     └─ clean ──→ done
  └─ clean ──→ done
```

1. Round 1 table → drive below 25 mph and in the 25–50 band.
2. If residual buzz/wobble persists → Round 2 table + device-key OFF states →
   drive a 15-min steady route before judging.
3. If still not smooth enough → Round 3 table (keep Round-2 learner state).
   If it feels lazy instead of smooth, revert taus to Round-2 and keep D 150.

The 2× firmware already doubles authority — you don't need 150% gain to steer;
you need the damping (D) the gain doesn't provide.