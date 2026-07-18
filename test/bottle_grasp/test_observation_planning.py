"""run() observation-leg orchestration (no hardware).

The guided teaching corridor was removed (2026-07-17): the head->observation
leg always goes through MoveIt free planning (_select_observation_flange +
_plan_flange). This exercises the plan-only orchestration with everything
below the state machine mocked out.
"""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import bottle_grasp.demo as demo_module
from bottle_grasp.core import Localization, SafetyAbort


def _make_demo(calls):
    demo = demo_module.BottleDemo.__new__(demo_module.BottleDemo)

    class Args:
        pass

    demo.args = Args()
    demo.args.execute = False
    demo.args.plan_only = True
    demo.args.resume_at_wrist = False
    demo.args.stop_after_observation = False
    demo.args.observe_seconds = 0
    demo.params = demo_module.DemoParams()

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
    demo._select_observation_flange = lambda target: (
        calls.append(("select_flange",)),
        (np.eye(4), [0.0] * 7),
    )[1]
    demo._plan_flange = lambda name, flange, goal: (
        calls.append(("autonomous_plan", name)),
        {"points_deg": [[0.0] * 7]},
    )[1]
    demo._plan_observation = lambda target: (
        calls.append(("safe_observation_plan",)),
        {"points_deg": [[0.0] * 7]},
    )[1]
    loc = Localization(
        [0, 0, 0.5], [0, 0.6, -0.05], [320, 240], 0.5, 0.001, 0.002,
        [0, 0, 10, 10], 0.9, 7,
    )
    demo.localize = lambda *a, **k: (calls.append(("localize",)), loc)[1]
    return demo


def test_run_plans_observation_autonomously():
    calls = []
    demo = _make_demo(calls)
    demo.run()
    assert ("initialize",) in calls
    assert ("localize",) in calls
    assert ("build_head_scene",) in calls
    assert ("safe_observation_plan",) in calls


def test_fence_rejected_moveit_plan_is_replanned_before_execution():
    """Replay the real table-edge failure: reject plan 1, accept plan 2."""
    calls = []
    demo = demo_module.BottleDemo.__new__(demo_module.BottleDemo)
    demo.params = demo_module.DemoParams()
    demo.scene_voxels = []
    demo.scene_boxes = [{"id": "fence_table_top"}]
    demo.stage = lambda name, msg="": calls.append(("stage", name, msg))

    class FakeSafety:
        moveit_frame = "platform_base_link"

        @staticmethod
        def pose_to_moveit(pose):
            return pose

        @staticmethod
        def points_to_moveit(points):
            return list(points)

        @staticmethod
        def moveit_workspace():
            return {"min": [-1, -1, -1], "max": [1, 1, 1]}

    class FakeRobot:
        @staticmethod
        def joints_deg():
            return [0.0] * 7

        @staticmethod
        def validate_planned_joints(
            points, max_step, safety, start_joints_deg=None
        ):
            attempt = int(points[0][0])
            calls.append(("validate", attempt))
            if attempt == 1:
                raise SafetyAbort(
                    "轨迹 TCP 点 54 进入禁入区 table_top: "
                    "[0.2797, 0.3385, -0.4709]"
                )
            return 120

    class FakeLeftRobot:
        @staticmethod
        def joints_deg():
            return [0.0] * 7

    class FakePlanner:
        attempts = 0

        def plan(self, **kwargs):
            self.attempts += 1
            calls.append(("plan", self.attempts))
            return {
                "success": True,
                "points_deg": [[float(self.attempts)] * 7],
                "planning_time": 0.01,
            }

        @staticmethod
        def validate_exact_path(**kwargs):
            return {"checked_states": len(kwargs["points_deg"])}

    demo.safety = FakeSafety()
    demo.robot = FakeRobot()
    demo.left_robot = FakeLeftRobot()
    demo.planner = FakePlanner()

    plan = demo._plan_flange("moveit_observation", np.eye(4), [0.0] * 7)

    assert demo.planner.attempts == 2
    assert plan["points_deg"] == [[2.0] * 7]
    assert calls.index(("validate", 1)) < calls.index(("plan", 2))


def _precheck_demo(calls):
    """Demo stub with only what _observation_plan_targets touches."""
    demo = demo_module.BottleDemo.__new__(demo_module.BottleDemo)
    demo.params = demo_module.DemoParams()
    demo.stage = lambda name, msg="": calls.append(("stage", name, msg))

    class FakeCalibration:
        T_end_right_to_camera_rightwrist = np.eye(4)

    class FakeConfig:
        calibration = FakeCalibration()

    demo.cfg = FakeConfig()

    class FakeSafety:
        def assert_tcp_point(self, point, *, label=""):
            pass

    demo.safety = FakeSafety()
    return demo


def test_observation_candidates_near_joint_limit_are_rejected_by_precheck():
    """2026-07-18 真机复现：端点 J2=129.2° 过了 3° 硬余量，但从那里出发的
    抓取接近段全部死于限位——预检必须在选观察位时就把它淘汰。"""
    calls = []
    demo = _precheck_demo(calls)

    class NearLimitRobot:
        def joints_deg(self):
            return [0.0] * 7

        def solve_flange_ik(self, flange, params):
            return [0.0, 129.2, 0.0, 30.0, 0.0, 0.0, 0.0]

        def plan_ik(self, poses, params, *, allow_first_jump=False,
                    seed_joints_deg=None):
            # 预检用软余量：J2=129.2 距限位不足 observation_grasp_margin_deg
            assert seed_joints_deg is not None
            assert params.joint_limit_margin_deg == demo.params.observation_grasp_margin_deg
            raise SafetyAbort("路径点 1 关节 J2 距限位过近: 129.2°")

    demo.robot = NearLimitRobot()
    with pytest.raises(SafetyAbort, match="全部未通过抓取预检"):
        demo._observation_plan_targets(np.array([0.0, 0.52, -0.11]))


def test_graspable_candidates_survive_and_keep_transfer_cost_order():
    calls = []
    demo = _precheck_demo(calls)

    class HealthyRobot:
        def __init__(self):
            self.solve_count = 0

        def joints_deg(self):
            return [0.0] * 7

        def solve_flange_ik(self, flange, params):
            self.solve_count += 1
            return [float(self.solve_count % 5)] * 7

        def plan_ik(self, poses, params, *, allow_first_jump=False,
                    seed_joints_deg=None):
            return [[0.0] * 7 for _ in poses]

    demo.robot = HealthyRobot()
    targets = demo._observation_plan_targets(np.array([0.0, 0.52, -0.11]))
    assert targets
    scores = [target.score for target in targets]
    assert scores == sorted(scores)
    assert any(
        "抓取预检通过" in msg for _, name, msg in calls if name == "生成右腕观察位候选"
    )
