import importlib.util
from pathlib import Path

import pytest


MODULE_PATH = Path(__file__).with_name("head_camera_control.py")
SPEC = importlib.util.spec_from_file_location("head_camera_control", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


@pytest.mark.parametrize(
    ("current", "direction", "step", "expected"),
    [
        (330, "up", 50, 380),
        (330, "down", 50, 280),
        (2580, "up", 50, 2600),
        (20, "down", 50, 0),
    ],
)
def test_lift_target_is_incremental_and_bounded(current, direction, step, expected):
    assert MODULE.LiftController.target_height(current, direction, step) == expected


@pytest.mark.parametrize("step", [0, 201])
def test_lift_target_rejects_unsafe_step(step):
    with pytest.raises(ValueError):
        MODULE.LiftController.target_height(330, "up", step)


def test_lift_target_rejects_unknown_direction():
    with pytest.raises(ValueError):
        MODULE.LiftController.target_height(330, "sideways", 50)


def test_lift_motion_accepts_normal_enabled_state():
    state = {"height": 330, "en_flag": 1, "err_flag": 0}
    assert MODULE.LiftController.validate_state_for_motion(state) == 330


@pytest.mark.parametrize(
    "state",
    [
        {"en_flag": 1, "err_flag": 0},
        {"height": 330, "en_flag": 0, "err_flag": 0},
        {"height": 330, "en_flag": 1, "err_flag": 2},
    ],
)
def test_lift_motion_rejects_invalid_or_faulted_state(state):
    with pytest.raises(RuntimeError):
        MODULE.LiftController.validate_state_for_motion(state)
