"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""

from openpilot.cereal import log, custom
from opendbc.car import structs

from opendbc.car.chrysler.values import RAM_DT
from openpilot.common.realtime import DT_CTRL
from openpilot.selfdrive.selfdrived.events import ET, Events
from openpilot.sunnypilot.selfdrive.selfdrived.events import EventsSP

EventName = log.OnroadEvent.EventName
EventNameSP = custom.OnroadEventSP.EventName
GearShifter = structs.CarState.GearShifter
# Once the gas interceptor is healthy, its FAULT states used to fault immediately.
# On a cold boot the device is still finishing startup (manager restarting processes,
# controlsd settling), which can briefly pause the interceptor keepalive; the pedal
# hardware then reports FAULT_TIMEOUT / FAULT_STARTUP (STATE 4/5) for a few hundred ms
# even though nothing is actually wrong. This window (from the start of the onroad
# session) tolerates those brief transient states, and only faults if the transient
# state persists longer than GAS_INTERCEPTOR_TRANSIENT_GRACE_FRAMES or after the window
# expires. Real, sustained interceptor faults still surface since the tolerated
# transient streak is a small fraction of this period.
GAS_INTERCEPTOR_STARTUP_GRACE_FRAMES = int(45. / DT_CTRL)
# Maximum tolerated streak (seconds) of the transient states (4/5) inside the startup
# grace window before it is treated as a real fault even during startup.
GAS_INTERCEPTOR_TRANSIENT_GRACE_FRAMES = int(2. / DT_CTRL)


class CarSpecificEventsSP:
  def __init__(self, CP: structs.CarParams, CP_SP: structs.CarParamsSP):
    self.CP = CP
    self.CP_SP = CP_SP

    self.low_speed_alert = False
    self.gas_interceptor_healthy = False
    self.gas_interceptor_bootstrap_frames = 0
    self.gas_interceptor_startup_frames = 0
    self.gas_interceptor_fault_frames = 0

  def update(self, CS: structs.CarState, CS_SP: custom.CarStateSP, events: Events):
    events_sp = EventsSP()
    self.gas_interceptor_startup_frames += 1

    if self.CP_SP.enableGasInterceptor:
      interceptor_state = CS_SP.gasInterceptorState
      if interceptor_state != 0:
        self.gas_interceptor_fault_frames += 1
      else:
        self.gas_interceptor_fault_frames = 0

      # During the startup window, briefly tolerate the transient timeout/startup
      # states (4/5) so a one-shot FAULT_TIMEOUT from boot churn doesn't hard
      # disengage. Anything else, or anything sustained, faults immediately.
      in_startup = self.gas_interceptor_startup_frames < GAS_INTERCEPTOR_STARTUP_GRACE_FRAMES
      transient_tolerated = in_startup and interceptor_state in (4, 5) and \
        self.gas_interceptor_fault_frames <= GAS_INTERCEPTOR_TRANSIENT_GRACE_FRAMES

      if self.gas_interceptor_healthy:
        if interceptor_state != 0 and not transient_tolerated:
          events.add(EventName.gasInterceptorFault)
      elif interceptor_state == 0:
        self.gas_interceptor_healthy = CS.canValid
      elif interceptor_state in (4, 5):
        self.gas_interceptor_bootstrap_frames += 1
        if events.contains(ET.ENABLE) or self.gas_interceptor_bootstrap_frames > GAS_INTERCEPTOR_STARTUP_GRACE_FRAMES:
          events.add(EventName.gasInterceptorFault)
      else:
        events.add(EventName.gasInterceptorFault)

    if self.CP.brand == 'chrysler':
      if self.CP.carFingerprint in RAM_DT:
        # remove belowSteerSpeed event from CarSpecificEvents as RAM_DT uses a different logic
        if events.has(EventName.belowSteerSpeed):
          events.remove(EventName.belowSteerSpeed)

        # TODO-SP: use if/elif to have the gear shifter condition takes precedence over the speed condition
        # TODO-SP: add 1 m/s hysteresis
        if CS.vEgo >= self.CP.minEnableSpeed:
          self.low_speed_alert = False
        if self.CP.minEnableSpeed >= 14.5 and CS.gearShifter != GearShifter.drive:
          self.low_speed_alert = True
      if self.low_speed_alert:
        events.add(EventName.belowSteerSpeed)

    elif self.CP.brand == 'toyota':
      if self.CP.openpilotLongitudinalControl:
        if CS.cruiseState.standstill and not CS.brakePressed and self.CP_SP.enableGasInterceptor:
          if events.has(EventName.resumeRequired):
            events.remove(EventName.resumeRequired)

    return events_sp
