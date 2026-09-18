# Cold Boot Fixes — Port Status

Status of porting the cold-boot fixes from `nrdr-nightly-0914` (commits
`9514844fbe`, `b54cc11e7b`, `f7a42ea360`, `f72b1ea3bf`) into the current
`nrdr-nightly` codebase (openpilot v2026.003.000 base), plus two follow-up
cold-boot fixes derived from analyzing the `commalogs/0919` device logs
(Controls Mismatch boot race and a false Temperature-Too-High alert).

- Branch: `nrdr-nightly`
- CHANGES ARE NOT COMMITTED / NOT PUSHED.
- Approach: logic re-implemented against the current base (a git cherry-pick was
  **not** possible — the two branches have rewritten/rebased upstream history and
  share no merge base; the 0914 diffs also do not apply cleanly because upstream
  restructured parts of this area).

## Source of truth

Documented behavior: `cold_boot_fixes.md` (present on both branches).

## What was aligned and how

### 1. `9514844fbe` — auto-restart micd/soundd + startup grace for process startup

Files: `openpilot/system/manager/process.py`, `openpilot/system/manager/process_config.py`,
`openpilot/selfdrive/selfdrived/selfdrived.py`

| Piece | nrdr-nightly-0914 | Applied on nrdr-nightly |
|-------|-------------------|-------------------------|
| `restart_if_crash` on `micd`, `soundd` | `PythonProcess(..., restart_if_crash=True)` — mechanism already existed in base `process.py` | `restart_if_crash` did **not** exist in current `process.py` (upstream replaced it with `wait_for_ready`). Re-introduced: class attr `restart_if_crash = False`, `ManagerProcess.restart()`, `PythonProcess(..., restart_if_crash=False)` kwarg, and crash-relaunch branch in `ensure_running()` (`p.proc is not None and not p.proc.is_alive()` → `p.restart()`, ~1s cadence). Set `restart_if_crash=True` on `micd`/`soundd` in `process_config.py`. |
| `wait_for_ready` on `micd`/`soundd` | absent in 0914 base | **Kept as-is** (`wait_for_ready=True`). Upstream addition; it only gates `is_healthy()` on a ready signal and does not conflict with crash restart. |
| `PROCESS_STARTUP_WAIT` grace | 90s → 30s → **45s** | **45s** constant + comment added in `selfdrived.py`; countdown starts at `self.initialized = True` in `data_sample()`. |

Final value chosen: 45s (this is the final state of the 0914 branch, aligned with
the interceptor grace).

### 2. `b54cc11e7b` — suppress transient boot faults during startup grace

File: `openpilot/selfdrive/selfdrived/selfdrived.py`

| Piece | Applied |
|-------|---------|
| `STARTUP_TRANSIENT_EVENTS` set (`commIssue`, `commIssueAvgFreq`, `processNotRunning`, `selfdrivedLagging`, `modeldLagging`, `posenetInvalid`, `locationdTemporaryError`, `paramsdTemporaryError`, `sensorDataInvalid`, `radarTempUnavailable`) | Added verbatim; all event names verified present in the current cereal/event map. |
| Per-frame countdown `self.process_startup_wait_left = max(0., ... - DT_CTRL)` | Added after `num_events = len(self.events)` in `update_events()` — same position as 0914. |
| `self.mask_transient_startup_events(...)` called before `self.icbm.run(...)` | Same position as 0914. Masking runs inside `update_events()`, before `state_machine.update()` in `step()`, so engagement decisions see the masked set. |
| `mask_transient_startup_events()` method (`remove` transient events, add single `selfdriveInitializing`) | Added before `update_alerts()`. `Events.add/remove/has` API verified current (`EventsBase` in `sunnypilot/.../events_base.py`). |

### 3. `f7a42ea360` — hold thermal status at ok during boot

File: `openpilot/system/hardware/hardwared.py`

| Piece | Applied |
|-------|---------|
| `THERMAL_SETTLE_GRACE = 10.` | Added near top-level constants. |
| `thermal_settle_start = time.monotonic()` | Added at hardware_thread setup (before `params = Params()`), matching 0914 placement. |
| Hold `thermal_status = ThermalStatus.ok` during settle window | Placed after the full band transition block (and after the `is_offroad_for_5_min` / `OFFROAD_DANGER_TEMP` critical override) and **before** the `# **** starting logic ****` block, so the settle hold also covers the `device_temp_engageable` startup condition. |

### 4. `f72b1ea3bf` — tolerate gas interceptor timeouts during boot

File: `openpilot/sunnypilot/selfdrive/car/car_specific.py`, `openpilot/selfdrive/selfdrived/selfdrived.py`

| Piece | Applied |
|-------|---------|
| `GAS_INTERCEPTOR_STARTUP_GRACE_FRAMES` 10s → **45s** | Done. |
| `GAS_INTERCEPTOR_TRANSIENT_GRACE_FRAMES = int(2. / DT_CTRL)` | Added. |
| State tracking `gas_interceptor_startup_frames`, `gas_interceptor_fault_frames` | Added; startup frame increments every `update()`, fault frames track consecutive non-zero states. |
| Transient tolerance: `in_startup and state in (4,5) and fault_frames <= transient_grace` gates the `gas_interceptor_healthy` fault branch | Done, byte-identical logic to 0914 (this file was unchanged between the branches, diff applied cleanly). |
| `PROCESS_STARTUP_WAIT` | 45s (see item 1). |

### 5. Controls Mismatch on cold boot — wait for the safety-mode handoff

File: `openpilot/selfdrive/selfdrived/selfdrived.py`

Found from `commalogs/0919` rlogs: on a cold boot the panda legitimately stays in
a non-car safety mode (**ELM327** for OBD fingerprinting or **NO_OUTPUT** when
offroad) until pandad has pushed the car's real safety config (`hondaNidec`/4/1024
for HONDA_PILOT), which only happens after `card` sets **`ControlsReady`**. The old
check compared the panda against `carParams.safetyConfigs` after a fixed 10s grace
and had no readiness gate, so starting the engine / going into drive while the
device was still booting raised `controlsMismatch` (IMMEDIATE_DISABLE + NO_ENTRY)
for the whole pre-handoff window (up to 18-20s in the logs; first event fired at
exactly the 10s grace expiry; `enabled` was always `False`, so the
`mismatch_counter` path was never involved).

| Piece | Applied |
|-------|---------|
| `handoff_ready = self.params.get_bool("FirmwareQueryDone") and self.params.get_bool("ControlsReady")` | Added per `update_events()` before the panda loop — the exact two params pandad requires before pushing the car safety mode. |
| `self.handoff_ready_frames` | Counts update frames while handoff_ready is true (reset otherwise); the `safety_mismatch` and `safetyRxChecksInvalid` branches require `handoff_ready_frames*DT_CTRL > 10.` — a 10s grace measured from the moment pandad *has what it needs*, not from process start. On a cold boot card's interface init can take ~40s (observed), so a fixed-from-start grace is not enough; the rebased window covers the ~1-2s the safety-mode push itself takes while still catching a genuinely stuck panda within seconds. |
| `mismatch_counter >= 200` branch | **Untouched** — openpilot enabled while a panda refuses `controlsAllowed` is a real-time disagreement, not a boot artifact. |

Validation against today's on-device segments (device running this branch, car-on
boots at 09-20, `commalogs` pulled over SSH):

| Segment | Kind | CM samples (prev) | CM samples (fixed) |
|---|---|---|---|
| `00000085--…--0` | boot | 309 | **0** |
| `00000086--…--0` | boot | 339 | **0** |
| `00000085--…--1` | mid-drive revert to `noOutput` | 1 | 1 (kept) |

Known remaining behavior: pandad closes the relay to `NO_OUTPUT` on drive-end/park
(`pandad.cc` teardown), which can still briefly flag a revert after
`handoff_ready`; unchanged from before.

### 6. Temperature Too High false positive — reject temperature read spikes

File: `openpilot/system/hardware/hardwared.py`

Found from `commalogs/0919` swaglog STATUS_PACKETs: on a cold boot a single
sensor read of one `cpuTempC` zone glitched to **93 °C** while every other
reading (cpu 52-70, memory 56-58, gpu 57-59, pmic 52-54) was sane. Because the
temperature filters start uninitialized, that one garbage sample seeded the filter
high (Tau = 5s), and the thermal band state machine + offroad danger path
(`> 75 °C`) followed the decaying filter for ~10-20s, showing
`thermalStatus = critical/overheated` at a real ~74 °C and blocking engagement.
The first-read spike has no "previous" value to compare against, so the existing
10s `THERMAL_SETTLE_GRACE` hold-to-ok alone was not sufficient.

| Piece | Applied |
|-------|---------|
| `MAX_TEMP_SPIKE_C = 8.0` group-max clamp | The `offroad_max`/`all_max` inputs to the temperature filters reject any single read that jumps more than 8 °C above the previously accepted value (observed jump: +41 °C from one `cpuTempC` zone); the bad sample is replaced with the previous value before it can enter a filter. |
| Settle-window filter seeding | During `THERMAL_SETTLE_GRACE` the filters are not fed; raw maxima are collected and both filters are seeded once from their **median** when the window expires, so a bogus *first* read (which has no previous value to reject against) can no longer poison them. |
| Existing settle hold at `ok` | Kept as a final belt-and-suspenders layer. |

Validation: simulated the measured boot profile (52 → one 93 °C sample → 70-84 °C),
both with the spike on the first read and at a late startup transition (t=12 s,
past the settle grace). The fixed build rejects the spike and stays `ok`; a real
heat ramp (60 → 102 °C) still trips `critical`/`overheated` in the fixed build, so
genuine overheat detection is not masked. The actual 09-19 rlog segments confirm
`thermalStatus=ok` throughout (maxTempC 52-75 °C); the false `critical`/`overheated`
10-20 s window is reproduced in the 07-28 STATUS_PACKET data (spike + decaying filter).

### 7. "Possible Controls Mismatch" during calibration — MADS lateral counter false positive

File: `openpilot/sunnypilot/mads/mads.py`

The on-screen alert "Possible Controls Mismatch / Openpilot may not have fully
disengaged." is `controlsMismatchLateral`, raised in `mads.py` when
`lateral_mismatch_counter >= 200` (20 s). The counter previously accumulated
whenever MADS was active and longitudinal cruise was *not* engaged and the panda
reported `controlsAllowedLateral=False`. On this HONDA port the panda legitimately
keeps `controlsAllowedLateral=False` while LKAS is on but cruise has not been
engaged yet (it only grants lateral once fully engaged), so a normal
LKAS-on/pre-engagement wait of 20 s+ tripped the warning — reproduced right after
Reset Calibration in route `0000008b--…` (t=122-130 s, panda `hondaNidec`,
`ctrlLat=False`, `selfdrive.enabled=False` the whole window).

| Piece | Applied |
|-------|---------|
| `was_engaged = self.selfdrive.enabled or self.selfdrive.enabled_prev` | Counter only accumulates while longitudinal was currently or just previously engaged (`enabled_prev` = prior frame), then resets otherwise. Pre-engagement LKAS-on waits no longer count; a genuine post-disengage mismatch (panda still denying lateral right after disengage) still accumulates and fires. |
| Tests | `test_accumulates_when_active_and_panda_disagrees` updated to model the just-disengaged state; added `test_no_accumulation_before_first_engagement` covering the calibration scenario. (Native `msgq` prevents running the suite on macOS; logic validated with a stub harness + `py_compile`.) |

## NOT aligned (deliberate / out of scope)

1. **`restart_if_crash` mechanism does not exist in current `process.py`** — had to
   be re-introduced (it was removed upstream and replaced by `wait_for_ready`).
   The 0914 commit diff only changed `process_config.py`; on this base the
   infrastructure change in `process.py` was also required. Behavior preserved
   (relaunch within ~1s of crash, no relaunch while the process is alive but still
   starting up).

2. **`ui` process `restart_if_crash=True`** — present in the 0914 base config
   (`PythonProcess("ui", ..., restart_if_crash=True)`) but NOT in the current base.
   This is a pre-existing upstream difference unrelated to the cold-boot fixes, so
   it was left untouched. Note: `ui` still has no crash relaunch on this branch.

3. **`hardwared.py` structural drift** — upstream added `is_offroad_for_5_min` /
   `OFFROAD_DANGER_TEMP` critical override, `thermal_config.get_msg()`,
   `log_slow_hardware_stage()` instrumentation, and the `device_temp_engageable`
   startup condition around the thermal code. The settle-hold logic is the same;
   its placement was adapted so it applies after all thermal computation and before
   startup conditions (see item 3 above).

4. **`micd`/`soundd` keep `wait_for_ready=True`** — the 0914 branch did not have
   this mechanism. Kept to avoid regressing upstream startup-readiness behavior.

5. **git cherry-pick / merge not possible** — histories diverged at the
   v2026.003.000 upstream prebuilt sync (`efe4f758ae` vs `c0bad38f74`); no common
   ancestor. All four commits were re-applied as logic instead of as patches.

## Verification performed

- `python3 -m py_compile` on all 5 changed files: OK.
- Line length check (repo ruff limit 160): no violations.
- `ruff` binary unavailable in this environment (not installed); no full lint run.
- No unit tests exist for `system/manager` or `selfdrived` on this branch; no test
  run performed. On-device cold-boot validation is still required.
- Items 5/6 additionally validated by replaying the `commalogs/0919` logs
  (rlog segments + swaglog STATUS_PACKETs) through the new logic — see the
  Validation notes in those sections.

## Changed files

- `openpilot/selfdrive/selfdrived/selfdrived.py`
- `openpilot/sunnypilot/selfdrive/car/car_specific.py`
- `openpilot/system/hardware/hardwared.py`
- `openpilot/system/manager/process.py`
- `openpilot/system/manager/process_config.py`

## Current constants (after port)

| Constant | Value | Where |
|----------|-------|-------|
| `PROCESS_STARTUP_WAIT` | 45s | `selfdrived.py` |
| `THERMAL_SETTLE_GRACE` | 10s | `hardwared.py` |
| `GAS_INTERCEPTOR_STARTUP_GRACE_FRAMES` | 45s | `car_specific.py` |
| `GAS_INTERCEPTOR_TRANSIENT_GRACE_FRAMES` | 2s | `car_specific.py` |
| `MAX_TEMP_SPIKE_C` | 8 °C | `hardwared.py` (items 6) |
| `handoff_ready` (FirmwareQueryDone + ControlsReady) | gates mismatch until pandad has what it needs + 10s | `selfdrived.py` (item 5) |