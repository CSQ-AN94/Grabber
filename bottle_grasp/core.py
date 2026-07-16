"""Shared data types and geometry helpers for the bottle grasp demo."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np
from scipy.spatial.transform import Rotation


class SafetyAbort(RuntimeError):
    """A fail-closed condition; no automatic retreat is allowed."""


@dataclass
class DemoParams:
    samples: int = 7
    confidence: float = 0.45
    min_depth_m: float = 0.12
    max_depth_m: float = 0.65
    max_depth_mad_m: float = 0.018
    max_position_spread_m: float = 0.025
    max_relocalization_jump_m: float = 0.035
    # 续抓模式首次定位对保存先验的容差：桌子/瓶子可能被人为挪动过，
    # 放宽到12cm；接近过程中的分段跳变检查仍用 max_relocalization_jump_m。
    resume_prior_jump_m: float = 0.20
    tcp_z_m: float = 0.151
    moveit_link7_to_controller_flange_m: float = 0.0172
    tool_guard_xy_m: float = 0.10
    tool_guard_length_m: float = 0.19
    tool_guard_center_z_m: float = 0.095
    pregrasp_standoff_m: float = 0.085
    segment_m: float = 0.045
    lift_m: float = 0.05
    travel_speed: int = 3
    final_speed: int = 3
    j4_singularity_deg: float = 8.0
    joint_limit_margin_deg: float = 3.0
    corridor_radius_m: float = 0.045
    obstacle_min_points: int = 18
    frame_timeout_s: float = 1.0
    observation_standoff_m: float = 0.32
    head_min_depth_m: float = 0.25
    head_max_depth_m: float = 2.2
    scene_voxel_m: float = 0.065
    scene_max_voxels: int = 550
    scene_target_clearance_m: float = 0.14
    scene_image_bottom_crop: int = 405
    planned_joint_step_deg: float = 1.5
    head_width: int = 848
    head_height: int = 480
    wrist_scene_max_voxels: int = 240
    merged_scene_max_voxels: int = 650
    wrist_relocalization_samples: int = 3
    pregrasp_replan_cycles: int = 12
    replan_dense_points: int = 6
    # RM Plus two-finger gripper.  The legacy rm_set_gripper_* API does not
    # control the installed ZX gripper.  Real-robot empty-close calibration on
    # 2026-07-16 stopped at pos~=394, so a bottle grasp must stop wider than
    # that baseline before lifting.
    gripper_open_position: int = 900
    gripper_close_position: int = 0
    gripper_speed: int = 100
    gripper_force: int = 30
    gripper_empty_closed_position: int = 394
    gripper_object_margin: int = 35


@dataclass
class Detection:
    box: tuple[int, int, int, int]
    confidence: float
    class_name: str


@dataclass
class Localization:
    point_camera: list[float]
    point_base: list[float]
    pixel: list[float]
    depth_m: float
    depth_mad_m: float
    position_spread_m: float
    box: list[int]
    confidence: float
    frame_count: int


def pose_matrix(pose: Sequence[float]) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = Rotation.from_euler("xyz", pose[3:6]).as_matrix()
    T[:3, 3] = pose[:3]
    return T


def matrix_pose(T: np.ndarray) -> list[float]:
    return [
        *map(float, T[:3, 3]),
        *map(float, Rotation.from_matrix(T[:3, :3]).as_euler("xyz")),
    ]


def interpolate_poses(
    start: Sequence[float], end: Sequence[float], max_step: float
) -> list[list[float]]:
    """Interpolate a Cartesian path with a hard translation step bound."""
    a, b = pose_matrix(start), pose_matrix(end)
    distance = float(np.linalg.norm(b[:3, 3] - a[:3, 3]))
    count = max(1, int(math.ceil(distance / max_step)))
    rv0 = Rotation.from_matrix(a[:3, :3]).as_rotvec()
    rv1 = Rotation.from_matrix(b[:3, :3]).as_rotvec()
    result = []
    for i in range(1, count + 1):
        alpha = i / count
        T = np.eye(4)
        T[:3, 3] = (1 - alpha) * a[:3, 3] + alpha * b[:3, 3]
        T[:3, :3] = Rotation.from_rotvec(
            (1 - alpha) * rv0 + alpha * rv1
        ).as_matrix()
        result.append(matrix_pose(T))
    return result


def look_at_camera_pose(
    target: Sequence[float],
    camera_position: Sequence[float],
) -> np.ndarray:
    """Construct an optical camera pose whose +Z axis looks at the target.

    RealSense optical coordinates use +X right, +Y down, +Z forward. The
    projected base -Z direction is used as camera down to keep the image level.
    """
    target = np.asarray(target, dtype=float)
    position = np.asarray(camera_position, dtype=float)
    z_axis = target - position
    z_axis /= np.linalg.norm(z_axis)
    down = np.array([0.0, 0.0, -1.0])
    down -= z_axis * float(down @ z_axis)
    if np.linalg.norm(down) < 1e-5:
        down = np.array([0.0, 1.0, 0.0])
        down -= z_axis * float(down @ z_axis)
    y_axis = down / np.linalg.norm(down)
    x_axis = np.cross(y_axis, z_axis)
    x_axis /= np.linalg.norm(x_axis)
    y_axis = np.cross(z_axis, x_axis)
    T = np.eye(4)
    T[:3, :3] = np.column_stack((x_axis, y_axis, z_axis))
    T[:3, 3] = position
    return T
