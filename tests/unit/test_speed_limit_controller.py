#!/usr/bin/env python3
"""Regression tests for Item 4: Driver Override During SLC Confirmation Pending.

Tests SpeedLimitController.handle_limit_change accept/deny/timeout logic
with and without an active driver override.
"""
import sys
from unittest.mock import MagicMock

sys.path.insert(0, "/Users/suri/repo/openpilot")

# Stub out hardware-dependent modules before importing speed_limit_controller
# (its import chain pulls in openpilot.system.hardware which needs smbus2).
_hardware_pkg = MagicMock()
_hardware_pkg.__path__ = []
sys.modules["openpilot.system.hardware"] = _hardware_pkg
for _mod in [
    "openpilot.system.hardware.tici",
    "openpilot.system.hardware.tici.hardware",
    "openpilot.system.hardware.tici.amplifier",
    "openpilot.system.hardware.tici.debug",
    "openpilot.system.hardware.hw",
    "openpilot.common.params_pyx",
    "openpilot.common.params",
    "openpilot.selfdrive.navd.helpers",
    "panda",
    "panda.python",
    "panda.python.uds",
    "usb1",
    "smbus2",
]:
  sys.modules[_mod] = MagicMock()

# Provide a minimal real-like frogpilot_variables stub (speed_limit_controller
# only needs SPEED_LIMIT_SOURCES and MAPBOX_MONTHLY_REQUEST_LIMIT from it).
_fvp = MagicMock()
_fvp.SPEED_LIMIT_SOURCES = {
    "NONE": 0,
    "CAMERA": 1,
    "DASHBOARD": 2,
    "MAP_DATA": 3,
    "NAVIGATION": 4,
}
_fvp.MAPBOX_MONTHLY_REQUEST_LIMIT = 100000
sys.modules["openpilot.frogpilot.common.frogpilot_variables"] = _fvp

# Make openpilot.frogpilot.common a package so `from openpilot.frogpilot.common
# import frogpilot_variables` works.
_fc = MagicMock()
_fc.__path__ = []
_fc.frogpilot_variables = _fvp
sys.modules["openpilot.frogpilot.common"] = _fc

from openpilot.common.conversions import Conversions as CV

from openpilot.frogpilot.controls.lib.speed_limit_controller import (
    SpeedLimitController,
    SPEED_LIMIT_CONFIRMATION_TIMEOUT,
    SLC_CONFIRMATION_THRESHOLD_MPH,
)


def _make_slc():
  """Build a SpeedLimitController with mocked dependencies."""
  slc = SpeedLimitController.__new__(SpeedLimitController)
  slc.frogpilot_toggles = MagicMock()
  slc.frogpilot_toggles.speed_limit_confirmation_lower = True
  slc.frogpilot_toggles.speed_limit_confirmation_higher = True

  slc.frogpilot_planner = MagicMock()
  slc.frogpilot_planner.frogpilot_vcruise = MagicMock()
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_active = False
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_speed = 0.0

  slc.frogpilot_planner.accel_pressed = False
  slc.frogpilot_planner.decel_pressed = False

  slc.source = None
  slc.target = 0
  slc.overridden_speed = 0
  slc.unconfirmed_speed_limit = 0
  slc.unconfirmed_source = None
  slc.speed_limit_changed_timer = 0
  slc.denied_target = 0
  slc.previous_target = 0
  return slc


def _set_limit(slc, current_ms, new_ms, metric=False):
  """Helper: configure slc state so current_limit=current_ms, desired=new_ms."""
  slc.target = current_ms
  slc.previous_target = current_ms
  slc.source = "CAMERA"
  slc.frogpilot_toggles.is_metric = metric
  slc.speed_limit_accepted = False
  slc.overridden_speed = 0


def test_no_override_diff_gt_10mph_requires_confirmation():
  """Cruise engaged, no override, diff > 10MPH -> confirmation required."""
  slc = _make_slc()
  _set_limit(slc, 55 * CV.MPH_TO_MS, 70 * CV.MPH_TO_MS, metric=False)
  sm = MagicMock()
  sm["carControl"].longActive = True

  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 70 * CV.MPH_TO_MS
  assert slc.speed_limit_changed_timer > 0
  assert slc.target == 55 * CV.MPH_TO_MS, "target should stay at old limit while pending"


def test_no_override_diff_le_10mph_no_confirmation():
  """Cruise engaged, no override, diff <= 10MPH -> no confirmation (auto-apply)."""
  slc = _make_slc()
  _set_limit(slc, 55 * CV.MPH_TO_MS, 60 * CV.MPH_TO_MS, metric=False)
  sm = MagicMock()
  sm["carControl"].longActive = True

  slc.handle_limit_change("CAMERA", 60 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 0
  assert slc.target == 60 * CV.MPH_TO_MS, "target should auto-apply new limit"


def test_override_active_any_diff_triggers_confirmation_off():
  """Override active: small diff (<=10MPH) still triggers confirmation (toggle OFF)."""
  slc = _make_slc()
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_active = True
  _set_limit(slc, 55 * CV.MPH_TO_MS, 60 * CV.MPH_TO_MS, metric=False)
  sm = MagicMock()
  sm["carControl"].longActive = True

  slc.handle_limit_change("CAMERA", 60 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 60 * CV.MPH_TO_MS
  assert slc.speed_limit_changed_timer > 0
  assert slc.target == 55 * CV.MPH_TO_MS, "target should stay at old limit while pending"


def test_override_active_any_diff_triggers_confirmation_on():
  """Override active: small diff triggers confirmation even when toggle ON."""
  slc = _make_slc()
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_active = True
  _set_limit(slc, 55 * CV.MPH_TO_MS, 60 * CV.MPH_TO_MS, metric=False)
  sm = MagicMock()
  sm["carControl"].longActive = True

  slc.handle_limit_change("CAMERA", 60 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 60 * CV.MPH_TO_MS


def test_accept_clears_override_and_applies_new_limit():
  """Override active + accept: override cleared, cruise set to new limit."""
  slc = _make_slc()
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_active = True
  _set_limit(slc, 55 * CV.MPH_TO_MS, 70 * CV.MPH_TO_MS, metric=False)

  # First frame: set up pending confirmation
  sm = MagicMock()
  sm["carControl"].longActive = True
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)
  assert slc.unconfirmed_speed_limit == 70 * CV.MPH_TO_MS
  assert slc.target == 55 * CV.MPH_TO_MS

  # Second frame: same target (still pending), accept pressed
  slc.frogpilot_planner.accel_pressed = True
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 0
  assert slc.target == 70 * CV.MPH_TO_MS, "accept applies new limit as target"
  assert slc.frogpilot_planner.frogpilot_vcruise.driver_override_active is False, \
    "accept clears driver override"


def test_deny_keeps_override_active():
  """Override active + deny: override stays active, cruise stays at override speed."""
  slc = _make_slc()
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_active = True
  _set_limit(slc, 55 * CV.MPH_TO_MS, 70 * CV.MPH_TO_MS, metric=False)

  # First frame: set up pending confirmation
  sm = MagicMock()
  sm["carControl"].longActive = True
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)
  assert slc.unconfirmed_speed_limit == 70 * CV.MPH_TO_MS

  # Second frame: same target, deny pressed
  slc.frogpilot_planner.decel_pressed = True
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 0
  assert slc.target == 55 * CV.MPH_TO_MS, "deny keeps old limit as target"
  assert slc.frogpilot_planner.frogpilot_vcruise.driver_override_active is True, \
    "deny keeps driver override active"


def test_timeout_keeps_override_active():
  """Override active + timeout (30s): same as deny, override stays active."""
  slc = _make_slc()
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_active = True
  _set_limit(slc, 55 * CV.MPH_TO_MS, 70 * CV.MPH_TO_MS, metric=False)

  # First frame: set up pending confirmation
  sm = MagicMock()
  sm["carControl"].longActive = True
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)
  assert slc.unconfirmed_speed_limit == 70 * CV.MPH_TO_MS

  # Simulate timeout: advance timer past SPEED_LIMIT_CONFIRMATION_TIMEOUT
  slc.speed_limit_changed_timer = SPEED_LIMIT_CONFIRMATION_TIMEOUT + 1
  slc.frogpilot_planner.decel_pressed = False
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 0
  assert slc.target == 55 * CV.MPH_TO_MS, "timeout keeps old limit as target"
  assert slc.frogpilot_planner.frogpilot_vcruise.driver_override_active is True, \
    "timeout keeps driver override active (same as deny)"


def test_override_active_large_diff_triggers_confirmation():
  """Override active + large diff (>10MPH) triggers confirmation."""
  slc = _make_slc()
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_active = True
  _set_limit(slc, 55 * CV.MPH_TO_MS, 70 * CV.MPH_TO_MS, metric=False)
  sm = MagicMock()
  sm["carControl"].longActive = True

  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 70 * CV.MPH_TO_MS
  assert slc.speed_limit_changed_timer > 0


def test_no_override_diff_gt_10mph_toggle_off_no_confirmation():
  """Toggle OFF + diff > 10MPH: no confirmation (toggle gates even large changes)."""
  slc = _make_slc()
  slc.frogpilot_toggles.speed_limit_confirmation_lower = False
  slc.frogpilot_toggles.speed_limit_confirmation_higher = False
  _set_limit(slc, 55 * CV.MPH_TO_MS, 70 * CV.MPH_TO_MS, metric=False)
  sm = MagicMock()
  sm["carControl"].longActive = True

  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 0
  assert slc.target == 70 * CV.MPH_TO_MS, "toggle OFF auto-applies large diff"


def test_no_override_diff_le_10mph_toggle_on_no_confirmation():
  """Toggle ON + diff <= 10MPH: no confirmation (diff too small regardless of toggle)."""
  slc = _make_slc()
  slc.frogpilot_toggles.speed_limit_confirmation_lower = True
  slc.frogpilot_toggles.speed_limit_confirmation_higher = True
  _set_limit(slc, 55 * CV.MPH_TO_MS, 60 * CV.MPH_TO_MS, metric=False)
  sm = MagicMock()
  sm["carControl"].longActive = True

  slc.handle_limit_change("CAMERA", 60 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 0
  assert slc.target == 60 * CV.MPH_TO_MS, "diff <= 10 auto-applies regardless of toggle"


def test_override_cleared_and_wipe_applies_on_accept_sync():
  """Override active + accept: override cleared AND wipe applies → vCruise/UI/HUD sync to new limit."""
  slc = _make_slc()
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_active = True
  _set_limit(slc, 55 * CV.MPH_TO_MS, 70 * CV.MPH_TO_MS, metric=False)

  # Frame 1: pending confirmation
  sm = MagicMock()
  sm["carControl"].longActive = True
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)
  assert slc.unconfirmed_speed_limit == 70 * CV.MPH_TO_MS
  assert slc.frogpilot_planner.frogpilot_vcruise.driver_override_active is True

  # Frame 2: accept pressed → override cleared, target = new limit
  slc.frogpilot_planner.accel_pressed = True
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 0
  assert slc.target == 70 * CV.MPH_TO_MS, "accept sets target to new limit"
  assert slc.frogpilot_planner.frogpilot_vcruise.driver_override_active is False, \
    "accept clears driver override"


def test_override_deny_wipe_skipped_holds_override():
  """Override active + deny: override kept, wipe skipped → vCruise/UI/HUD hold override speed."""
  slc = _make_slc()
  slc.frogpilot_planner.frogpilot_vcruise.driver_override_active = True
  _set_limit(slc, 55 * CV.MPH_TO_MS, 70 * CV.MPH_TO_MS, metric=False)

  sm = MagicMock()
  sm["carControl"].longActive = True
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)

  slc.frogpilot_planner.decel_pressed = True
  slc.handle_limit_change("CAMERA", 70 * CV.MPH_TO_MS, sm)

  assert slc.unconfirmed_speed_limit == 0
  assert slc.target == 55 * CV.MPH_TO_MS, "deny keeps old limit as target"
  assert slc.frogpilot_planner.frogpilot_vcruise.driver_override_active is True, \
    "deny keeps driver override active (vCruise/UI/HUD hold override speed)"


def test_no_override_none_source_no_confirmation():
  """No limit source -> no confirmation required (no crash)."""
  slc = _make_slc()
  slc.target = 55 * CV.MPH_TO_MS
  slc.frogpilot_toggles.is_metric = False
  slc.speed_limit_accepted = False
  sm = MagicMock()
  sm["carControl"].longActive = True

  slc.handle_limit_change(None, 0, sm)

  assert slc.unconfirmed_speed_limit == 0


if __name__ == "__main__":
  test_no_override_diff_gt_10mph_requires_confirmation()
  test_no_override_diff_le_10mph_no_confirmation()
  test_no_override_diff_gt_10mph_toggle_off_no_confirmation()
  test_no_override_diff_le_10mph_toggle_on_no_confirmation()
  test_override_active_any_diff_triggers_confirmation_off()
  test_override_active_any_diff_triggers_confirmation_on()
  test_accept_clears_override_and_applies_new_limit()
  test_override_cleared_and_wipe_applies_on_accept_sync()
  test_deny_keeps_override_active()
  test_override_deny_wipe_skipped_holds_override()
  test_timeout_keeps_override_active()
  test_override_active_large_diff_triggers_confirmation()
  test_no_override_none_source_no_confirmation()
  print("All speed_limit_controller tests passed.")
