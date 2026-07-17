"""_return_home / --finish-from-current orchestration (no hardware).

2026-07-17: the removed guided corridor used to also carry the robot back to
its hang pose. This restores a "go home" leg using the same trusted mechanism
already used for the observation leg (MoveIt plan + electronic-fence dense
check inside _plan_flange), driven by a single home_joints_deg target stored
in the safety profile instead of a recorded corridor.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import bottle_grasp.demo as demo_module
from bottle_grasp.core import SafetyAbort
from bottle_grasp.safety import load_safety_profile


def test_table_demo_profile_has_home_joints_deg():
    profile = load_safety_profile(
        Path(__file__).parents[2] / "bottle_grasp" / "safety_profiles.json",
        "table_demo",
        require_verified=False,
    )
    assert profile.home_joints_deg is not None
    assert len(profile.home_joints_deg) == 7


def test_shelf_template_has_no_home_joints_deg():
    # shelf_template is a disabled placeholder profile (load_safety_profile
    # refuses disabled profiles), so check the raw config instead.
    import json

    data = json.loads(
        (
            Path(__file__).parents[2] / "bottle_grasp" / "safety_profiles.json"
        ).read_text()
    )
    assert "home_joints_deg" not in data["profiles"]["shelf_template"]


def _make_demo(calls):
    demo = demo_module.BottleDemo.__new__(demo_module.BottleDemo)
    demo.params = demo_module.DemoParams()

    class FakeSafety:
        name = "fake"
        home_joints_deg = (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)

    demo.safety = FakeSafety()
    demo.stage = lambda name, msg="": calls.append(("stage", name))

    class FakeRobot:
        def controller_flange_from_joints(self, joints):
            calls.append(("fk", tuple(joints)))
            return np.eye(4)

        def joints_deg(self):
            return [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0]

    demo.robot = FakeRobot()
    demo._plan_flange = lambda name, flange, goal_joints=None: (
        calls.append(("plan", name, tuple(goal_joints))),
        {"points_deg": [[0.0] * 7]},
    )[1]
    demo._execute_plan = lambda name, plan: calls.append(("execute", name))
    return demo


def test_return_home_plans_and_executes_to_profile_target():
    calls = []
    demo = _make_demo(calls)
    demo._return_home()
    assert ("plan", "moveit_return_home", (1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0)) in calls
    assert any(c[0] == "execute" for c in calls)


def test_return_home_aborts_without_configured_target():
    calls = []
    demo = _make_demo(calls)
    demo.safety.home_joints_deg = None
    with pytest.raises(SafetyAbort, match="home_joints_deg"):
        demo._return_home()


def test_finish_from_current_skips_localization_and_grasp():
    calls = []
    demo = _make_demo(calls)
    demo.args = type("Args", (), {})()
    demo.args.place_back = True
    demo.args.return_home = True
    demo.args.restore_teleop = False
    demo.stop_event = __import__("threading").Event()
    demo.stop_event.set()  # exit the hold loop immediately
    demo._place_back = lambda: calls.append(("place_back",))
    demo._return_home = lambda: calls.append(("return_home",))
    demo._finish_from_current()
    actions = [c for c in calls if c[0] in ("place_back", "return_home")]
    assert actions == [("place_back",), ("return_home",)]


def test_place_back_closes_empty_gripper_only_after_retreat():
    """The fingers stay open until every post-release retreat point completes."""
    calls = []
    demo = demo_module.BottleDemo.__new__(demo_module.BottleDemo)
    demo.params = demo_module.DemoParams()
    demo.stage = lambda name, msg="": calls.append(("stage", name))

    class FakeSafety:
        def assert_tcp_point(self, point, *, label):
            calls.append(("fence", label))

    class FakeRobot:
        def current_tcp(self):
            return np.eye(4)

        def escape_j4_singularity(self, params, safety_profile):
            calls.append(("escape_check",))
            return None  # 起点不在奇异带

        def move_linear(self, pose, speed):
            calls.append(("move", tuple(pose)))

        def open_gripper(self, params):
            calls.append(("open",))

        def close_empty_gripper(self, params):
            calls.append(("close_empty",))

    demo.safety = FakeSafety()
    demo.robot = FakeRobot()
    demo._plan_ik_avoiding_singularity = (
        lambda path, params, **kwargs: path
    )

    demo._place_back()

    retreat_stage = calls.index(("stage", "退开"))
    close_index = calls.index(("close_empty",))
    last_move = max(i for i, call in enumerate(calls) if call[0] == "move")
    completed_stage = calls.index(("stage", "放回完成"))
    assert retreat_stage < last_move < close_index < completed_stage
