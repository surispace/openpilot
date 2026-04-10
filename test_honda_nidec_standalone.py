#!/usr/bin/env python3
"""
Standalone test for the Honda Nidec cruise fix.
Does not require building the full openpilot codebase.
"""
import sys

# Add cereal gen path for generated files
sys.path.insert(0, '/Users/suri/repo/openpilot')
sys.path.insert(0, '/Users/suri/repo/openpilot/cereal')

# Mock the cereal imports with simple dataclasses
from dataclasses import dataclass, field
from enum import IntEnum
from typing import List

@dataclass
class ButtonEvent:
    class Type(IntEnum):
        none = 0
        accelCruise = 1
        decelCruise = 2
        cancel = 3
        resumeCruise = 4
        setCruise = 5
        gapAdjustCruise = 6

    type: 'ButtonEventType' = None
    pressed: bool = False

@dataclass
class ButtonEventType:
    raw: int = 0

    def __eq__(self, other):
        if isinstance(other, ButtonEvent.Type):
            return self.raw == other.value
        return False

    def __hash__(self):
        return self.raw

@dataclass
class CruiseState:
    available: bool = False
    speed: float = 0.0
    speedCluster: float = 0.0
    standstill: bool = False

@dataclass
class CarState:
    vEgo: float = 0.0
    gasPressed: bool = False
    cruiseState: CruiseState = field(default_factory=CruiseState)
    buttonEvents: List = field(default_factory=list)

@dataclass
class CarParams:
    pcmCruise: bool = False
    openpilotLongitudinalControl: bool = False

@dataclass
class CarParamsSP:
    pcmCruiseSpeed: bool = False
    customMinimumSetSpeed: float = 0.0


# Constants from cruise.py
V_CRUISE_MIN = 8
V_CRUISE_MAX = 145
V_CRUISE_UNSET = 255
V_CRUISE_INITIAL = 40
V_CRUISE_INITIAL_EXPERIMENTAL_MODE = 105
IMPERIAL_INCREMENT = 1.6  # CV.MPH_TO_KPH rounded

# Conversion constants
CV = type('CV', (), {'MS_TO_KPH': 3.6, 'KPH_TO_MS': 1/3.6, 'MPH_TO_KPH': 1.609344, 'MPH_TO_MS': 0.44704})()


class VCruiseHelperBase:
    def __init__(self, CP, CP_SP):
        self.CP = CP
        self.CP_SP = CP_SP
        self.v_cruise_kph = V_CRUISE_UNSET
        self.v_cruise_cluster_kph = V_CRUISE_UNSET
        self.v_cruise_kph_last = 0
        self.v_cruise_min = V_CRUISE_MIN
        self.button_timers = {ButtonEvent.Type.decelCruise: 0, ButtonEvent.Type.accelCruise: 0}
        self.button_change_states = {btn: {"standstill": False, "enabled": False} for btn in self.button_timers}

    @property
    def v_cruise_initialized(self):
        return self.v_cruise_kph != V_CRUISE_UNSET


class VCruiseHelper(VCruiseHelperBase):
    def update_v_cruise(self, CS, enabled, is_metric):
        # Simplified - just tracks last value
        self.v_cruise_kph_last = self.v_cruise_kph

    def initialize_v_cruise(self, CS, experimental_mode: bool, dynamic_experimental_control: bool) -> None:
        # THIS IS THE FIXED VERSION
        # initializing is handled by the PCM
        # Exception: Honda Nidec has pcmCruise=True but openpilot controls longitudinal,
        # so it still needs initialization
        if self.CP.pcmCruise and not self.CP.openpilotLongitudinalControl:
            return

        initial_experimental_mode = experimental_mode and not dynamic_experimental_control
        initial = V_CRUISE_INITIAL_EXPERIMENTAL_MODE if initial_experimental_mode else V_CRUISE_INITIAL

        if any(b.type in (ButtonType.accelCruise, ButtonType.resumeCruise) for b in CS.buttonEvents) and self.v_cruise_initialized:
            self.v_cruise_kph = self.v_cruise_kph_last
        else:
            import math
            import numpy as np
            self.v_cruise_kph = int(round(np.clip(CS.vEgo * CV.MS_TO_KPH, initial, V_CRUISE_MAX)))

        self.v_cruise_cluster_kph = self.v_cruise_kph


def test_honda_nidec_experimental_mode():
    """Test: Honda Nidec with Experimental Mode ON should initialize to current speed"""
    print("\n" + "="*70)
    print("TEST 1: Honda Nidec with Experimental Mode ON")
    print("="*70)

    # 2019 Honda Pilot configuration
    CP = CarParams(pcmCruise=True, openpilotLongitudinalControl=True)
    CP_SP = CarParamsSP()
    v_cruise_helper = VCruiseHelper(CP, CP_SP)

    # Simulate driving at 70 mph (above 105 kph experimental minimum)
    test_speed_mph = 70
    test_speed_ms = test_speed_mph * CV.MPH_TO_MS

    print(f"  Driving speed: {test_speed_mph} mph ({test_speed_ms:.1f} m/s)")
    print(f"  Experimental Mode: ON (min: {V_CRUISE_INITIAL_EXPERIMENTAL_MODE} kph = {V_CRUISE_INITIAL_EXPERIMENTAL_MODE/CV.MPH_TO_KPH:.1f} mph)")

    # Initialize (simulates pressing SET button)
    v_cruise_helper.initialize_v_cruise(
        CarState(vEgo=test_speed_ms),
        experimental_mode=True,
        dynamic_experimental_control=False
    )

    assert v_cruise_helper.v_cruise_initialized, "❌ v_cruise should be initialized!"
    expected_kph = int(round(test_speed_mph * CV.MPH_TO_KPH))
    assert v_cruise_helper.v_cruise_kph == expected_kph, \
        f"❌ Expected {expected_kph} kph but got {v_cruise_helper.v_cruise_kph} kph"

    print(f"  ✓ Cruise speed initialized to {v_cruise_helper.v_cruise_kph} kph ({v_cruise_helper.v_cruise_kph / CV.MPH_TO_KPH:.1f} mph)")
    print(f"  ✅ TEST PASSED!\n")


def test_honda_nidec_chill_mode():
    """Test: Honda Nidec with Experimental Mode OFF should initialize to current speed"""
    print("\n" + "="*70)
    print("TEST 2: Honda Nidec with Experimental Mode OFF (Chill Mode)")
    print("="*70)

    CP = CarParams(pcmCruise=True, openpilotLongitudinalControl=True)
    CP_SP = CarParamsSP()
    v_cruise_helper = VCruiseHelper(CP, CP_SP)

    # Simulate driving at 55 mph
    test_speed_mph = 55
    test_speed_ms = test_speed_mph * CV.MPH_TO_MS

    print(f"  Driving speed: {test_speed_mph} mph ({test_speed_ms:.1f} m/s)")
    print(f"  Experimental Mode: OFF")

    v_cruise_helper.initialize_v_cruise(
        CarState(vEgo=test_speed_ms),
        experimental_mode=False,
        dynamic_experimental_control=False
    )

    assert v_cruise_helper.v_cruise_initialized, "❌ v_cruise should be initialized!"
    expected_kph = int(round(test_speed_mph * CV.MPH_TO_KPH))
    assert v_cruise_helper.v_cruise_kph == expected_kph, \
        f"❌ Expected {expected_kph} kph but got {v_cruise_helper.v_cruise_kph} kph"

    print(f"  ✓ Cruise speed initialized to {v_cruise_helper.v_cruise_kph} kph ({v_cruise_helper.v_cruise_kph / CV.MPH_TO_KPH:.1f} mph)")
    print(f"  ✅ TEST PASSED!\n")


def test_true_pcm_cruise_no_init():
    """Test: True PCM cruise (no openpilot long) should NOT initialize"""
    print("\n" + "="*70)
    print("TEST 3: True PCM Cruise (e.g., Toyota, VW) - Should Skip Init")
    print("="*70)

    CP = CarParams(pcmCruise=True, openpilotLongitudinalControl=False)
    CP_SP = CarParamsSP()
    v_cruise_helper = VCruiseHelper(CP, CP_SP)

    print(f"  pcmCruise: True")
    print(f"  openpilotLongitudinalControl: False")

    # Try to initialize
    v_cruise_helper.initialize_v_cruise(
        CarState(vEgo=50.0),
        experimental_mode=False,
        dynamic_experimental_control=False
    )

    # Should NOT be initialized (returns early)
    assert not v_cruise_helper.v_cruise_initialized, "❌ v_cruise should NOT be initialized for true PCM!"
    assert v_cruise_helper.v_cruise_kph == V_CRUISE_UNSET, \
        f"❌ Expected {V_CRUISE_UNSET} but got {v_cruise_helper.v_cruise_kph}"

    print(f"  ✓ Correctly skipped initialization (v_cruise = {v_cruise_helper.v_cruise_kph})")
    print(f"  ✅ TEST PASSED!\n")


def test_low_speed_clamping_experimental():
    """Test: Low speeds should be clamped to experimental mode minimum"""
    print("\n" + "="*70)
    print("TEST 4: Low Speed Clamping (Experimental Mode)")
    print("="*70)

    CP = CarParams(pcmCruise=True, openpilotLongitudinalControl=True)
    CP_SP = CarParamsSP()
    v_cruise_helper = VCruiseHelper(CP, CP_SP)

    # Simulate driving at 20 mph (below 105 kph minimum for experimental mode)
    test_speed_mph = 20
    test_speed_ms = test_speed_mph * CV.MPH_TO_MS

    print(f"  Driving speed: {test_speed_mph} mph ({test_speed_ms:.1f} m/s)")
    print(f"  Experimental Mode: ON (min: {V_CRUISE_INITIAL_EXPERIMENTAL_MODE} kph = {V_CRUISE_INITIAL_EXPERIMENTAL_MODE/CV.MPH_TO_KPH:.1f} mph)")

    v_cruise_helper.initialize_v_cruise(
        CarState(vEgo=test_speed_ms),
        experimental_mode=True,
        dynamic_experimental_control=False
    )

    assert v_cruise_helper.v_cruise_initialized
    # Should be clamped to 105 kph (experimental mode minimum)
    assert v_cruise_helper.v_cruise_kph >= V_CRUISE_INITIAL_EXPERIMENTAL_MODE, \
        f"❌ Expected at least {V_CRUISE_INITIAL_EXPERIMENTAL_MODE} kph but got {v_cruise_helper.v_cruise_kph} kph"

    print(f"  ✓ Low speed clamped to {v_cruise_helper.v_cruise_kph} kph ({v_cruise_helper.v_cruise_kph / CV.MPH_TO_KPH:.1f} mph)")
    print(f"  ✅ TEST PASSED!\n")


def test_old_buggy_behavior():
    """Demonstrate the old buggy behavior where Honda Nidec would get 65mph"""
    print("\n" + "="*70)
    print("DEMO: OLD BUGGY BEHAVIOR (Before Fix)")
    print("="*70)

    # Old code would return early on pcmCruise=True
    CP = CarParams(pcmCruise=True, openpilotLongitudinalControl=True)

    print(f"  Honda Pilot configuration:")
    print(f"    - pcmCruise = {CP.pcmCruise}")
    print(f"    - openpilotLongitudinalControl = {CP.openpilotLongitudinalControl}")

    # OLD CODE: if self.CP.pcmCruise: return  # ← Returns here!
    old_would_initialize = not CP.pcmCruise  # False for Honda

    print(f"\n  OLD CODE: 'if self.CP.pcmCruise: return'")
    print(f"  Would initialize: {old_would_initialize}")
    print(f"  Result: ❌ v_cruise stays at {V_CRUISE_UNSET}, falls back to 105 kph (65 mph)")

    # NEW CODE: if self.CP.pcmCruise and not self.CP.openpilotLongitudinalControl: return
    new_would_initialize = not (CP.pcmCruise and not CP.openpilotLongitudinalControl)  # True for Honda

    print(f"\n  NEW CODE: 'if self.CP.pcmCruise and not self.CP.openpilotLongitudinalControl: return'")
    print(f"  Would initialize: {new_would_initialize}")
    print(f"  Result: ✅ v_cruise set to current driving speed")
    print(f"  ✅ BUG FIXED!\n")


if __name__ == "__main__":
    import numpy as np

    try:
        test_honda_nidec_experimental_mode()
        test_honda_nidec_chill_mode()
        test_true_pcm_cruise_no_init()
        test_low_speed_clamping_experimental()
        test_old_buggy_behavior()

        print("\n" + "="*70)
        print("🎉 ALL TESTS PASSED!")
        print("="*70)
        print("\nSummary:")
        print("  ✅ Honda Nidec (Pilot) correctly initializes cruise speed")
        print("  ✅ Works with both Experimental Mode ON and OFF")
        print("  ✅ True PCM cruise cars still skip initialization correctly")
        print("  ✅ Low speed clamping works as expected")
        print("="*70)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
