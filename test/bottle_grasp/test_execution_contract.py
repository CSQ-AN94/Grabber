import threading
import time
from types import SimpleNamespace

import numpy as np
import pytest

from bottle_grasp.core import DemoParams, SafetyAbort
from bottle_grasp.demo import BottleDemo
from bottle_grasp.robot import RobotSession


class _Arm:
    def __init__(self, *, follow: bool):
        self.follow = follow
        self.current = [0.0] * 7
        self.moves = []

    def rm_movej(self, joints, _speed, _trajectory_connect, _radius, _block):
        self.moves.append(list(joints))
        if self.follow:
            self.current = list(joints)
        return 0


def _session(*, follow: bool):
    session = RobotSession.__new__(RobotSession)
    session.take_control = True
    session.stop_event = threading.Event()
    session.arm = _Arm(follow=follow)
    session.joints_deg = lambda: list(session.arm.current)
    session.current_tcp = lambda: np.eye(4)
    return session


def test_planned_path_rejects_stale_real_robot_start_before_move():
    session = _session(follow=True)
    session.arm.current = [2.0] * 7

    with pytest.raises(SafetyAbort, match="轨迹已过期"):
        session.execute_planned_joints(
            [[3.0] * 7],
            3,
            1.5,
            expected_start_joints_deg=[0.0] * 7,
            start_tolerance_deg=0.8,
        )

    assert session.arm.moves == []


def test_planned_path_stops_when_blocking_move_feedback_does_not_follow():
    session = _session(follow=False)

    with pytest.raises(SafetyAbort, match="执行反馈偏差过大"):
        session.execute_planned_joints(
            [[1.0] * 7],
            3,
            1.5,
            expected_start_joints_deg=[0.0] * 7,
            tracking_tolerance_deg=0.5,
        )

    assert len(session.arm.moves) == 1


def test_planned_path_accepts_fresh_start_and_following_feedback():
    session = _session(follow=True)

    session.execute_planned_joints(
        [[2.0] * 7],
        3,
        1.5,
        expected_start_joints_deg=[0.0] * 7,
    )

    np.testing.assert_allclose(session.arm.current, [2.0] * 7)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_planned_path_rejects_nonfinite_joint_feedback(bad):
    session = _session(follow=True)
    original = session.joints_deg
    reads = 0

    def feedback():
        nonlocal reads
        reads += 1
        values = original()
        if reads >= 2:
            values[3] = bad
        return values

    session.joints_deg = feedback
    session.hold = lambda: None

    with pytest.raises(SafetyAbort, match="反馈含非有限数"):
        session.execute_planned_joints(
            [[1.0] * 7],
            3,
            1.5,
            expected_start_joints_deg=[0.0] * 7,
        )


def _execution_demo(*, left_joints=None):
    demo = BottleDemo.__new__(BottleDemo)
    demo.args = SimpleNamespace(task_mode="from-start")
    demo.params = DemoParams()
    demo.stop_event = threading.Event()
    demo.stage = lambda *_args, **_kwargs: None

    class Left:
        @staticmethod
        def joints_deg():
            return list([0.0] * 7 if left_joints is None else left_joints)

    class Right:
        calls = 0

        @classmethod
        def execute_planned_joints(cls, *_args, **_kwargs):
            cls.calls += 1

        @staticmethod
        def hold():
            return None

    demo.left_robot = Left()
    demo.robot = Right()
    return demo


def _fresh_plan():
    return {
        "points_deg": [[0.0] * 7],
        "start_joints_deg": [0.0] * 7,
        "start_left_joints_deg": [0.0] * 7,
        "scene_captured_monotonic": time.monotonic(),
    }


def test_global_execution_rejects_stale_rgbd_scene_before_motion():
    demo = _execution_demo()
    plan = _fresh_plan()
    plan["scene_captured_monotonic"] -= demo.params.scene_max_age_s + 1.0

    with pytest.raises(SafetyAbort, match="规划场景已过期"):
        demo._execute_plan("test", plan)

    assert demo.robot.calls == 0


def test_global_execution_rejects_left_arm_snapshot_drift_before_motion():
    demo = _execution_demo(left_joints=[2.0] * 7)

    with pytest.raises(SafetyAbort, match="左臂已偏离"):
        demo._execute_plan("test", _fresh_plan())

    assert demo.robot.calls == 0


def test_scene_age_is_rechecked_after_blocking_left_arm_read(monkeypatch):
    """Regression: a 44s scene must not execute at 46s after an SSH read."""
    demo = _execution_demo()
    now = [144.0]

    def delayed_left_read():
        now[0] = 146.0
        return [0.0] * 7

    demo.left_robot.joints_deg = delayed_left_read
    monkeypatch.setattr("bottle_grasp.demo.time.monotonic", lambda: now[0])
    plan = _fresh_plan()
    plan["scene_captured_monotonic"] = 100.0

    with pytest.raises(SafetyAbort, match="规划场景已过期"):
        demo._execute_plan("test", plan)

    assert demo.robot.calls == 0


def test_local_task_path_uses_moveit_and_removes_only_target_cylinder():
    demo = BottleDemo.__new__(BottleDemo)
    demo.args = SimpleNamespace(task_mode="from-observation")
    demo.params = DemoParams()
    demo.stage = lambda *_args, **_kwargs: None
    demo.scene_boxes = [{"id": "table"}]
    demo.scene_voxels = [
        [0.01, 0.0, 0.05],  # locked bottle cylinder: contact is intentional
        [0.05, 0.0, 0.05],  # neighbouring object: must remain
        [0.0, 0.0, -0.06],  # table below cylinder: must remain
    ]
    calls = []

    class Safety:
        moveit_frame = "platform_base_link"

        @staticmethod
        def points_to_moveit(points):
            return points

    class Right:
        @staticmethod
        def joints_deg():
            return [0.0] * 7

        @staticmethod
        def validate_planned_joints(*_args, **_kwargs):
            calls.append("sdk")
            return 1

    class Left:
        @staticmethod
        def joints_deg():
            return [0.0] * 7

    class Planner:
        @staticmethod
        def validate_exact_path(**kwargs):
            calls.append(("moveit", kwargs["obstacles"]))
            return {"success": True}

    demo.safety = Safety()
    demo.robot = Right()
    demo.left_robot = Left()
    demo.planner = Planner()

    demo._validate_local_joint_path(
        name="test",
        joints=[[1.0] * 7],
        target_base=np.zeros(3),
    )

    assert calls[0] == "sdk"
    assert calls[1] == (
        "moveit",
        [[0.05, 0.0, 0.05], [0.0, 0.0, -0.06]],
    )
