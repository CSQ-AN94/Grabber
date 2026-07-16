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
    points, u, v = _base_points(
        depth,
        K,
        T_base_camera,
        params,
        min_depth_m=min_depth_m,
        max_depth_m=max_depth_m,
        bottom_crop=bottom_crop,
    )
    x1, y1, x2, y2 = localization.box
    keep = ~(
        (u >= x1 - 12)
        & (u <= x2 + 12)
        & (v >= y1 - 12)
        & (v <= y2 + 12)
    )
    points = points[keep]
    target = np.asarray(localization.point_base, dtype=float)

    # Keep the local arm work volume, not the entire room.
    relative = points - target
    valid_workspace = (
        (np.linalg.norm(relative[:, :2], axis=1) < 0.95)
        & (np.abs(relative[:, 2]) < 0.75)
        & (np.linalg.norm(relative, axis=1) > params.scene_target_clearance_m)
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
        distance = np.linalg.norm(centers - target, axis=1)
        centers = centers[np.argsort(distance)[:max_voxels]]
    return centers.tolist()
