"""--autonomous-observation branch selection (no hardware).

table_demo's safety profile normally ships a recorded guided_path for the
head->observation leg. --autonomous-observation must force MoveIt free
planning (_select_observation_flange + _plan_flange) instead, ignoring any
configured corridor; without the flag, an existing corridor still wins
(unchanged prior behavior), and no corridor still falls back to autonomous.
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import bottle_grasp.demo as demo_module
from bottle_grasp.core import Localization


def _make_demo(calls, *, autonomous_observation, has_guided_path):
    demo = demo_module.BottleDemo.__new__(demo_module.BottleDemo)

    class Args:
        pass

    demo.args = Args()
    demo.args.execute = False
    demo.args.plan_only = True
    demo.args.full_cycle = False
    demo.args.resume_at_wrist = False
    demo.args.stop_after_observation = False
    demo.args.autonomous_observation = autonomous_observation
    demo.args.observe_seconds = 0
    demo.params = demo_module.DemoParams()
    demo.guided_path = (
        {"points_deg": [[0.0] * 7, [1.0] * 7]} if has_guided_path else None
    )

    class FakeCalibration:
        T_base_right_to_camera_head = np.eye(4)

    class FakeConfig:
        calibration = FakeCalibration()

    demo.cfg = FakeConfig()

    class FakeSafety:
        def assert_tcp_point(self, point, label=""):
            pass

    demo.safety = FakeSafety()
    demo.stage = lambda name, msg="": calls.append(("stage", name))
    demo.initialize = lambda: calls.append(("initialize",))
    demo._build_head_scene = lambda target: calls.append(("build_head_scene",))
    demo._guided_observation_plan = lambda: (
        calls.append(("guided_plan",)),
        {"points_deg": [[0.0] * 7]},
    )[1]
    demo._select_observation_flange = lambda target: (
        calls.append(("select_flange",)),
        (np.eye(4), [0.0] * 7),
    )[1]
    demo._plan_flange = lambda name, flange, goal: (
        calls.append(("autonomous_plan", name)),
        {"points_deg": [[0.0] * 7]},
    )[1]
    loc = Localization(
        [0, 0, 0.5], [0, 0.6, -0.05], [320, 240], 0.5, 0.001, 0.002,
        [0, 0, 10, 10], 0.9, 7,
    )
    demo.localize = lambda *a, **k: (calls.append(("localize",)), loc)[1]
    return demo


def test_guided_path_used_by_default():
    calls = []
    demo = _make_demo(calls, autonomous_observation=False, has_guided_path=True)
    demo.run()
    assert ("guided_plan",) in calls
    assert not any(c[0] == "autonomous_plan" for c in calls if isinstance(c, tuple))


def test_autonomous_observation_overrides_guided_path():
    calls = []
    demo = _make_demo(calls, autonomous_observation=True, has_guided_path=True)
    demo.run()
    assert ("guided_plan",) not in calls
    assert ("select_flange",) in calls
    assert any(c[0] == "autonomous_plan" for c in calls if isinstance(c, tuple))


def test_no_guided_path_falls_back_to_autonomous():
    calls = []
    demo = _make_demo(calls, autonomous_observation=False, has_guided_path=False)
    demo.run()
    assert ("guided_plan",) not in calls
    assert any(c[0] == "autonomous_plan" for c in calls if isinstance(c, tuple))
