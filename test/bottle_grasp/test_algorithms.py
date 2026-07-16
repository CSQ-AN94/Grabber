import numpy as np
import pytest
from pathlib import Path

from bottle_grasp.core import (
    DemoParams,
    Detection,
    Localization,
    SafetyAbort,
    interpolate_poses,
)
from bottle_grasp.perception import depth_point_for_detection, robust_near_cluster
from bottle_grasp.safety import load_guided_joint_path, load_safety_profile
from bottle_grasp.scene import build_scene_voxels


def test_interpolate_respects_max_translation_step():
    start = [0, 0, 0, 0, 0, 0]
    end = [0.11, 0, 0, 0, 0, 0]
    poses = interpolate_poses(start, end, 0.045)
    assert len(poses) == 3
    last = np.array(start[:3], float)
    for pose in poses:
        assert np.linalg.norm(np.array(pose[:3]) - last) <= 0.045 + 1e-9
        last = np.array(pose[:3])


def test_robust_depth_prefers_supported_near_cluster():
    params = DemoParams()
    rng = np.random.default_rng(3)
    bottle = rng.normal(0.31, 0.003, 70)
    background = rng.normal(0.51, 0.005, 260)
    z, mad = robust_near_cluster(
        np.r_[bottle, background, 0, np.nan], params
    )
    assert abs(z - 0.31) < 0.01
    assert mad < 0.01


def test_depth_point_rejects_background_and_deprojects():
    params = DemoParams()
    depth = np.full((100, 100), 0.55, np.float32)
    depth[22:78, 44:57] = 0.30
    detection = Detection((35, 10, 65, 90), 0.9, "bottle")
    K = np.array([[100, 0, 50], [0, 100, 50], [0, 0, 1]], float)
    point, z, _, pixel = depth_point_for_detection(depth, detection, K, params)
    assert abs(z - 0.30) < 0.015
    assert abs(point[2] - 0.30) < 1e-6
    assert abs(pixel[0] - 50) < 5


def test_scene_builds_generic_rgbd_voxels():
    params = DemoParams(
        head_min_depth_m=0.25,
        head_max_depth_m=1.0,
        scene_target_clearance_m=0.03,
    )
    depth = np.full((100, 100), 0.50, np.float32)
    depth[20:81, 40:61] = 0.60
    K = np.array([[100, 0, 50], [0, 100, 50], [0, 0, 1]], float)
    localization = Localization(
        point_camera=[0.0, 0.0, 0.60],
        point_base=[0.0, 0.0, 0.60],
        pixel=[50.0, 50.0],
        depth_m=0.60,
        depth_mad_m=0.001,
        position_spread_m=0.002,
        box=[40, 20, 60, 80],
        confidence=0.9,
        frame_count=7,
    )
    voxels = build_scene_voxels(
        depth,
        K,
        np.eye(4),
        localization,
        params,
    )
    assert voxels


def test_observation_direction_normalization_does_not_mutate_target():
    target = np.array([-0.01, 0.65, -0.04])
    original = target.copy()
    horizontal = np.array(target[:2], dtype=float, copy=True)
    horizontal /= np.linalg.norm(horizontal)
    camera_position = target.copy()
    camera_position[:2] -= horizontal * 0.32
    assert np.array_equal(target, original)
    assert abs(np.linalg.norm(camera_position[:2] - target[:2]) - 0.32) < 1e-9


def test_electronic_fence_profile_accepts_task_and_home_zones():
    profile = load_safety_profile(
        Path(__file__).parents[2] / "bottle_grasp" / "safety_profiles.json",
        "table_demo",
        require_verified=False,
    )
    profile.assert_tcp_point([0.31, -0.03, -0.59], label="home")
    profile.assert_tcp_point([0.00, 0.65, -0.04], label="bottle")
    # 2026-07-15: 桌面实测后加入 table_top 禁入盒，必须一并进入 MoveIt 世界
    assert [box["id"] for box in profile.moveit_collision_boxes()] == [
        "fence_table_top"
    ]
    guided = load_guided_joint_path(profile.guided_path)
    assert guided["raw_point_count"] == 226
    assert 2 < len(guided["points_deg"]) < guided["raw_point_count"]


def test_electronic_fence_rejects_outside_allowed_zone():
    config = Path(__file__).parents[2] / "bottle_grasp" / "safety_profiles.json"
    profile = load_safety_profile(
        config, "table_demo", require_verified=False
    )
    # 桌面以下的点现在被桌子禁入盒拦截（比"不在允许区"更早、语义更准）
    with pytest.raises(SafetyAbort, match="进入禁入区 table_top"):
        profile.assert_tcp_point([0.0, 0.65, -0.24], label="table")
    # 允许区之外但不在任何禁入盒里的点，仍走"不在任何允许区"这条路径
    with pytest.raises(SafetyAbort, match="不在任何允许区"):
        profile.assert_tcp_point([0.0, 0.96, 0.30], label="beyond task volume")
    assert load_safety_profile(
        config, "table_demo", require_verified=True
    ).verified_for_execution


def test_overlapping_allowed_zones_have_no_clearance_seam():
    profile = load_safety_profile(
        Path(__file__).parents[2] / "bottle_grasp" / "safety_profiles.json",
        "table_demo",
        require_verified=False,
    )
    # Inside the authored transit zone but close to its y edge. This must not
    # be rejected merely because per-zone clearance creates a fake seam.
    profile.assert_tcp_point([0.1815, 0.3291, -0.4886], label="transit seam")
