"""
Copyright (c) 2026-, Zeph Leggett.

This file is part of zoompilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.

Camera-based speed limit sign reader, ported from FrogPilot's speed_limit_reader.

Reads road camera frames via VisionIPC, runs the FrogPilot speed limit reader model
(MNN), and publishes the detected speed limit into Params so the zoompilot speed limit
resolver can feed camera values in place of the dashboard (useful for cars like the
Honda Pilot 2019 that do not publish a dashboard speed limit).

This module intentionally imports MNN lazily so it can be imported in environments
without the MNN runtime (the resolver reads the persisted Params value directly).
"""
import json
import time

import numpy as np

from cereal import messaging
from msgq.visionipc import VisionIpcClient, VisionStreamType

from openpilot.common.params import Params
from openpilot.common.realtime import set_core_affinity
from openpilot.common.swaglog import cloudlog
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.speed_limit_reader_paths import (
  PARAM_SPEED_LIMIT_CAMERA_TS,
  PARAM_SPEED_LIMIT_CAMERA_VALUE,
  SPEED_LIMIT_READER_MODEL_DIR,
  SPEED_LIMIT_READER_MODEL_FILES,
)

LIVE_POSE_SERVICE = "liveLocationKalman"

SIGN_BOX_OUTPUTS = ("heldSignLeft", "heldSignTop", "heldSignRight", "heldSignBottom")

MODEL_INPUT_FRAME = "frame"
MODEL_INPUT_TEXT = "text"
MODEL_INPUT_CONTEXT = "context"


def _load_model(folder):
  """Load the MNN speed limit reader model. MNN is imported lazily so this module
  can be imported (and the resolver tested) on hosts without the MNN runtime."""
  try:
    import MNN
  except ImportError as e:
    cloudlog.exception("speed_limit_reader: MNN import failed — third_party/MNN not on PYTHONPATH: %s", e)
    return None

  model_file = folder / SPEED_LIMIT_READER_MODEL_FILES[0]
  if not model_file.is_file():
    cloudlog.error("speed_limit_reader: model file not found at %s", model_file)
    return None

  try:
    runtime = MNN.nn.create_runtime_manager(({"backend": "CPU", "numThread": 1},))
  except Exception as e:
    cloudlog.exception("speed_limit_reader: MNN runtime manager creation failed: %s", e)
    return None

  modes = []
  for mode in ("0", "1"):
    try:
      mod = MNN.nn.load_module_from_file(str(model_file), [MODEL_INPUT_FRAME, MODEL_INPUT_TEXT, MODEL_INPUT_CONTEXT], [mode], runtime_manager=runtime)
      modes.append(mod)
    except Exception as e:
      cloudlog.exception("speed_limit_reader: failed to load MNN model mode %s: %s", mode, e)
      return None

  cloudlog.info("speed_limit_reader: loaded MNN model %s with %d modes", model_file, len(modes))
  return modes


def _read(sm, field, map_match):
  service, path = field.split(".", 1)
  if service == LIVE_POSE_SERVICE:
    service = LIVE_POSE_SERVICE
    if path == "orientationNED.z":
      orientation = sm[service].orientationNED.value
      return orientation[2] if len(orientation) > 2 else 0.0
  if path == "alive":
    return sm.alive[service]
  return field.split(".")[-1] and getattr(sm[service], path)


def run(params: Params | None = None):
  """Main loop: read camera frames, run the model, persist the camera speed limit.

  Intended to be run as a standalone daemon process on device (like FrogPilot's
  speed_limit_reader). Reads camera frames from camerad's wide-road stream.
  """
  if params is None:
    params = Params()

  cloudlog.info("speed_limit_reader: starting camera speed limit reader daemon")

  set_core_affinity([6])

  modes = _load_model(SPEED_LIMIT_READER_MODEL_DIR)
  if modes is None:
    cloudlog.error("speed_limit_reader: failed to load MNN model; exiting")
    return

  try:
    inputs = json.loads(modes[0].get_info()["bizCode"])
  except (AttributeError, KeyError, json.JSONDecodeError) as e:
    cloudlog.exception("speed_limit_reader: model has no parseable bizCode inputs: %s", e)
    return

  cloudlog.info("speed_limit_reader: model bizCode inputs=%s outputs=%s", inputs.get("inputs"), inputs.get("outputs"))

  outputs = {name: index for index, name in enumerate(inputs["outputs"])}

  fields = inputs.get("numbers", []) + inputs.get("text", [])
  services = {field.split(".")[0] for field in fields}

  sm = messaging.SubMaster(sorted(services))
  try:
    for field in fields:
      _read(sm, field, {})
  except (AttributeError, KeyError) as e:
    cloudlog.exception("speed_limit_reader: model requests unsupported inputs: %s", e)
    return

  cloudlog.info("speed_limit_reader: subscribed to services %s", sorted(services))

  client = VisionIpcClient("camerad", VisionStreamType.VISION_STREAM_WIDE_ROAD, True)
  while not client.connect(False):
    cloudlog.warning("speed_limit_reader: waiting for camerad VisionIPC wide-road stream to connect...")
    time.sleep(1.0)

  cloudlog.info("speed_limit_reader: connected to camerad wide-road stream (width=%s height=%s stride=%s)", client.width, client.height, client.stride)

  state = np.zeros(len(outputs), np.float32)

  while True:
    buffer = client.recv(1000)
    sm.update(0)

    if buffer is None:
      cloudlog.debug("speed_limit_reader: no camera frame received this cycle")
      continue

    if client.frame_id < state[outputs.get("nextFrameId", 0)]:
      continue

    try:
      map_match = json.loads(params.get("MapMatchedWay") or "{}")

      text = np.frombuffer("\0".join(str(_read(sm, field, map_match)) for field in inputs.get("text", [])).encode(), np.uint8)
      numbers = [_read(sm, field, map_match) for field in inputs.get("numbers", [])]
      context = np.array([client.frame_id, buffer.width, buffer.height, buffer.stride, buffer.uv_offset, *numbers, *state], np.float32)

      import MNN
      frame_input = MNN.expr.const(buffer.data, [buffer.data.size], MNN.expr.NCHW, MNN.expr.uint8)
      text_input = MNN.expr.const(text, [text.size], MNN.expr.NCHW, MNN.expr.uint8)
      context_input = MNN.expr.const(context, [context.size], MNN.expr.NCHW, MNN.expr.float)

      state = modes[int(state[outputs.get("nextMode", 0)])].forward([frame_input, text_input, context_input])[0].read()
    except Exception as e:
      cloudlog.exception("speed_limit_reader: inference failed on frame %s: %s", client.frame_id, e)
      continue

    speed_limit = 0.0
    if "speedLimit" in outputs:
      try:
        speed_limit = float(state[outputs["speedLimit"]])
      except (TypeError, ValueError) as e:
        cloudlog.exception("speed_limit_reader: failed to parse speedLimit output: %s", e)
        speed_limit = 0.0

    if speed_limit >= 1.0:
      try:
        params.put(PARAM_SPEED_LIMIT_CAMERA_VALUE, str(speed_limit), block=False)
        params.put(PARAM_SPEED_LIMIT_CAMERA_TS, str(time.monotonic()), block=False)
      except Exception as e:
        cloudlog.exception("speed_limit_reader: failed to write camera speed limit to Params: %s", e)
        continue

      cloudlog.info("speed_limit_reader: camera speed limit %.2f m/s written to Params (frame_id=%s)", speed_limit, client.frame_id)
    else:
      cloudlog.debug("speed_limit_reader: no valid sign detected on frame %s (speed_limit=%.2f)", client.frame_id, speed_limit)
