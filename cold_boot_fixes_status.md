# Cold Boot Fixes — Port Status

Status of porting the cold-boot fixes from `nrdr-nightly-0914` (commits
`9514844fbe`, `b54cc11e7b`, `f7a42ea360`, `f72b1ea3bf`) into the current
`nrdr-nightly` codebase (openpilot v2026.003.000 base).

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