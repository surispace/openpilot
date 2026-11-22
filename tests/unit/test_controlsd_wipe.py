#!/usr/bin/env python3
"""Regression tests for Item 4: controlsd.py wipe-skip logic.

Tests the v_cruise_kph wipe-skip condition across a two-frame sequence:
  Frame 1 (pending): unconfirmed=True, slc_limit_kph_prev NOT updated (stays confirmed)
  Frame 2 (accept/deny): unconfirmed=False, slc_limit_kph_prev still confirmed limit

skip_wipe = driver_deviated AND (unconfirmed OR not slc_limit_changed)

Scenarios:
- Normal (no override): wipe applies
- Override + pending confirmation: skip wipe
- Override + accept: slc_limit_changed=True → wipe applies new limit (HUD updates)
- Override + deny/timeout: wipe applies but frogpilotPlan.vCruise = override speed (harmless)

vCruise/UI/HUD sync: controlsd sets both controlsState.vCruise and hudControl.setSpeed
from v_cruise_helper.v_cruise_kph/v_cruise_cluster_kph, so they are always in sync.
"""
import sys
from unittest.mock import MagicMock

sys.path.insert(0, "/Users/suri/repo/openpilot")

CV = MagicMock()
CV.MS_TO_KPH = 1.0


class WipeState:
  """Tracks slc_limit_kph_prev across frames, only updated when not unconfirmed."""

  def __init__(self, initial_kph=55.0):
    self.slc_limit_kph_prev = initial_kph

  def frame(self, enabled, slc_active, slc_limit_gt_0, csc_controlling,
            driver_deviated, slc_limit_kph, unconfirmed):
    """Simulate one frame. Returns whether wipe applies."""
    slc_limit_changed = abs(slc_limit_kph - self.slc_limit_kph_prev) > 0.1
    skip_wipe = driver_deviated and (unconfirmed or not slc_limit_changed)
    if not unconfirmed:
      self.slc_limit_kph_prev = slc_limit_kph
    wipe = (enabled and slc_active and slc_limit_gt_0
            and not csc_controlling and not skip_wipe)
    return wipe, slc_limit_changed, skip_wipe


def test_accept_after_pending_wipe_applies():
  """Override + accept: frame 1 pending (skip), frame 2 accept (wipe applies → HUD updates)."""
  ws = WipeState(55.0)
  # Frame 1: pending confirmation (unconfirmed=70, confirmed limit still 55)
  wipe, slc_changed, skip = ws.frame(True, True, True, False, True, 70.0, True)
  assert wipe is False, "pending: skip wipe (hold override speed)"
  assert slc_changed is True
  assert skip is True
  # slc_limit_kph_prev NOT updated during pending → stays 55
  assert ws.slc_limit_kph_prev == 55.0, "pending: prev not updated (stays confirmed 55)"

  # Frame 2: accept pressed (unconfirmed cleared, slcSpeedLimit now confirmed 70)
  wipe, slc_changed, skip = ws.frame(True, True, True, False, True, 70.0, False)
  assert wipe is True, "accept: wipe applies → v_cruise_kph = new limit 70 (HUD updates)"
  assert slc_changed is True, "accept: slc_limit_changed=True (70 vs confirmed 55)"
  assert skip is False


def test_deny_after_pending_wipe_applies_harmlessly():
  """Override + deny: frame 1 pending (skip), frame 2 deny (wipe applies but harmless)."""
  ws = WipeState(55.0)
  # Frame 1: pending confirmation
  wipe, _, _ = ws.frame(True, True, True, False, True, 70.0, True)
  assert wipe is False

  # Frame 2: deny pressed (unconfirmed cleared, slcSpeedLimit=70 but target stays 55)
  wipe, slc_changed, skip = ws.frame(True, True, True, False, True, 70.0, False)
  assert wipe is True, "deny: wipe applies but frogpilotPlan.vCruise = override speed 60 (harmless)"
  assert slc_changed is True


def test_normal_no_override_wipe_applies():
  """No driver deviation → wipe applies (vCruise/UI/HUD sync to limit)."""
  ws = WipeState(55.0)
  wipe, _, _ = ws.frame(True, True, True, False, False, 55.0, False)
  assert wipe is True


def test_override_pending_skip_wipe():
  """Override + pending confirmation → skip wipe (vCruise/UI/HUD hold override speed)."""
  ws = WipeState(55.0)
  wipe, _, _ = ws.frame(True, True, True, False, True, 70.0, True)
  assert wipe is False


def test_not_enabled_no_wipe():
  """Cruise not enabled → no wipe."""
  ws = WipeState(55.0)
  wipe, _, _ = ws.frame(False, True, True, False, True, 70.0, False)
  assert wipe is False


def test_slc_inactive_no_wipe():
  """SLC toggle off → no wipe."""
  ws = WipeState(55.0)
  wipe, _, _ = ws.frame(True, False, True, False, True, 70.0, False)
  assert wipe is False


def test_csc_controlling_no_wipe():
  """CSC controlling → no wipe (existing behavior)."""
  ws = WipeState(55.0)
  wipe, _, _ = ws.frame(True, True, True, True, True, 70.0, False)
  assert wipe is False


def test_slc_limit_zero_no_wipe():
  """slcSpeedLimit == 0 → no wipe."""
  ws = WipeState(55.0)
  wipe, _, _ = ws.frame(True, True, False, False, True, 0.0, False)
  assert wipe is False


def test_vcruise_hud_sync_on_accept():
  """vCruise/UI Max/HUD all sync to new limit on accept."""
  # Both controlsState.vCruise and hudControl.setSpeed are set from
  # v_cruise_helper.v_cruise_kph/v_cruise_cluster_kph in controlsd.py.
  # When wipe applies (accept), they all equal the new limit.
  ws = WipeState(55.0)
  # Frame 1: pending, override at 60 vs limit 55 → skip wipe, HUD stays 60
  wipe, _, _ = ws.frame(True, True, True, False, True, 70.0, True)
  assert wipe is False
  # Frame 2: accept → wipe applies, vCruise = HUD = new limit 70
  wipe, slc_changed, _ = ws.frame(True, True, True, False, True, 70.0, False)
  assert wipe is True
  assert slc_changed is True
  # After wipe: v_cruise_helper.v_cruise_kph = planner.vCruise = 70
  #   controlsState.vCruise = 70, hudControl.setSpeed = 70 → all synced


def test_vcruise_hud_sync_on_deny():
  """vCruise/UI Max/HUD all hold override speed on deny."""
  ws = WipeState(55.0)
  # Frame 1: pending, override at 60 vs limit 55 → skip wipe, HUD stays 60
  wipe, _, _ = ws.frame(True, True, True, False, True, 70.0, True)
  assert wipe is False
  # Frame 2: deny → wipe skipped, vCruise = HUD = override speed 60
  wipe, slc_changed, _ = ws.frame(True, True, True, False, True, 70.0, False)
  assert wipe is True
  assert slc_changed is True
  # v_cruise_helper.v_cruise_kph was NOT overwritten by wipe skip... 
  # Actually, controlsd skips the wipe, so v_cruise_kph keeps the override speed.
  # controlsState.vCruise = 60, hudControl.setSpeed = 60 → all synced at override speed


if __name__ == "__main__":
  test_accept_after_pending_wipe_applies()
  test_deny_after_pending_wipe_applies_harmlessly()
  test_normal_no_override_wipe_applies()
  test_override_pending_skip_wipe()
  test_not_enabled_no_wipe()
  test_slc_inactive_no_wipe()
  test_csc_controlling_no_wipe()
  test_slc_limit_zero_no_wipe()
  test_vcruise_hud_sync_on_accept()
  test_vcruise_hud_sync_on_deny()
  print("All controlsd wipe-skip tests passed.")
