# Cold Boot Fixes

Documentation of fixes for issues encountered during device cold boot that prevented or disrupted engagement when starting the car and placing it in Drive.

## Problem Overview

On a cold boot (device starting while the engine is turned on and put in D), openpilot reported failures and disengaged shortly after engage:

- **"Process Not Running"** NO_ENTRY blocking engagement (`micd`, `loggerd`, `soundd`, etc. still starting).
- A **barrage of transient NO_ENTRY errors** right after initialization (commIssue, posenetInvalid, locationdTemporaryError, paramsdTemporaryError) raised while freshly-started services were still publishing invalid data.
- A brief **false "TEMP HIGH"** sidebar metric on boot before temperature readings settled.
- A **Gas Pedal Interceptor Fault** immediate-disengage triggered by a brief FAULT_TIMEOUT during boot process churn.

## Commits

### 9514844fbe — auto-restart micd/soundd and grace-wait for process startup

**Files:** `openpilot/system/manager/process_config.py`, `openpilot/selfdrive/selfdrived/selfdrived.py`

**Problem:** `micd` and `soundd` could die mid-drive and were never relaunched by the manager, leaving a "Process Not Running" NO_ENTRY event that blocked engagement for the entire drive. (Neither process had `restart_if_crash`, and `PythonProcess.start()` returns early while `self.proc is not None`, so the manager never relaunched a process that quit mid-session.)

**Fix:**
- Enabled `restart_if_crash=True` on `micd` and `soundd` so the manager relaunches them within ~1s of a crash.
- Added an initial `PROCESS_STARTUP_WAIT` startup grace so engagement waits (shown as non-failing "System Initializing") for genuinely-required processes that are slow to start, rather than immediately reporting `processNotRunning`.

### b54cc11e7b — suppress transient boot faults during startup grace

**File:** `openpilot/selfdrive/selfdrived/selfdrived.py`

**Problem:** Cold boot fires a barrage of engagement-blocking NO_ENTRY errors (`commIssue`, `commIssueAvgFreq`, `posenetInvalid`, `locationdTemporaryError`, `paramsdTemporaryError`, `processNotRunning`) while freshly started services still publish invalid data.

**Fix:**
- Added a startup grace countdown (decremented every frame, so it always expires) that collapses any transient "system-not-ready" fault in `STARTUP_TRANSIENT_EVENTS` into a single "System Initializing" no-entry wait.
- The masking is **centralized by fault class** (`mask_transient_startup_events`), so it also covers transient faults not yet seen on any hardware, while real safety/hardware faults (cameraMalfunction, usbError, controlsMismatch, overheat, lowMemory, canBusMissing, etc.) are deliberately never masked.

### f7a42ea360 — hold thermal status at ok during boot to avoid false TEMP HIGH

**File:** `openpilot/system/hardware/hardwared.py`

**Problem:** On a cold boot the temperature sensors can briefly spike, flipping `thermalStatus` off `ok`, which makes the sidebar TEMP metric flash red "HIGH" until the reading settles.

**Fix:**
- Added `THERMAL_SETTLE_GRACE = 10s`; holds `thermalStatus` at `ok` during the settle window after the hardware thread starts, so the TEMP HIGH alert only reflects a real sustained temperature rather than a transient boot spike.

### f72b1ea3bf — tolerate gas interceptor timeouts during boot and align startup grace

**Files:** `openpilot/sunnypilot/selfdrive/car/car_specific.py`, `openpilot/selfdrive/selfdrived/selfdrived.py`

**Problem:** During a cold boot, the manager restarting processes can briefly pause the gas interceptor keepalive, making the pedal interceptor report `FAULT_TIMEOUT` (STATE 5) for a few hundred ms. Because the interceptor had been seen healthy, the pre-existing code faulted immediately, causing an `IMMEDIATE_DISABLE` `gasInterceptorFault` and a hard disengage shortly after engage.

**Fix:**
- `GAS_INTERCEPTOR_STARTUP_GRACE_FRAMES`: 10s → **45s** (covers the cold-boot window from onroad start).
- Added `GAS_INTERCEPTOR_TRANSIENT_GRACE_FRAMES` (2s): brief `FAULT_TIMEOUT`/`FAULT_STARTUP` (STATE 4/5) streaks up to 2s are tolerated while inside the 45s startup window.
- Anything not STATE 4/5, any streak longer than 2s, or anything after the 45s window still faults immediately (safety preserved).
- Aligned `PROCESS_STARTUP_WAIT` to **45s** so the System Initializing wait and the interceptor grace cover the same boot window.

## Current Startup Constants

| Constant | Value | Where |
|----------|-------|-------|
| `PROCESS_STARTUP_WAIT` | 45s | `selfdrived.py` |
| `THERMAL_SETTLE_GRACE` | 10s | `hardwared.py` |
| `GAS_INTERCEPTOR_STARTUP_GRACE_FRAMES` | 45s | `car_specific.py` |
| `GAS_INTERCEPTOR_TRANSIENT_GRACE_FRAMES` | 2s | `car_specific.py` |

## Measurement Baseline

Measured from on-road logs (swaglog STATUS_PACKET + rlog) on the test device:

- Cold-boot transient faults (commIssue/posenet/locationd/paramsd) clear by **11.0–15.4s** after startup.
- Peak `maxTempC` during drives reached **~73–76°C**; `thermalStatus` stayed `ok` all day, no thermal blocks.
- Gas interceptor FAULT_TIMEOUT seen in a 0.73s keepalive gap at ~31.8s during boot churn.

The 45s windows comfortably cover these measured values with margin while still surfacing genuine faults afterwards.

## Related References

- `openpilot/system/manager/process.py` — `ensure_running` / `restart_if_crash` handling.
- `openpilot/sunnypilot/selfdrive/car/car_specific.py` — gas interceptor fault logic.
- `openpilot/system/hardware/hardwared.py` — thermal status computation and bands.
- `openpilot/selfdrive/selfdrived/selfdrived.py` — startup grace and transient-event masking.