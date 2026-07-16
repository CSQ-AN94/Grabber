"""Orchestration tests for the full pick-and-return cycle (no hardware).

These lock in the safety-critical sequencing of run_full_cycle():
forward transit corridor -> grasp -> place back -> return-to-observation ->
reverse corridor; plan-only validates the corridor without any motion; and a
start pose off the corridor entry aborts before moving.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import bottle_grasp.demo as demo_module
from bottle_grasp.core import DemoParams, Localization, SafetyAbort

CORRIDOR = [
    [0, 0, 0, 0, 0, 0, 0],
    [5, 5, 5, 5, 5, 5, 5],
    [10, 10, 10, 10, 10, 10, 10],
]


class _FakeRobot:
    def __init__(self, calls, joints):
        self.calls = calls
        self._j = list(joints)

    def current_tcp(self):
        return np.eye(4)

    def gripper_state(self):
        return {"enable_state": 1}

    def joints_deg(self):
        return list(self._j)

    def validate_planned_joints(self, pts, step, safety, start_joints_deg=None):
        self.calls.append(("validate", len(pts)))
        return len(pts) * 3

    def execute_planned_joints(self, pts, speed, step):
        self.calls.append(("execute", len(pts)))
        self._j = list(pts[-1])

    def open_gripper(self, params=None):
        self.calls.append(("open_gripper",))


class _FakeSafety:
    guided_start_tolerance_deg = 3.0

    def assert_tcp_point(self, point, label=""):
        pass


def _make_demo(calls, *, execute, start_joints):
    demo = demo_module.BottleDemo.__new__(demo_module.BottleDemo)

    class Args:
        pass

    demo.args = Args()
    demo.args.execute = execute
    demo.args.plan_only = not execute
    demo.args.full_cycle = True
    demo.args.restore_teleop = False
    demo.args.observe_seconds = 0
    demo.params = DemoParams()
    demo.guided_path = {"points_deg": [list(p) for p in CORRIDOR]}
    demo.robot = _FakeRobot(calls, start_joints)
    demo.safety = _FakeSafety()
    demo.stage = lambda name, msg="": calls.append(("stage", name))
    demo.initialize = lambda: calls.append(("initialize",))
    demo._build_head_scene = lambda target: calls.append(("build_head_scene",))
    demo._start_camera = lambda name: calls.append(("start_camera", name))
    demo._grasp_and_lift = lambda target: calls.append(("grasp_and_lift",))
    demo._place_back = lambda: calls.append(("place_back",))
    loc = Localization(
        [0, 0, 0.5], [0, 0.6, -0.05], [320, 240], 0.5, 0.001, 0.002,
        [0, 0, 10, 10], 0.9, 7,
    )
    demo.localize = lambda *a, **k: (calls.append(("localize",)), loc)[1]
    return demo


def test_full_cycle_execute_sequence(monkeypatch):
    monkeypatch.setattr(demo_module.time, "sleep", lambda s: None)
    calls = []
    demo = _make_demo(calls, execute=True, start_joints=CORRIDOR[0])
    demo.run_full_cycle()

    # forward corridor and reverse corridor are both the full 3-point path
    assert sum(1 for c in calls if c == ("execute", 3)) == 2
    # a single-waypoint hop back onto the corridor end (observation pose)
    assert ("execute", 1) in calls

    order = [
        calls.index(("execute", 3)),      # forward transit
        calls.index(("grasp_and_lift",)),
        calls.index(("place_back",)),
        calls.index(("execute", 1)),      # return to observation
    ]
    assert order == sorted(order)


def test_plan_only_validates_without_motion(monkeypatch):
    monkeypatch.setattr(demo_module.time, "sleep", lambda s: None)
    calls = []
    demo = _make_demo(calls, execute=False, start_joints=CORRIDOR[0])
    demo.run_full_cycle()

    assert not any(c[0] == "execute" for c in calls if isinstance(c, tuple))
    assert ("grasp_and_lift",) not in calls
    assert any(c[0] == "validate" for c in calls if isinstance(c, tuple))


def test_off_corridor_start_aborts(monkeypatch):
    monkeypatch.setattr(demo_module.time, "sleep", lambda s: None)
    calls = []
    demo = _make_demo(calls, execute=True, start_joints=[50, 0, 0, 0, 0, 0, 0])
    with pytest.raises(SafetyAbort, match="垂下"):
        demo.run_full_cycle()
    assert not any(c[0] == "execute" for c in calls if isinstance(c, tuple))
