"""Wrist point-cloud safety gate for the straight gripper approach corridor."""

from __future__ import annotations

from typing import Any

import numpy as np

from .core import DemoParams, Localization, SafetyAbort


def check_approach_corridor(
    *,
    camera: Any,
    robot: Any,
    localization: Localization,
    target_base: np.ndarray,
    T_flange_camera: np.ndarray,
    params: DemoParams,
) -> int:
    """Return blocker count or abort if the straight TCP corridor is occupied."""
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
    x1, y1, x2, y2 = localization.box
    valid &= ~(
        (uu >= x1 - 8)
        & (uu <= x2 + 8)
        & (vv >= y1 - 8)
        & (vv <= y2 + 8)
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
