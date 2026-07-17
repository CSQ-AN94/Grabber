"""MoveIt subprocess adapter error normalization; no ROS required."""

import subprocess

import numpy as np
import pytest

from bottle_grasp.core import SafetyAbort
from bottle_grasp.planner import MoveItPlanner


def _planner(tmp_path):
    return MoveItPlanner(tmp_path, tmp_path)


def _plan(planner):
    return planner.plan(
        name="probe",
        start_joints_deg=[0.0] * 7,
        start_left_joints_deg=[0.0] * 7,
        goal_joints_deg=[1.0] * 7,
        target_flange=np.eye(4),
        obstacles=[],
        boxes=[],
        workspace={"min": [-1, -1, -1], "max": [1, 1, 1]},
        planning_frame="platform_base_link",
        tool_guard={"xy": 0.1, "length": 0.2, "center_z": 0.1},
        voxel_size=0.05,
    )


def test_moveit_helper_timeout_becomes_safety_abort(tmp_path, monkeypatch):
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", timeout)

    with pytest.raises(SafetyAbort, match="规划 probe 超时"):
        _plan(_planner(tmp_path))


def test_moveit_malformed_output_becomes_safety_abort(tmp_path, monkeypatch):
    output_path = tmp_path / "probe_plan.json"

    def malformed(*args, **kwargs):
        output_path.write_text("not json", encoding="utf-8")
        return subprocess.CompletedProcess(args[0], 0, "", "")

    monkeypatch.setattr(subprocess, "run", malformed)

    with pytest.raises(SafetyAbort, match="结果无法解析"):
        _plan(_planner(tmp_path))
