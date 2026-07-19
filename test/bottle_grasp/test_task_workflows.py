from __future__ import annotations

import logging
import threading
from types import SimpleNamespace

import numpy as np
import pytest

from bottle_grasp.core import DemoParams, Localization, SafetyAbort
from bottle_grasp.demo import BottleDemo
import bottle_grasp.demo as demo_module
from bottle_grasp.task import (
    BottlePickPlaceTask,
    ObjectState,
    RunStatus,
    StartMode,
    TaskPhase,
)


def _localization(point):
    return Localization(
        point_camera=list(point),
        point_base=list(point),
        pixel=[320.0, 240.0],
        depth_m=0.36,
        depth_mad_m=0.001,
        position_spread_m=0.002,
        box=[280, 100, 360, 479],
        confidence=0.9,
        frame_count=7,
    )


class FakeDemo:
    def __init__(self, tmp_path, mode):
        self.args = SimpleNamespace(task_mode=mode.value)
        self.params = DemoParams()
        self.safety = SimpleNamespace(
            observation_staging_joints_deg=None,
        )
        self.stop_event = threading.Event()
        self.run_dir = tmp_path
        self.calls = []
        self.head = _localization([0.12, 0.52, -0.12])
        self.wrist = _localization([0.13, 0.51, -0.12])
        self.left_robot = SimpleNamespace(joints_deg=lambda: [0.0] * 7)

    def stage(self, name, message=""):
        self.calls.append(("stage", name))

    def initialize(self):
        self.calls.append(("initialize",))

    def _preflight(self):
        self.calls.append(("preflight",))

    def _fresh_head_target(self):
        self.calls.append(("fresh_head",))
        return self.head

    def _build_head_scene(self, target):
        assert target is self.head
        self.calls.append(("scene",))

    def _plan_observation(self, target):
        np.testing.assert_allclose(target, self.head.point_base)
        self.calls.append(("plan_observation",))
        return {"points_deg": [[1.0] * 7]}

    def _plan_observation_staging(self):
        self.calls.append(("plan_observation_staging",))
        return {"points_deg": [[2.0] * 7]}

    def _refresh_and_revalidate_plan(self, *, name, plan, locked_target):
        assert plan["points_deg"]
        assert locked_target is self.head
        if name == "moveit_observation_staging":
            self.calls.append(("refresh_validate_staging",))
        else:
            assert name == "moveit_observation"
            self.calls.append(("refresh_validate_observation",))

    def _execute_plan(self, name, plan):
        if name == "抬高展开到观察准备位":
            self.calls.append(("execute_staging", name))
        else:
            self.calls.append(("execute_observation", name))

    def _fresh_wrist_target(self, head_target):
        assert head_target is self.head
        self.calls.append(("fresh_wrist",))
        return self.wrist

    def _verify_wrist_observation_start(self, wrist_target):
        assert wrist_target is self.wrist
        self.calls.append(("verify_wrist_start",))

    def _grasp_and_lift(self, wrist_target):
        assert wrist_target is self.wrist
        self.calls.append(("grasp_lift",))

    def _place_back(self, wrist_target):
        assert wrist_target is self.wrist
        self.calls.append(("place_release_retreat",))

    def _refresh_head_scene_for_global_motion(self, wrist_target):
        assert wrist_target is self.wrist
        self.calls.append(("refresh_return_scene",))

    def _return_home(self):
        self.calls.append(("return_home",))


def _hardware_calls(demo):
    return [call[0] for call in demo.calls if call[0] != "stage"]


def test_from_observation_is_fresh_and_uses_one_complete_shared_tail(tmp_path):
    demo = FakeDemo(tmp_path, StartMode.FROM_OBSERVATION)

    result = BottlePickPlaceTask(demo).run(StartMode.FROM_OBSERVATION)

    assert _hardware_calls(demo) == [
        "initialize",
        "preflight",
        "fresh_head",
        "scene",
        "fresh_wrist",
        "verify_wrist_start",
        "grasp_lift",
        "place_release_retreat",
    ]
    assert result.status == RunStatus.DONE.value
    assert result.phase == TaskPhase.DONE.value
    assert result.object_state == ObjectState.EMPTY.value
    assert (tmp_path / "task_result.json").is_file()


def test_from_start_adds_only_transfer_prefix_and_home_suffix(tmp_path):
    demo = FakeDemo(tmp_path, StartMode.FROM_START)

    result = BottlePickPlaceTask(demo).run(StartMode.FROM_START)

    assert _hardware_calls(demo) == [
        "initialize",
        "preflight",
        "fresh_head",
        "scene",
        "plan_observation",
        "refresh_validate_observation",
        "execute_observation",
        "fresh_wrist",
        "verify_wrist_start",
        "grasp_lift",
        "place_release_retreat",
        "refresh_return_scene",
        "return_home",
    ]
    assert result.status == RunStatus.DONE.value
    assert result.object_state == ObjectState.EMPTY.value


def test_from_natural_hang_uses_staging_then_reacquires_scene(tmp_path):
    demo = FakeDemo(tmp_path, StartMode.FROM_START)
    demo.safety.observation_staging_joints_deg = tuple([10.0] * 7)

    result = BottlePickPlaceTask(demo).run(StartMode.FROM_START)

    assert _hardware_calls(demo) == [
        "initialize",
        "preflight",
        "fresh_head",
        "scene",
        "plan_observation_staging",
        "refresh_validate_staging",
        "execute_staging",
        # The arm occupied a different part of the camera scene after the
        # departure motion, so observation planning must use a fresh lock.
        "fresh_head",
        "scene",
        "plan_observation",
        "refresh_validate_observation",
        "execute_observation",
        "fresh_wrist",
        "verify_wrist_start",
        "grasp_lift",
        "place_release_retreat",
        "refresh_return_scene",
        "return_home",
    ]
    assert result.status == RunStatus.DONE.value


def test_from_start_can_stop_after_real_observation_without_grasp(tmp_path):
    demo = FakeDemo(tmp_path, StartMode.FROM_START)
    demo.args.stop_after_observation = True

    result = BottlePickPlaceTask(demo).run(StartMode.FROM_START)

    assert _hardware_calls(demo) == [
        "initialize",
        "preflight",
        "fresh_head",
        "scene",
        "plan_observation",
        "refresh_validate_observation",
        "execute_observation",
        "fresh_wrist",
        "verify_wrist_start",
    ]
    assert result.status == RunStatus.DONE.value
    assert result.object_state == ObjectState.EMPTY.value


def test_failure_during_grasp_is_recorded_as_unknown_not_success(tmp_path):
    demo = FakeDemo(tmp_path, StartMode.FROM_OBSERVATION)

    def fail(_target):
        raise SafetyAbort("captured hardware failure")

    demo._grasp_and_lift = fail
    task = BottlePickPlaceTask(demo)

    with pytest.raises(SafetyAbort, match="captured hardware failure"):
        task.run(StartMode.FROM_OBSERVATION)

    assert task.status is RunStatus.SAFE_ABORT
    assert task.phase is TaskPhase.ABORTED
    assert task.object_state is ObjectState.UNKNOWN
    assert '"status": "safe_abort"' in (
        tmp_path / "task_result.json"
    ).read_text(encoding="utf-8")


def test_failed_independent_lift_confirmation_cannot_place_or_reach_done(tmp_path):
    demo = FakeDemo(tmp_path, StartMode.FROM_OBSERVATION)

    def reject_false_grasp(_target):
        raise SafetyAbort("抬升三维确认失败：瓶子仍在原桌面点")

    demo._grasp_and_lift = reject_false_grasp
    task = BottlePickPlaceTask(demo)

    with pytest.raises(SafetyAbort, match="抬升三维确认失败"):
        task.run(StartMode.FROM_OBSERVATION)

    assert task.status is RunStatus.SAFE_ABORT
    assert task.object_state is ObjectState.UNKNOWN
    assert "place_release_retreat" not in _hardware_calls(demo)
    assert task.phase is TaskPhase.ABORTED


def test_task_rejects_parser_and_runtime_mode_disagreement(tmp_path):
    demo = FakeDemo(tmp_path, StartMode.FROM_START)

    with pytest.raises(SafetyAbort, match="任务模式在解析后发生变化"):
        BottlePickPlaceTask(demo).run(StartMode.FROM_OBSERVATION)

    assert demo.calls == []


def test_two_runs_started_at_the_same_timestamp_get_distinct_evidence_dirs(
    monkeypatch, tmp_path
):
    class FrozenDateTime:
        @staticmethod
        def now():
            return SimpleNamespace(
                strftime=lambda _format: "20260718_203207"
            )

    monkeypatch.setattr(demo_module, "datetime", FrozenDateTime)
    args = SimpleNamespace(
        config=str(tmp_path / "config.yaml"),
        output_dir=str(tmp_path / "outputs"),
    )
    first = BottleDemo(args, None)
    second = BottleDemo(args, None)
    try:
        assert first.run_dir != second.run_dir
    finally:
        for demo in (first, second):
            logging.getLogger().removeHandler(demo.run_log_handler)
            demo.run_log_handler.close()
