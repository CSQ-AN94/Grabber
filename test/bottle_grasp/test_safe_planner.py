"""SafeMotionPlanner interface tests; no ROS or robot hardware."""

from pathlib import Path

import numpy as np
import pytest

from bottle_grasp.core import DemoParams, SafetyAbort
from bottle_grasp.safe_planner import PlanTarget, SafeMotionPlanner
from bottle_grasp.safety import load_safety_profile


class FakeLeftRobot:
    @staticmethod
    def joints_deg():
        return [0.0] * 7


def _profile():
    return load_safety_profile(
        Path(__file__).parents[2] / "bottle_grasp" / "safety_profiles.json",
        "table_demo",
        require_verified=False,
    )


def _target(label: str, score: float, value: float) -> PlanTarget:
    return PlanTarget(
        label=label,
        flange=np.eye(4),
        goal_joints=tuple([value] * 7),
        score=score,
    )


def test_fence_violation_becomes_moveit_feedback_box():
    safety = _profile()

    class FakeMoveIt:
        def __init__(self):
            self.calls = []

        def plan(self, **kwargs):
            self.calls.append(kwargs)
            attempt = len(self.calls)
            return {"points_deg": [[float(attempt)] * 7]}

        @staticmethod
        def validate_exact_path(**kwargs):
            return {"checked_states": len(kwargs["points_deg"])}

    class FakeRobot:
        @staticmethod
        def joints_deg():
            return [0.0] * 7

        @staticmethod
        def validate_planned_joints(
            points, max_step, profile, start_joints_deg=None
        ):
            if int(points[0][0]) == 1:
                profile.assert_tcp_point(
                    [0.2797, 0.3385, -0.4709], label="轨迹 TCP 点 54"
                )
            return 120

    moveit = FakeMoveIt()
    planner = SafeMotionPlanner(
        moveit=moveit,
        robot=FakeRobot(),
        left_robot=FakeLeftRobot(),
        safety=safety,
        params=DemoParams(),
    )

    result = planner.plan(
        name="observe",
        targets=[_target("candidate", 0.0, 0.0)],
        obstacle_points=[],
        collision_boxes=safety.moveit_collision_boxes(),
    )

    assert result.attempts == 2
    assert result.checked_tcp_points == 120
    assert len(moveit.calls[1]["boxes"]) == len(moveit.calls[0]["boxes"]) + 1
    assert moveit.calls[1]["boxes"][-1]["id"] == "replan_01"


def test_rejected_endpoint_falls_back_to_next_ranked_candidate():
    safety = _profile()

    class FakeMoveIt:
        def plan(self, **kwargs):
            value = float(kwargs["goal_joints_deg"][0])
            return {"points_deg": [[value] * 7]}

        @staticmethod
        def validate_exact_path(**kwargs):
            return {"checked_states": len(kwargs["points_deg"])}

    class FakeRobot:
        @staticmethod
        def joints_deg():
            return [0.0] * 7

        @staticmethod
        def validate_planned_joints(
            points, max_step, profile, start_joints_deg=None
        ):
            if int(points[0][0]) == 1:
                raise SafetyAbort("first endpoint path rejected")
            return 40

    planner = SafeMotionPlanner(
        moveit=FakeMoveIt(),
        robot=FakeRobot(),
        left_robot=FakeLeftRobot(),
        safety=safety,
        params=DemoParams(global_plan_attempts_per_candidate=1),
    )

    result = planner.plan(
        name="observe",
        targets=[_target("first", 1.0, 1.0), _target("second", 2.0, 2.0)],
        obstacle_points=[],
        collision_boxes=[],
    )

    assert result.target.label == "second"
    assert result.attempts == 2


def test_replanning_is_bounded_and_reports_aggregate_rejections():
    safety = _profile()

    class FakeMoveIt:
        attempts = 0

        def plan(self, **kwargs):
            self.attempts += 1
            return {"points_deg": [[float(self.attempts)] * 7]}

        @staticmethod
        def validate_exact_path(**kwargs):
            return {"checked_states": len(kwargs["points_deg"])}

    class FakeRobot:
        @staticmethod
        def joints_deg():
            return [0.0] * 7

        @staticmethod
        def validate_planned_joints(
            points, max_step, profile, start_joints_deg=None
        ):
            raise SafetyAbort("still unsafe")

    moveit = FakeMoveIt()
    planner = SafeMotionPlanner(
        moveit=moveit,
        robot=FakeRobot(),
        left_robot=FakeLeftRobot(),
        safety=safety,
        params=DemoParams(
            global_plan_max_candidates=2,
            global_plan_attempts_per_candidate=2,
        ),
    )

    with pytest.raises(SafetyAbort, match="4 次安全规划") as failure:
        planner.plan(
            name="observe",
            targets=[_target("first", 1.0, 1.0), _target("second", 2.0, 2.0)],
            obstacle_points=[],
            collision_boxes=[],
        )

    assert moveit.attempts == 4
    assert "still unsafe" in str(failure.value)


def test_moveit_post_validation_rejection_also_replans():
    safety = _profile()

    class FakeMoveIt:
        attempts = 0
        validations = 0

        def plan(self, **kwargs):
            self.attempts += 1
            return {"points_deg": [[float(self.attempts)] * 7]}

        def validate_exact_path(self, **kwargs):
            self.validations += 1
            if self.validations == 1:
                raise SafetyAbort("full-arm collision at state 3")
            return {"checked_states": len(kwargs["points_deg"])}

    class FakeRobot:
        @staticmethod
        def joints_deg():
            return [0.0] * 7

        @staticmethod
        def validate_planned_joints(
            points, max_step, profile, start_joints_deg=None
        ):
            return 10

    moveit = FakeMoveIt()
    planner = SafeMotionPlanner(
        moveit=moveit,
        robot=FakeRobot(),
        left_robot=FakeLeftRobot(),
        safety=safety,
        params=DemoParams(),
    )

    result = planner.plan(
        name="observe",
        targets=[_target("candidate", 0.0, 0.0)],
        obstacle_points=[],
        collision_boxes=[],
    )

    assert result.attempts == 2
    assert moveit.validations == 2
