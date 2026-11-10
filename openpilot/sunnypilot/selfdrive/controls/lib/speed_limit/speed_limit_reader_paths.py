"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from pathlib import Path

from openpilot.common.basedir import BASEDIR

SPEED_LIMIT_READER_MODEL_DIR = Path(BASEDIR) / "openpilot/sunnypilot/selfdrive/assets/models"
SPEED_LIMIT_READER_MODEL_FILES = ("speed_limit_reader.mnn",)
SIGN_IMAGE_MARGIN = 0.5

# Params keys used by the camera speed limit reader and the resolver
PARAM_SPEED_LIMIT_CAMERA_ENABLED = "SpeedLimitCameraEnabled"
PARAM_SPEED_LIMIT_CAMERA_VALUE = "SpeedLimitCameraValue"
PARAM_SPEED_LIMIT_CAMERA_TS = "SpeedLimitCameraTimestamp"

# Maximum age (seconds) of a camera reading before it is treated as stale.
CAMERA_MAX_AGE_SEC = 2.0
