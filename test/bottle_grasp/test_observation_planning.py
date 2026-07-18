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
        def controller_flange_from_joints(_joints):
            return np.eye(4)

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


def test_candidates_failing_even_the_hard_margin_are_rejected():
    """2026-07-18 真机复现：从端点出发的抓取接近段死于限位（任何余量档位
    都过不了）——预演必须在选观察位时就把它淘汰，档位要一路降到执行余量。"""
    calls = []
    demo = _precheck_demo(calls)
    margins_seen = []

    class NearLimitRobot:
        def joints_deg(self):
            return [0.0] * 7

        def solve_flange_ik(self, flange, params):
            return [0.0, 129.2, 0.0, 30.0, 0.0, 0.0, 0.0]

        def plan_ik(self, poses, params, *, allow_first_jump=False,
                    seed_joints_deg=None):
            assert seed_joints_deg is not None
            margins_seen.append(params.joint_limit_margin_deg)
            raise SafetyAbort("路径点 1 关节 J2 距限位过近: 129.2°")

    demo.robot = NearLimitRobot()
    with pytest.raises(SafetyAbort, match="全部未通过抓取预演"):
        demo._observation_plan_targets(np.array([0.0, 0.52, -0.11]))
    # 降级尝试必须覆盖从软余量到执行余量的全部档位，最宽的先试
    assert max(margins_seen) == demo.params.observation_grasp_margin_deg
    assert min(margins_seen) == demo.params.joint_limit_margin_deg


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
    assert all(target.goal_constraint == "joints" for target in targets)
    scores = [target.score for target in targets]
    assert scores == sorted(scores)
    assert any(
        "抓取预演可行" in msg for _, name, msg in calls if name == "生成右腕观察位候选"
    )


def test_tight_margin_candidates_are_kept_but_ranked_after_roomy_ones():
    """2026-07-18 晚真机 watch 复现：10° 二元筛选把 11 个端点砍到 1 个，
    唯一幸存者 MoveIt 规划失败（error=99999）后没有任何备胎直接中止。
    分级录取必须保住窄余量候选作为后备，同时让宽余量的排前面。"""
    calls = []
    demo = _precheck_demo(calls)
    wide = demo.params.observation_grasp_margin_deg

    class MixedRobot:
        def __init__(self):
            self.solve_count = 0

        def joints_deg(self):
            return [0.0] * 7

        def solve_flange_ik(self, flange, params):
            self.solve_count += 1
            # 第一个候选给最大的转移代价，其余递减——用来验证排序不只看代价
            return [float(50 - self.solve_count % 5)] * 7

        def plan_ik(self, poses, params, *, allow_first_jump=False,
                    seed_joints_deg=None):
            # 只有第一个解出的候选（转移代价最大）通过宽余量；
            # 其余候选只在执行余量（3°）下可行。
            first_candidate = seed_joints_deg[0] == 49.0
            if first_candidate:
                return [[0.0] * 7 for _ in poses]
            if params.joint_limit_margin_deg > demo.params.joint_limit_margin_deg:
                raise SafetyAbort("路径点 1 关节 J2 距限位过近")
            return [[0.0] * 7 for _ in poses]

    demo.robot = MixedRobot()
    targets = demo._observation_plan_targets(np.array([0.0, 0.52, -0.11]))
    # 窄余量候选全部保留（没有被一刀切淘汰）
    assert len(targets) > 1
    # 宽余量候选排第一；其后存在转移代价更小的窄余量候选——证明排序是
    # "余量档位优先于转移代价"，而不是单纯按代价排
    assert targets[0].goal_joints[0] == 49.0
    assert any(
        target.score < targets[0].score for target in targets[1:]
    )
