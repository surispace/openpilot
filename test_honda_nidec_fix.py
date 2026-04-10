#!/usr/bin/env python3
"""
Quick test to verify the Honda Nidec cruise fix works correctly
"""
import sys
sys.path.insert(0, '/Users/suri/repo/openpilot')

from cereal import car, custom
from openpilot.selfdrive.car.cruise import VCruiseHelper, V_CRUISE_INITIAL, V_CRUISE_MAX, V_CRUISE_UNSET
from common.constants import CV

def test_honda_nidec():
    """Honda Nidec: pcmCruise=True but openpilotLongitudinalControl=True"""
    print("Testing Honda Nidec (pcmCruise=True, openpilotLongitudinalControl=True)...")
    
    CP = car.CarParams(pcmCruise=True, openpilotLongitudinalControl=True)
    CP_SP = custom.CarParamsSP()
    v_cruise_helper = VCruiseHelper(CP, CP_SP)
    
    # Reset state
    for _ in range(2):
        v_cruise_helper.update_v_cruise(car.CarState(cruiseState={"available": False}), enabled=False, is_metric=False)
    
    # Test with experimental mode ON
    test_speed_mph = 45
    test_speed_ms = test_speed_mph * CV.MPH_TO_MS
    
    v_cruise_helper.initialize_v_cruise(
        car.CarState(vEgo=test_speed_ms), 
        experimental_mode=True, 
        dynamic_experimental_control=False
    )
    
    assert v_cruise_helper.v_cruise_initialized, "v_cruise should be initialized!"
    expected_kph = test_speed_mph * CV.MPH_TO_KPH
    assert v_cruise_helper.v_cruise_kph == int(round(expected_kph)), \
        f"Expected {int(round(expected_kph))} kph but got {v_cruise_helper.v_cruise_kph} kph"
    
    print(f"  ✓ At {test_speed_mph} mph with experimental mode ON, cruise set to {v_cruise_helper.v_cruise_kph} kph")
    
    # Test with experimental mode OFF
    v_cruise_helper2 = VCruiseHelper(CP, CP_SP)
    for _ in range(2):
        v_cruise_helper2.update_v_cruise(car.CarState(cruiseState={"available": False}), enabled=False, is_metric=False)
    
    v_cruise_helper2.initialize_v_cruise(
        car.CarState(vEgo=test_speed_ms), 
        experimental_mode=False, 
        dynamic_experimental_control=False
    )
    
    assert v_cruise_helper2.v_cruise_initialized, "v_cruise should be initialized!"
    assert v_cruise_helper2.v_cruise_kph == int(round(expected_kph)), \
        f"Expected {int(round(expected_kph))} kph but got {v_cruise_helper2.v_cruise_kph} kph"
    
    print(f"  ✓ At {test_speed_mph} mph with experimental mode OFF, cruise set to {v_cruise_helper2.v_cruise_kph} kph")
    print("  ✅ Honda Nidec tests PASSED!\n")

def test_true_pcm_cruise():
    """True PCM cruise: should NOT initialize"""
    print("Testing True PCM cruise (pcmCruise=True, openpilotLongitudinalControl=False)...")
    
    CP = car.CarParams(pcmCruise=True, openpilotLongitudinalControl=False)
    CP_SP = custom.CarParamsSP()
    v_cruise_helper = VCruiseHelper(CP, CP_SP)
    
    # Try to initialize
    v_cruise_helper.initialize_v_cruise(
        car.CarState(vEgo=50.0), 
        experimental_mode=False, 
        dynamic_experimental_control=False
    )
    
    # Should NOT be initialized (returns early)
    assert not v_cruise_helper.v_cruise_initialized, "v_cruise should NOT be initialized for true PCM!"
    assert v_cruise_helper.v_cruise_kph == V_CRUISE_UNSET, \
        f"Expected {V_CRUISE_UNSET} but got {v_cruise_helper.v_cruise_kph}"
    
    print("  ✓ True PCM cruise correctly skips initialization")
    print("  ✅ True PCM cruise test PASSED!\n")

def test_low_speed_clamping():
    """Test that low speeds are clamped to minimum"""
    print("Testing low speed clamping with experimental mode...")
    
    CP = car.CarParams(pcmCruise=True, openpilotLongitudinalControl=True)
    CP_SP = custom.CarParamsSP()
    v_cruise_helper = VCruiseHelper(CP, CP_SP)
    
    for _ in range(2):
        v_cruise_helper.update_v_cruise(car.CarState(cruiseState={"available": False}), enabled=False, is_metric=False)
    
    # Test very low speed (should clamp to V_CRUISE_INITIAL_EXPERIMENTAL_MODE = 105 kph)
    low_speed_ms = 10.0  # ~22 mph
    
    v_cruise_helper.initialize_v_cruise(
        car.CarState(vEgo=low_speed_ms), 
        experimental_mode=True, 
        dynamic_experimental_control=False
    )
    
    assert v_cruise_helper.v_cruise_initialized
    # Should be clamped to 105 kph (experimental mode minimum)
    assert v_cruise_helper.v_cruise_kph >= 105, \
        f"Expected at least 105 kph but got {v_cruise_helper.v_cruise_kph} kph"
    
    print(f"  ✓ Low speed {low_speed_ms} m/s clamped to {v_cruise_helper.v_cruise_kph} kph")
    print("  ✅ Low speed clamping test PASSED!\n")

if __name__ == "__main__":
    try:
        test_honda_nidec()
        test_true_pcm_cruise()
        test_low_speed_clamping()
        print("=" * 60)
        print("🎉 ALL TESTS PASSED!")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
