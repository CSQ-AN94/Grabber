"""Shared local grasp/place geometry contracts; no hardware."""

import numpy as np
from scipy.spatial.transform import Rotation

from bottle_grasp.core import (
    DemoParams,
    interpolate_poses,
    matrix_pose,
    pose_matrix,
)
from bottle_grasp.demo import BottleDemo


def test_grasp_stops_short_and_post_release_retreat_is_independent():
    demo = object.__new__(BottleDemo)
    demo.params = DemoParams()
    start = np.eye(4)
    start[2, 3] = 0.20
    target = np.array([0.0, 0.0, 0.50])

    pregrasp, grasp, _transit, full_path = demo._local_pick_place_geometry(
        start, target, np.eye(3)
    )

    np.testing.assert_allclose(
        pose_matrix(grasp)[:3, 3],
        [0.0, 0.0, 0.50 - demo.params.grasp_stop_short_m],
    )
    # Pregrasp keeps its old target-relative hover distance; shortening the
    # final insertion must not move the observation/hover waypoint.
    np.testing.assert_allclose(
        pose_matrix(pregrasp)[:3, 3],
        [0.0, 0.0, 0.50 - demo.params.pregrasp_standoff_m],
    )
    # The path ends after release at a separately configured, longer retreat.
    np.testing.assert_allclose(
        np.asarray(full_path[-1][:3]),
        [
            0.0,
            0.0,
            0.50
            - demo.params.grasp_stop_short_m
            - demo.params.retreat_standoff_m,
        ],
    )


def test_shared_geometry_uses_conservative_first_site_adjustment():
    params = DemoParams()

    assert params.grasp_stop_short_m == 0.030
    assert params.pregrasp_standoff_m == 0.085
    assert params.retreat_standoff_m == 0.150
    assert params.transit_speed == 75
    assert params.travel_speed == 15
    assert params.final_speed == 15


def test_large_optional_roll_is_split_into_small_rotation_steps():
    start = pose_matrix(
        [0.09857, 0.57603, -0.13667, 0.369, 1.522, 2.48]
    )
    rolled = start.copy()
    rolled[:3, :3] = (
        start[:3, :3]
        @ Rotation.from_euler("z", 89.0, degrees=True).as_matrix()
    )

    poses = interpolate_poses(matrix_pose(start), matrix_pose(rolled), 0.045)

    # Optional small-roll IK recovery must remain safely interpolated if a
    # caller ever requests a larger orientation change.
    total_deg = np.degrees(
        Rotation.from_matrix(start[:3, :3].T @ rolled[:3, :3]).magnitude()
    )
    assert len(poses) == int(np.ceil(total_deg / 10.0))
    assert len(poses) > 1
    previous = start[:3, :3]
    for pose in poses:
        current = pose_matrix(pose)
        np.testing.assert_allclose(current[:3, 3], start[:3, 3], atol=1e-12)
        step_deg = np.degrees(
            Rotation.from_matrix(previous.T @ current[:3, :3]).magnitude()
        )
        assert step_deg <= 10.0 + 1e-9
        previous = current[:3, :3]


def test_runtime_place_back_uses_the_longer_retreat_distance():
    demo = object.__new__(BottleDemo)
    demo.params = DemoParams()
    demo.stage = lambda *_args: None

    class Safety:
        @staticmethod
        def assert_tcp_point(_point, *, label):
            assert label == "放回后退开点"

    class Robot:
        def __init__(self):
            self.moves = []

        @staticmethod
        def current_tcp():
            return np.eye(4)

        @staticmethod
        def open_gripper(_params):
            pass

        @staticmethod
        def close_empty_gripper(_params):
            pass

        def move_linear(self, pose, _speed):
            self.moves.append((np.asarray(pose[:3], dtype=float), _speed))

    demo.safety = Safety()
    demo.robot = Robot()
    demo._plan_local_leg = lambda _name, build_path, _params: build_path()

    demo._place_back()

    np.testing.assert_allclose(
        demo.robot.moves[-1][0],
        [0.0, 0.0, -demo.params.retreat_standoff_m],
    )
    assert demo.robot.moves[0][1] == demo.params.final_speed
    assert demo.robot.moves[-1][1] == demo.params.travel_speed
