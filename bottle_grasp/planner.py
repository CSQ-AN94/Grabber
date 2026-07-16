"""Subprocess bridge from the vision environment to ROS2 MoveIt."""

from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Sequence

import numpy as np

from .core import SafetyAbort

LOG = logging.getLogger("bottle_demo")


class MoveItPlanner:
    def __init__(self, project_root: Path, run_dir: Path):
        self.project_root = Path(project_root)
        self.run_dir = Path(run_dir)
        self.process = None
        self.log_handle = None
        self.last_obstacle_count = 0
        self.last_box_ids: set[str] = set()

    @property
    def ros_prefix(self) -> str:
        return (
            "source /opt/ros/humble/setup.bash && "
            "source /home/rm/ros2_ws/install/setup.bash && "
        )

    def start(self):
        launch_script = self.project_root / "bottle_grasp" / "moveit_headless.py"
        self.log_handle = open(self.run_dir / "moveit.log", "w", encoding="utf-8")
        self.process = subprocess.Popen(
            [
                "bash",
                "-lc",
                self.ros_prefix + f"exec python3 '{launch_script}'",
            ],
            stdout=self.log_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        deadline = time.time() + 25
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise SafetyAbort("MoveIt2 启动失败，查看 moveit.log")
            result = subprocess.run(
                [
                    "bash",
                    "-lc",
                    self.ros_prefix
                    + "ros2 service list | grep -q '^/plan_kinematic_path$'",
                ],
                check=False,
            )
            if result.returncode == 0:
                LOG.info("MoveIt2 只规划服务已就绪")
                return
            time.sleep(1)
        raise SafetyAbort("等待 MoveIt2 规划服务超时")

    def plan(
        self,
        *,
        name: str,
        start_joints_deg: Sequence[float],
        start_left_joints_deg: Sequence[float] | None,
        goal_joints_deg: Sequence[float],
        target_flange: np.ndarray,
        obstacles: Sequence[Sequence[float]],
        boxes: Sequence[dict],
        workspace: dict,
        planning_frame: str,
        tool_guard: dict,
        voxel_size: float,
    ) -> dict:
        request_path = self.run_dir / f"{name}_request.json"
        output_path = self.run_dir / f"{name}_plan.json"
        current_box_ids = {str(item["id"]) for item in boxes}
        clear_ids = [
            f"rgbd_{index}"
            for index in range(len(obstacles), self.last_obstacle_count)
        ]
        clear_ids.extend(sorted(self.last_box_ids - current_box_ids))
        request_path.write_text(
            json.dumps(
                {
                    "start_joints_deg": list(map(float, start_joints_deg)),
                    "start_left_joints_deg": (
                        None
                        if start_left_joints_deg is None
                        else list(map(float, start_left_joints_deg))
                    ),
                    "goal_joints_deg": list(map(float, goal_joints_deg)),
                    "target_flange": np.asarray(target_flange, dtype=float).tolist(),
                    "obstacles": [list(map(float, item)) for item in obstacles],
                    "boxes": list(boxes),
                    "workspace": workspace,
                    "planning_frame": planning_frame,
                    "tool_guard": tool_guard,
                    "clear_ids": clear_ids,
                    "voxel_size": float(voxel_size),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        self.last_obstacle_count = len(obstacles)
        self.last_box_ids = current_box_ids
        helper = self.project_root / "bottle_grasp" / "moveit_plan_once.py"
        result = subprocess.run(
            [
                "bash",
                "-lc",
                self.ros_prefix
                + f"python3 '{helper}' '{request_path}' '{output_path}'",
            ],
            capture_output=True,
            text=True,
            timeout=40,
        )
        if not output_path.exists():
            LOG.error("MoveIt helper stdout=%s stderr=%s", result.stdout, result.stderr)
            raise SafetyAbort("MoveIt2 没有返回规划结果")
        plan = json.loads(output_path.read_text(encoding="utf-8"))
        if not plan.get("success"):
            raise SafetyAbort(f"MoveIt2 规划失败: error={plan.get('error_code')}")
        LOG.info(
            "MoveIt2 规划 %s 成功: %d 点, %.3fs",
            name,
            len(plan["points_deg"]),
            plan["planning_time"],
        )
        return plan

    def validate_exact_path(
        self,
        *,
        name: str,
        start_left_joints_deg: Sequence[float],
        points_deg: Sequence[Sequence[float]],
        obstacles: Sequence[Sequence[float]],
        boxes: Sequence[dict],
        planning_frame: str,
        tool_guard: dict,
        voxel_size: float,
    ) -> dict:
        request_path = self.run_dir / f"{name}_validation_request.json"
        output_path = self.run_dir / f"{name}_validation.json"
        request_path.write_text(
            json.dumps(
                {
                    "start_left_joints_deg": list(
                        map(float, start_left_joints_deg)
                    ),
                    "points_deg": [
                        list(map(float, item)) for item in points_deg
                    ],
                    "obstacles": [
                        list(map(float, item)) for item in obstacles
                    ],
                    "boxes": list(boxes),
                    "planning_frame": planning_frame,
                    "tool_guard": tool_guard,
                    "voxel_size": float(voxel_size),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        helper = self.project_root / "bottle_grasp" / "moveit_validate_path.py"
        result = subprocess.run(
            [
                "bash",
                "-lc",
                self.ros_prefix
                + f"python3 '{helper}' '{request_path}' '{output_path}'",
            ],
            capture_output=True,
            text=True,
            timeout=90,
        )
        if not output_path.exists():
            LOG.error(
                "MoveIt path validator stdout=%s stderr=%s",
                result.stdout,
                result.stderr,
            )
            raise SafetyAbort("MoveIt2 没有返回示教路径检查结果")
        validation = json.loads(output_path.read_text(encoding="utf-8"))
        if not validation.get("success"):
            raise SafetyAbort(
                "示教路径碰撞检查失败: "
                f"{validation.get('invalid', [])[:1]}"
            )
        LOG.info(
            "示教路径 MoveIt 检查通过: %d 个状态",
            validation["checked_states"],
        )
        return validation

    def close(self):
        if self.process and self.process.poll() is None:
            os.killpg(self.process.pid, signal.SIGTERM)
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(self.process.pid, signal.SIGKILL)
        if self.log_handle:
            self.log_handle.close()
