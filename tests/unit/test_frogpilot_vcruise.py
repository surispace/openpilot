#!/usr/bin/env python3
"""Regression tests for Item 4: frogpilot_vcruise.py override logic.

Tests that driver +/- deviation from slc_candidate latches driver_override_active,
uses v_cruise as slc_value while overriding, clears on accept, and does not
re-latch when slc_candidate changes (accept/deny).
"""
import sys
from unittest.mock import MagicMock

sys.path.insert(0, "/Users/suri/repo/openpilot")

# Stub hardware/compiled modules.
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
    "openpilot.selfdrive.car.interfaces",
    "openpilot.selfdrive.car.values",
    "openpilot.selfdrive.car.fw_query_definitions",
    "openpilot.selfdrive.controls.lib.longitudinal_mpc_lib.c_generated_code.acados_ocp_solver_pyx",
    "opendbc.can.parser_pyx",
    "opendbc.can.can_define",
    "casadi", "panda", "panda.python", "panda.python.uds", "usb1", "smbus2",
]:
  sys.modules[_mod] = MagicMock()

_fvp = MagicMock()
_fvp.SPEED_LIMIT_SOURCES = {"NONE": 0, "CAMERA": 1, "DASHBOARD": 2, "MAP_DATA": 3, "NAVIGATION": 4}
_fvp.MAPBOX_MONTHLY_REQUEST_LIMIT = 100000
_fvp.CRUISING_SPEED = 5
sys.modules["openpilot.frogpilot.common.frogpilot_variables"] = _fvp
_fc = MagicMock()
_fc.__path__ = []
_fc.frogpilot_variables = _fvp
sys.modules["openpilot.frogpilot.common"] = _fc

from openpilot.common.conversions import Conversions as CV
from openpilot.selfdrive.controls.lib.drive_helpers import ButtonType
from openpilot.frogpilot.controls.lib.frogpilot_vcruise import FrogPilotVCruise


def _make_vcruise():
  """Build FrogPilotVCruise with mocked dependencies."""
  vc = FrogPilotVCruise.__new__(FrogPilotVCruise)

  # frogpilot_planner.frogpilot_vcruise must point back to self (circular ref).
  vc.frogpilot_planner = MagicMock()
  vc.frogpilot_planner.frogpilot_vcruise = vc
  vc.frogpilot_planner.accel_pressed = False
  vc.frogpilot_planner.decel_pressed = False

  vc.csc = MagicMock()
  vc.csc.target = None
  vc.csc_active = False

  vc.slc = MagicMock()
  vc.slc.overridden_speed = 0
  vc.slc.target = 0
  vc.slc.unconfirmed_speed_limit = 0

  vc.driver_override_active = False
  vc.driver_override_speed = 0.0
  vc.v_cruise_prev = 0.0
  return vc


def _call_update(vc, v_cruise_ms, v_ego_ms=10, slc_target_ms=55 * CV.MPH_TO_MS,
                 accel=False, decel=False, unconfirmed=0, is_metric=False,
                 slc_active=True):
  """Configure slc/toggles and call vc.update()."""
  vc.frogpilot_planner.accel_pressed = accel
  vc.frogpilot_planner.decel_pressed = decel
  vc.slc.target = slc_target_ms
  vc.slc.unconfirmed_speed_limit = unconfirmed
  vc.slc.offset = 0

  toggles = MagicMock()
  toggles.speed_limit_controller = slc_active
  toggles.curve_speed_controller = False
  toggles.taco_tune = False
  toggles.is_metric = is_metric
  vc.frogpilot_toggles = toggles

  sm = MagicMock()
  sm["carControl"].longActive = True
  sm["carState"].vEgoCluster = v_ego_ms
  sm["controlsState"].vCruiseCluster = v_cruise_ms / CV.KPH_TO_MS
  sm["carState"].cruiseState.available = False  # PCM inactive by default
  sm.alive = {}

  # Simulate button press events for accel/decel cruise
  button_events = []
  if accel:
    be = MagicMock()
    be.type = ButtonType.accelCruise
    button_events.append(be)
  if decel:
    be = MagicMock()
    be.type = ButtonType.decelCruise
    button_events.append(be)
  sm["carState"].buttonEvents = button_events

  gps = None
  map_match = {}
  import datetime
  now = datetime.datetime.now()
  vc.update(gps, map_match, now, True, v_cruise_ms, v_ego_ms, sm, toggles)
  return vc


def test_override_latches_when_driver_goes_above_limit():
  """Driver + presses cruise above slc_candidate -> override active, slc_value=v_cruise."""
  vc = _make_vcruise()
  # First call: establish v_cruise_prev at limit
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is False
  # Second call: driver sets 60 MPH -> deviation -> latch
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is True, "override should latch when speed exceeds slc_candidate"
  assert abs(vc.slc_offset - 0) < 1e-6


def test_override_latches_when_driver_goes_below_limit():
  """Driver - presses cruise below slc_candidate -> override active."""
  vc = _make_vcruise()
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is False
  vc = _call_update(vc, 50 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is True, "override should latch when speed drops below slc_candidate"


def test_no_override_when_speed_matches_candidate():
  """No driver deviation -> no override, slc_value=slc_candidate."""
  vc = _make_vcruise()
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is False


def test_override_persists_on_subsequent_frame_no_deviation():
  """Once latched, override stays True even if v_cruise stops changing (no re-check clears it)."""
  vc = _make_vcruise()
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is True
  # Next frame: same speed, no new button press, but still deviated -> stays active
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is True


def test_override_clears_on_accept_no_relatch():
  """Accept: slc_candidate changes to new limit, v_cruise unchanged -> no re-latch, override cleared."""
  vc = _make_vcruise()
  # Establish override at 60 MPH vs limit 55 (two calls: first sets prev, second latches)
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is True

  # Simulate speed_limit_controller clearing override on accept, then setting new limit
  vc.driver_override_active = False  # cleared by SLC on accept

  # Accept frame: slc_candidate becomes 70, v_cruise still 60 (prev frame value).
  # v_cruise_prev was set to 60, so v_cruise_changed=False -> no re-latch.
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=70 * CV.MPH_TO_MS)
  assert vc.driver_override_active is False, \
    "accept should clear override and NOT re-latch on slc_candidate change"


def test_override_clears_when_slc_inactive():
  """SLC toggle off -> override cleared."""
  vc = _make_vcruise()
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS, accel=True, slc_active=False)
  assert vc.driver_override_active is False


def test_confirmation_pending_blocks_override_latch():
  """While confirmation pending, driver +/- does not latch new override."""
  vc = _make_vcruise()
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is False
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS,
                    accel=True, unconfirmed=70 * CV.MPH_TO_MS)
  assert vc.driver_override_active is False, \
    "confirmation pending should block override latch"


def test_no_override_without_button_press_on_v_cruise_change():
  """v_cruise changes (e.g. PCM/ACC adjustment) AND deviates from limit -> override latches."""
  vc = _make_vcruise()
  # First call: establish v_cruise_prev at limit (no deviation yet)
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS,
                    accel=False, decel=False)
  assert vc.driver_override_active is False
  # Second call: v_cruise deviates from slc_candidate -> latch override
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS,
                    accel=False, decel=False)
  assert vc.driver_override_active is True, \
    "v_cruise change deviating from slc_candidate latches override even without button press"


def test_no_override_when_cruise_not_active():
  """Driver presses + but cruise not engaged -> NO override."""
  vc = _make_vcruise()
  vc.frogpilot_toggles = MagicMock()
  vc.frogpilot_toggles.speed_limit_controller = True
  vc.frogpilot_toggles.curve_speed_controller = False
  vc.frogpilot_toggles.taco_tune = False
  vc.frogpilot_toggles.is_metric = False
  sm = MagicMock()
  sm["carControl"].longActive = False
  sm["carState"].vEgoCluster = 10
  sm["controlsState"].vCruiseCluster = 60 * CV.MPH_TO_MS / CV.KPH_TO_MS
  sm["controlsState"].enabled = False
  sm.alive = {}
  import datetime
  vc.update(None, {}, datetime.datetime.now(), True,
            60 * CV.MPH_TO_MS, 10, sm, vc.frogpilot_toggles)
  assert vc.driver_override_active is False, \
    "cruise not active should not latch override"


def test_no_override_without_deviation():
  """Button pressed but v_cruise matches slc_candidate -> NO override."""
  vc = _make_vcruise()
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS,
                    accel=True)
  assert vc.driver_override_active is False, \
    "button press without deviation should not latch override"


def test_button_pressed_and_deviation_latches_override():
  """Button pressed AND v_cruise deviates from slc_candidate -> override latched."""
  vc = _make_vcruise()
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is False
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is True, \
    "button press with deviation should latch override"


def test_no_override_when_pcm_active():
  """PCM controls speed (cruiseState.available=True) -> NO override even if v_cruise deviates."""
  vc = _make_vcruise()
  sm = MagicMock()
  sm["carControl"].longActive = True
  sm["carState"].vEgoCluster = 60 * CV.MPH_TO_MS / CV.KPH_TO_MS
  sm["controlsState"].vCruiseCluster = 60 * CV.MPH_TO_MS / CV.KPH_TO_MS
  sm["carState"].cruiseState.available = True  # PCM is controlling speed
  sm.alive = {}
  toggles = MagicMock()
  toggles.speed_limit_controller = True
  toggles.curve_speed_controller = False
  toggles.taco_tune = False
  toggles.is_metric = False
  vc.frogpilot_toggles = toggles
  import datetime
  vc.update(None, {}, datetime.datetime.now(), True,
            60 * CV.MPH_TO_MS, 10 * CV.MPH_TO_MS, sm, vc.frogpilot_toggles)
  assert vc.driver_override_active is False, \
    "PCM controlling speed should not latch override even when v_cruise deviates from slc_candidate"


def test_override_latches_when_pcm_inactive_and_driver_deviates():
  """PCM inactive + driver deviates -> override latched."""
  vc = _make_vcruise()
  vc = _call_update(vc, 55 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is False
  # PCM inactive, driver deviates to 60 MPH
  vc = _call_update(vc, 60 * CV.MPH_TO_MS, slc_target_ms=55 * CV.MPH_TO_MS)
  assert vc.driver_override_active is True, \
    "PCM inactive + driver deviation should latch override"


if __name__ == "__main__":
  test_override_latches_when_driver_goes_above_limit()
  test_override_latches_when_driver_goes_below_limit()
  test_no_override_when_speed_matches_candidate()
  test_override_persists_on_subsequent_frame_no_deviation()
  test_override_clears_on_accept_no_relatch()
  test_override_clears_when_slc_inactive()
  test_confirmation_pending_blocks_override_latch()
  test_no_override_without_button_press_on_v_cruise_change()
  test_no_override_when_cruise_not_active()
  test_no_override_without_deviation()
  test_button_pressed_and_deviation_latches_override()
  test_no_override_when_pcm_active()
  test_override_latches_when_pcm_inactive_and_driver_deviates()
  print("All frogpilot_vcruise tests passed.")
