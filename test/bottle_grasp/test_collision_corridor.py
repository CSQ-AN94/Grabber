from __future__ import annotations

import numpy as np
import pytest

from bottle_grasp.collision import check_approach_corridor
from bottle_grasp.core import DemoParams, SafetyAbort


def _corridor_fixture(depth_m: float, *, patch=(30, 60, 30, 60)):
    depth = np.full((90, 90), np.nan, dtype=float)
    y1, y2, x1, x2 = patch
    depth[y1:y2, x1:x2] = depth_m
    intrinsics = np.array(
        [[250.0, 0.0, 45.0], [0.0, 250.0, 45.0], [0.0, 0.0, 1.0]],
        dtype=float,
    )
    T_base_camera = np.eye(4)
    T_base_camera[2, 3] = -0.3

    class Camera:
        @staticmethod
        def get_latest_frames():
            return None, depth

        @staticmethod
        def get_camera_intrinsics():
            return intrinsics, None

    class Robot:
        @staticmethod
        def current_flange():
            return T_base_camera

        @staticmethod
        def current_tcp():
            return np.eye(4)

    return Camera(), Robot()


def _check(depth_m: float, target_box, *, patch=(30, 60, 30, 60)):
    camera, robot = _corridor_fixture(depth_m, patch=patch)
    return check_approach_corridor(
        camera=camera,
        robot=robot,
        target_box=target_box,
        target_base=np.array([0.0, 0.0, 0.085]),
        T_flange_camera=np.eye(4),
        params=DemoParams(),
    )


def test_target_box_does_not_erase_a_foreground_obstacle_at_another_depth():
    # Base z=0.01 m: this patch lies in the TCP-to-target corridor but 75 mm
    # nearer than the locked target depth.  A 2-D whole-box mask hid it.
    with pytest.raises(SafetyAbort, match="夹爪前进通道被点云阻挡"):
        _check(0.31, (15, 15, 75, 75))


def test_target_box_removes_only_the_locked_bottle_depth_region():
    # Base z=0.055 m: 30 mm in front of the locked cylinder centre and inside
    # its current associated silhouette, representing the visible bottle skin.
    assert _check(0.355, (15, 15, 75, 75)) == 0


def test_head_only_confirmation_does_not_reuse_or_invent_a_wrist_mask():
    # No box is available, but the explicit physical bottle cylinder is still
    # known and must let the target's own surface pass.
    assert _check(0.355, None) == 0


def test_head_only_target_cylinder_keeps_adjacent_obstacle_points():
    # Shift the patch just outside the physical bottle radius but keep enough
    # samples inside the 45 mm approach corridor.  A broad clearance hole would
    # erase this neighbour; a bounded occupancy cylinder must not.
    with pytest.raises(SafetyAbort, match="夹爪前进通道被点云阻挡"):
        _check(0.355, None, patch=(0, 90, 72, 78))
