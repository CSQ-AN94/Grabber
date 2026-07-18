"""Wrist point-cloud safety gate for the straight gripper approach corridor."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np

from .core import DemoParams, SafetyAbort


def classify_moveit_collision_probe(
    *, baseline_valid: bool, boxed_valid: bool, cleared_valid: bool
) -> tuple[str, str]:
    """Classify the three-state MoveIt world-collision probe accurately."""
    if not baseline_valid:
        return (
            "baseline_invalid",
            "无障碍基线姿态已经碰撞，探针姿态或残留场景无效",
        )
    if boxed_valid:
        return (
            "collision_missed",
            "巨型障碍盒中的姿态仍被判有效，世界碰撞检测未生效",
        )
    if not cleared_valid:
        return (
            "cleanup_failed",
            "撤除巨型障碍盒后没有恢复，规划场景清理或同步失败",
        )
    return "healthy", "基线、碰撞拒绝和场景恢复均符合预期"


def check_approach_corridor(
    *,
    camera: Any,
    robot: Any,
    target_box: Sequence[int] | None,
    target_base: np.ndarray,
    T_flange_camera: np.ndarray,
    params: DemoParams,
) -> int:
    """Return blocker count or abort if the straight TCP corridor is occupied.

    The target's own occupied cylinder is always removed.  A current wrist box
    narrows that removal further to ``box ∩ cylinder``; head-only confirmation
    uses the cylinder alone.  Neither case creates a broad clearance hole.
    """
    _, depth = camera.get_latest_frames()
    K, _ = camera.get_camera_intrinsics()
    if depth is None or K is None:
        raise SafetyAbort("通道检查缺少深度")

    stride = 3
    vv, uu = np.mgrid[0 : depth.shape[0] : stride, 0 : depth.shape[1] : stride]
    zz = depth[vv, uu]
    valid = (
        np.isfinite(zz)
        & (zz > params.min_depth_m)
        & (zz < params.max_depth_m)
    )
    z = zz[valid]
    u, v = uu[valid], vv[valid]
    camera_points = np.column_stack(
        (
            (u - K[0, 2]) * z / K[0, 0],
            (v - K[1, 2]) * z / K[1, 1],
            z,
            np.ones_like(z),
        )
    )
    T_base_camera = robot.current_flange() @ T_flange_camera
    points = (T_base_camera @ camera_points.T).T[:, :3]

    target = np.asarray(target_base, dtype=float)
    radial = np.linalg.norm(points[:, :2] - target[:2], axis=1)
    target_samples = (
        (radial <= params.target_occupancy_radius_m)
        & (
            points[:, 2]
            >= target[2] - params.target_occupancy_below_grasp_m
        )
        & (
            points[:, 2]
            <= target[2] + params.target_occupancy_above_grasp_m
        )
    )
    if target_box is not None:
        x1, y1, x2, y2 = target_box
        in_current_box = (
            (u >= x1 - params.target_occupancy_box_pad_px)
            & (u <= x2 + params.target_occupancy_box_pad_px)
            & (v >= y1 - params.target_occupancy_box_pad_px)
            & (v <= y2 + params.target_occupancy_box_pad_px)
        )
        target_samples &= in_current_box
    points = points[~target_samples]

    start = robot.current_tcp()[:3, 3]
    vector = target_base - start
    length_squared = float(vector @ vector)
    if length_squared < 1e-6:
        return 0
    along = np.clip(((points - start) @ vector) / length_squared, 0, 1)
    distance = np.linalg.norm(
        points - (start + along[:, None] * vector), axis=1
    )
    blockers = (
        (along > 0.08)
        & (along < 0.86)
        & (distance < params.corridor_radius_m)
    )
    count = int(np.count_nonzero(blockers))
    if count >= params.obstacle_min_points:
        raise SafetyAbort(f"夹爪前进通道被点云阻挡: {count} 点")
    return count
