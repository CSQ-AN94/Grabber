"""Verified global motion planning with bounded, feedback-driven replanning."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import numpy as np

from .core import DemoParams, SafetyAbort, interpolate_joint_path
from .safety import FenceViolation, SafetyProfile


@dataclass(frozen=True)
class PlanTarget:
    """One reachable controller-flange goal offered to the safe planner."""

    label: str
    flange: np.ndarray
    goal_joints: tuple[float, ...]
    score: float = 0.0


@dataclass(frozen=True)
class VerifiedPlan:
    """A trajectory accepted by MoveIt and the independent electronic fence."""

    trajectory: dict
    target: PlanTarget
    checked_tcp_points: int
    attempts: int
    rejections: tuple[str, ...]


class SafeMotionPlanner:
    """Find and independently verify a global arm trajectory.

    The interface deliberately exposes one operation. MoveIt sampling,
    candidate fallback, fence feedback, duplicate suppression and failure
    aggregation remain implementation details behind this seam.
    """

    def __init__(
        self,
        *,
        moveit,
        robot,
        left_robot,
        safety: SafetyProfile,
        params: DemoParams,
        report: Optional[Callable[[str, str], None]] = None,
    ):
        self.moveit = moveit
        self.robot = robot
        self.left_robot = left_robot
        self.safety = safety
        self.params = params
        self.report = report or (lambda _name, _message: None)

    @staticmethod
    def _trajectory_fingerprint(points: Sequence[Sequence[float]]) -> tuple:
        return tuple(
            tuple(round(float(value), 3) for value in point)
            for point in points
        )

    def _target_link7_in_moveit(self, target: PlanTarget) -> np.ndarray:
        T_link7_controller_flange = np.eye(4)
        T_link7_controller_flange[2, 3] = (
            self.params.moveit_link7_to_controller_flange_m
        )
        target_link7 = target.flange @ np.linalg.inv(
            T_link7_controller_flange
        )
        return self.safety.pose_to_moveit(target_link7)

    def plan(
        self,
        *,
        name: str,
        targets: Sequence[PlanTarget],
        obstacle_points: Sequence[Sequence[float]],
        collision_boxes: Sequence[dict],
    ) -> VerifiedPlan:
        ranked = sorted(targets, key=lambda target: target.score)
        ranked = ranked[: self.params.global_plan_max_candidates]
        if not ranked:
            raise SafetyAbort(f"{name} 没有可规划的目标候选")

        start_right = self.robot.joints_deg()
        start_left = self.left_robot.joints_deg()
        moveit_obstacles = self.safety.points_to_moveit(obstacle_points)
        base_boxes = list(collision_boxes)
        seen_trajectories: set[tuple] = set()
        rejections: list[str] = []
        attempts = 0

        for candidate_index, target in enumerate(ranked, 1):
            feedback_boxes: list[dict] = []
            target_moveit = self._target_link7_in_moveit(target)
            for route_index in range(
                1, self.params.global_plan_attempts_per_candidate + 1
            ):
                attempts += 1
                attempt_label = (
                    f"{name}_c{candidate_index:02d}_r{route_index:02d}"
                )
                self.report(
                    "安全规划尝试",
                    f"{name}: {target.label}，路线 {route_index}",
                )
                try:
                    trajectory = self.moveit.plan(
                        name=attempt_label,
                        start_joints_deg=start_right,
                        start_left_joints_deg=start_left,
                        goal_joints_deg=target.goal_joints,
                        target_flange=target_moveit,
                        obstacles=moveit_obstacles,
                        boxes=[*base_boxes, *feedback_boxes],
                        workspace=self.safety.moveit_workspace(),
                        planning_frame=self.safety.moveit_frame,
                        tool_guard={
                            "xy": self.params.tool_guard_xy_m,
                            "length": self.params.tool_guard_length_m,
                            "center_z": self.params.tool_guard_center_z_m,
                        },
                        voxel_size=self.params.scene_voxel_m,
                    )
                except SafetyAbort as exc:
                    reason = f"{target.label}/路线{route_index} 规划失败: {exc}"
                    rejections.append(reason)
                    self.report("规划未通过，自动换路", reason)
                    continue

                fingerprint = self._trajectory_fingerprint(
                    trajectory.get("points_deg", [])
                )
                if fingerprint in seen_trajectories:
                    reason = f"{target.label}/路线{route_index} 与已拒绝轨迹重复"
                    rejections.append(reason)
                    self.report("规划未通过，自动换目标", reason)
                    break
                seen_trajectories.add(fingerprint)

                try:
                    checked = self.robot.validate_planned_joints(
                        trajectory["points_deg"],
                        self.params.planned_joint_step_deg,
                        self.safety,
                        start_joints_deg=start_right,
                    )
                except SafetyAbort as exc:
                    reason = f"{target.label}/路线{route_index} 围栏拒绝: {exc}"
                    rejections.append(reason)
                    if isinstance(exc, FenceViolation):
                        feedback_boxes.append(
                            self.safety.replan_exclusion_box(
                                exc,
                                object_id=f"replan_{attempts:02d}",
                                size_m=self.params.replan_exclusion_size_m,
                            )
                        )
                    self.report("轨迹越界，自动重规划", reason)
                    continue

                dense_joint_points = interpolate_joint_path(
                    start_right,
                    trajectory["points_deg"],
                    self.params.planned_joint_step_deg,
                )
                try:
                    self.moveit.validate_exact_path(
                        name=f"{attempt_label}_postcheck",
                        start_left_joints_deg=start_left,
                        points_deg=dense_joint_points,
                        obstacles=moveit_obstacles,
                        boxes=[*base_boxes, *feedback_boxes],
                        planning_frame=self.safety.moveit_frame,
                        tool_guard={
                            "xy": self.params.tool_guard_xy_m,
                            "length": self.params.tool_guard_length_m,
                            "center_z": self.params.tool_guard_center_z_m,
                        },
                        voxel_size=self.params.scene_voxel_m,
                    )
                except SafetyAbort as exc:
                    reason = (
                        f"{target.label}/路线{route_index} "
                        f"MoveIt 后验碰撞拒绝: {exc}"
                    )
                    rejections.append(reason)
                    self.report("轨迹碰撞，自动重规划", reason)
                    continue

                self.report(
                    "安全轨迹确定",
                    (
                        f"{name}: {target.label}；第 {attempts} 次尝试；"
                        f"{checked} 个密集 TCP 点通过"
                    ),
                )
                return VerifiedPlan(
                    trajectory=trajectory,
                    target=target,
                    checked_tcp_points=checked,
                    attempts=attempts,
                    rejections=tuple(rejections),
                )

        tail = "；".join(rejections[-4:]) if rejections else "无详细拒绝原因"
        raise SafetyAbort(
            f"{name} 在 {attempts} 次安全规划后仍无可执行轨迹；"
            f"候选={len(ranked)}；最后拒绝: {tail}"
        )
