"""RGB-D conversion into environment-independent MoveIt collision voxels."""

from __future__ import annotations

from typing import Sequence

import numpy as np

from .core import DemoParams, Localization, SafetyAbort


def _base_points(
    depth: np.ndarray,
    K: np.ndarray,
    T_base_camera: np.ndarray,
    params: DemoParams,
    stride: int = 6,
    min_depth_m: float | None = None,
    max_depth_m: float | None = None,
    bottom_crop: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    if bottom_crop is None:
        bottom_crop = params.scene_image_bottom_crop
    max_v = min(depth.shape[0], bottom_crop)
    vv, uu = np.mgrid[0:max_v:stride, 0 : depth.shape[1] : stride]
    zz = depth[vv, uu]
    min_depth_m = (
        params.head_min_depth_m if min_depth_m is None else min_depth_m
    )
    max_depth_m = (
        params.head_max_depth_m if max_depth_m is None else max_depth_m
    )
    valid = (
        np.isfinite(zz)
        & (zz >= min_depth_m)
        & (zz <= max_depth_m)
    )
    z = zz[valid]
    if z.size < 20:
        raise SafetyAbort("头部点云有效点不足")
    u, v = uu[valid], vv[valid]
    camera_points = np.column_stack(
        (
            (u - K[0, 2]) * z / K[0, 0],
            (v - K[1, 2]) * z / K[1, 1],
            z,
            np.ones_like(z),
        )
    )
    return (T_base_camera @ camera_points.T).T[:, :3], u, v


def head_scene_points(
    depth: np.ndarray,
    K: np.ndarray,
    T_base_camera: np.ndarray,
    params: DemoParams,
    *,
    min_depth_m: float | None = None,
    max_depth_m: float | None = None,
    bottom_crop: int | None = None,
) -> np.ndarray:
    """Return the raw head point cloud in the right-arm base frame."""
    if depth is None or K is None:
        raise SafetyAbort("头部点云缺少深度或内参")
    points, _, _ = _base_points(
        depth,
        K,
        T_base_camera,
        params,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        bottom_crop=bottom_crop,
    )
    return points


def build_scene_voxels(
    depth: np.ndarray,
    K: np.ndarray,
    T_base_camera: np.ndarray,
    localization: Localization,
    params: DemoParams,
    *,
    min_depth_m: float | None = None,
    max_depth_m: float | None = None,
    bottom_crop: int | None = None,
    max_voxels: int | None = None,
) -> list[list[float]]:
    """Return occupied voxel centers in the right-arm base frame.

    The lower image strip is excluded because the robot's own arms and body
    occupy it in the fixed head-camera view. MoveIt handles robot self-collision
    from the URDF/SRDF; feeding those pixels back as world obstacles would make
    the start state falsely collide with itself.
    """
    if depth is None or K is None:
        raise SafetyAbort("头部点云缺少深度或内参")
    points, _, _ = _base_points(
        depth,
        K,
        T_base_camera,
        params,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        bottom_crop=bottom_crop,
    )
    target = np.asarray(localization.point_base, dtype=float)

    # Keep the local arm work volume, not the entire room.  Do not delete the
    # detector box or a target-centred sphere here.  The global leg stops at a
    # wrist observation pose and has no reason to contact the bottle; the old
    # 14 cm target hole could silently erase a real obstacle beside it.  Local
    # grasp contact is handled later by the wrist corridor and grasp recipe.
    relative = points - target
    valid_workspace = (
        (np.linalg.norm(relative[:, :2], axis=1) < 0.95)
        & (np.abs(relative[:, 2]) < 0.75)
    )
    points = points[valid_workspace]
    if points.size == 0:
        return []

    voxel = params.scene_voxel_m
    keys = np.floor(points / voxel).astype(np.int32)
    unique = np.unique(keys, axis=0)
    centers = (unique.astype(float) + 0.5) * voxel
    max_voxels = params.scene_max_voxels if max_voxels is None else max_voxels
    if len(centers) > max_voxels:
        # Never manufacture free space to meet a performance budget.  The
        # previous "nearest to bottle" truncation could drop an obstacle near
        # the path start while retaining hundreds of table voxels.  The scene
        # must either be represented in full or the robot must not move.
        raise SafetyAbort(
            "头部障碍体素超出安全场景预算，拒绝丢弃远处障碍: "
            f"{len(centers)} > {max_voxels}。清理视野或调大体素尺寸后重跑"
        )
    return centers.tolist()
