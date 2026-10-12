"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.cereal import custom
from opendbc.car import structs
from opendbc.car.hyundai.values import HyundaiFlags
from opendbc.sunnypilot.car.mazda.values import MazdaFlagsSP
from openpilot.selfdrive.selfdrived.events import Events
from openpilot.sunnypilot.selfdrive.selfdrived.events import EventsSP
from openpilot.sunnypilot.mads.mads import ModularAssistiveDrivingSystem
from openpilot.sunnypilot.mads.state import State
from openpilot.common.test import OpenpilotTestCase

EventNameSP = custom.OnroadEventSP.EventName
SafetyModel = structs.CarParams.SafetyModel
ButtonType = structs.CarState.ButtonEvent.Type


def make_car_state(available):
  cs = structs.CarState()
  cs.cruiseState.available = available
  return cs


def make_mads(mocker, brand, prev_available, flags=0, sp_flags=0):
  sd = mocker.MagicMock()
  sd.CP = structs.CarParams()
  sd.CP.brand = brand
  sd.CP.flags = int(flags)
  sd.CP_SP = structs.CarParamsSP()
  sd.CP_SP.flags = int(sp_flags)
  sd.params = mocker.MagicMock()
  sd.params.get_bool = mocker.MagicMock(side_effect=lambda k: {
    "Mads": True, "MadsMainCruiseAllowed": True,
    "DisengageOnAccelerator": True, "MadsUnifiedEngagementMode": True,
  }.get(k, False))
  sd.events = Events()
  sd.events_sp = EventsSP()
  sd.enabled = False
  sd.enabled_prev = False
  sd.initialized = True
  sd.CS_prev = make_car_state(prev_available)
  ps = mocker.MagicMock()
  ps.controlsAllowedLateral = True
  ps.safetyModel = SafetyModel.mazda
  sd.sm = {'pandaStates': [ps]}
  sd.state_machine = mocker.MagicMock()

  mads = ModularAssistiveDrivingSystem(sd)
  mads.enabled_toggle = True
  return mads, sd


class TestMainCruiseOffSwitch(OpenpilotTestCase):
  """On cars whose only MADS off-switch is the ACC main state, lateral must not be able to
  outlive it. A carstate that reports cruise enabled while main is off engages MADS with no
  falling edge behind it, which used to leave lateral on until ignition off (route 00000057)."""

  def _run(self, brand, prev_available, enabled, flags=0):
    mocker = self._fixture("mocker")
    mads, sd = make_mads(mocker, brand, prev_available, flags)
    mads.enabled = enabled
    mads.update_events(make_car_state(False))
    return sd.events_sp.has(EventNameSP.lkasDisable)

  def test_falling_edge_still_disables(self):
    assert self._run("mazda", prev_available=True, enabled=True)

  def test_enabled_with_availability_already_low_disables(self):
    assert self._run("mazda", prev_available=False, enabled=True)

  def test_disabled_mads_stays_quiet(self):
    assert not self._run("mazda", prev_available=False, enabled=False)

  def test_own_button_brands_keep_the_edge_only_behavior(self):
    # a hyundai with an LDA button engages MADS with main cruise off, so a low availability
    # level is a normal state there and must not disable it
    assert not self._run("hyundai", prev_available=False, enabled=True, flags=HyundaiFlags.HAS_LDA_BUTTON)


class TestAutoLkas(OpenpilotTestCase):
  """AutoLkas: with main cruise allowed, LKAS is on by default whenever main is available; main
  off disables it; and the LKAS button toggles it. Main re-arms the latch on the way down."""

  def _mads(self, brand="honda", prev_available=True):
    return make_mads(self._fixture("mocker"), brand, prev_available)

  def _frame(self, mads, sd, cs):
    sd.events.clear()
    sd.events_sp.clear()
    mads.update(cs)
    sd.CS_prev = cs

  def test_main_available_requests_enable_without_a_rising_edge(self):
    mads, sd = self._mads(prev_available=True)
    mads.update_events(make_car_state(True))
    assert sd.events_sp.has(EventNameSP.lkasEnable)

  def test_enable_latches_off_the_repeat_request(self):
    mads, sd = self._mads()
    self._frame(mads, sd, make_car_state(True))
    assert mads.state_machine.state == State.enabled
    assert not mads.auto_lkas.armed

    self._frame(mads, sd, make_car_state(True))
    assert mads.state_machine.state == State.enabled
    assert not sd.events_sp.has(EventNameSP.lkasEnable)

  def test_main_off_disables_and_re_arms(self):
    mads, sd = self._mads()
    self._frame(mads, sd, make_car_state(True))
    assert mads.state_machine.state == State.enabled

    self._frame(mads, sd, make_car_state(False))
    assert mads.state_machine.state == State.disabled
    assert mads.auto_lkas.armed

    self._frame(mads, sd, make_car_state(True))
    assert mads.state_machine.state == State.enabled

  def test_lkas_button_toggles(self):
    mads, sd = self._mads()
    self._frame(mads, sd, make_car_state(True))
    assert mads.state_machine.state == State.enabled

    pressed = make_car_state(True)
    be = structs.CarState.ButtonEvent()
    be.type = ButtonType.lkas
    be.pressed = True
    pressed.buttonEvents = [be]

    self._frame(mads, sd, pressed)
    assert mads.state_machine.state == State.disabled

    self._frame(mads, sd, pressed)
    assert mads.state_machine.state == State.enabled

  def test_declared_button_brand_is_not_auto_engaged(self):
    mads, sd = make_mads(self._fixture("mocker"), "mazda", True, sp_flags=MazdaFlagsSP.TJA_BUTTON)
    mads.update_events(make_car_state(True))
    assert not sd.events_sp.has(EventNameSP.lkasEnable)
