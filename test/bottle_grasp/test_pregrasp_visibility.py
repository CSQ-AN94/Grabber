"""Regression tests for transient YOLO loss during the pregrasp transit.

The real 2026-07-15 logs localised the bottle 7/7 frames, validated the point
cloud corridor, executed the first movel, then aborted before segment two only
because the translated wrist view no longer passed the close-bottle shape
filter.  The locked target and geometric safety gates remain valid; RGB-D
stream loss must still abort.
"""

from types import SimpleNamespace
import time

import numpy as np
import pytest

from bottle_grasp.core import (
    BottleDetectionLost,
    CameraFrameUnavailable,
    Detection,
    DemoParams,
    Localization,
    SafetyAbort,
)
from bottle_grasp.demo import BottleDemo


def _localization() -> Localization:
    return Localization(
        point_camera=[0.0, 0.0, 0.3],
        point_base=[0.02, 0.59, -0.135],
        pixel=[304.0, 180.0],
        depth_m=0.3,
        depth_mad_m=0.001,
        position_spread_m=0.002,
        box=[268, 52, 340, 294],
        confidence=0.12,
        frame_count=7,
    )


def _demo_with_two_segment_path():
    demo = BottleDemo.__new__(BottleDemo)
    demo.params = DemoParams()
    poses = [
        [0.22, 0.59, -0.135, 0.0, 0.0, 0.0],
        [0.105, 0.59, -0.135, 0.0, 0.0, 0.0],
    ]
    demo.candidate_path = lambda target: (poses[-1], poses[-1], poses)
    demo.safety = SimpleNamespace(assert_tcp_point=lambda *args, **kwargs: None)
    demo.collision_gate = lambda *args, **kwargs: None
    demo.stage = lambda *args, **kwargs: None

    class FakeRobot:
        def __init__(self):
            self.moves = []

        def plan_ik(self, path, params, *, allow_first_jump=False):
            assert allow_first_jump
            return [[0.0] * 7 for _ in path]

        def move_linear(self, pose, speed):
            self.moves.append(pose)

        @staticmethod
        def current_tcp():
            tcp = np.eye(4)
            tcp[:3, 3] = [0.32, 0.59, -0.135]
            return tcp

    demo.robot = FakeRobot()
    return demo, poses


def test_transient_detection_loss_after_first_segment_does_not_abort_locked_target():
    demo, poses = _demo_with_two_segment_path()
    head_checks = []
    outcomes = iter(
        [None, BottleDetectionLost("移动过程中符合形状的 bottle 检测丢失")]
    )

    def visibility_check(target_base=None):
        outcome = next(outcomes)
        if outcome:
            raise outcome

    demo.ensure_bottle_visible = visibility_check
    demo._confirm_locked_target_from_head = lambda target: head_checks.append(
        list(target)
    )

    demo._approach_pregrasp(_localization())

    assert demo.robot.moves == poses
    assert head_checks == [[0.02, 0.59, -0.135]]


def test_rgbd_stream_loss_still_aborts_before_next_segment():
    demo, poses = _demo_with_two_segment_path()
    outcomes = iter([None, CameraFrameUnavailable("RGB-D 画面中断")])

    def visibility_check(target_base=None):
        outcome = next(outcomes)
        if outcome:
            raise outcome

    demo.ensure_bottle_visible = visibility_check

    try:
        demo._approach_pregrasp(_localization())
    except SafetyAbort as exc:
        assert "画面中断" in str(exc)
    else:
        raise AssertionError("RGB-D stream loss must remain fatal")

    assert demo.robot.moves == poses[:1]


def test_visible_raw_bottle_is_associated_to_locked_projection_without_shape_gate():
    demo = BottleDemo.__new__(BottleDemo)
    demo.params = DemoParams()
    demo.camera_name = "right_wrist"
    demo.cfg = SimpleNamespace(
        calibration=SimpleNamespace(
            T_end_right_to_camera_rightwrist=np.eye(4)
        )
    )

    class FakeCamera:
        @staticmethod
        def get_frame_timestamp():
            return time.time()

        @staticmethod
        def get_latest_frames():
            return np.zeros((480, 640, 3), dtype=np.uint8), None

        @staticmethod
        def get_camera_intrinsics():
            return (
                np.array(
                    [[600.0, 0.0, 320.0], [0.0, 600.0, 240.0], [0.0, 0.0, 1.0]]
                ),
                None,
            )

    candidate = Detection((280, 220, 380, 270), 0.08, "bottle")
    assert not BottleDemo._plausible_close_bottle(candidate, (480, 640, 3))

    class FakeDetector:
        @staticmethod
        def detect(color, predicate=None):
            return candidate if predicate is None or predicate(candidate) else None

    demo.camera = FakeCamera()
    demo.wrist_detector = FakeDetector()
    demo.detector = None
    demo.robot = SimpleNamespace(current_flange=lambda: np.eye(4))

    demo.ensure_bottle_visible(target_base=np.array([0.0, 0.0, 1.0]))


def test_pregrasp_path_that_moves_farther_from_locked_bottle_is_rejected():
    demo, _ = _demo_with_two_segment_path()
    divergent = [
        [0.37, 0.59, -0.135, 0.0, 0.0, 0.0],
        [0.42, 0.59, -0.135, 0.0, 0.0, 0.0],
    ]
    demo.candidate_path = lambda target: (
        divergent[-1],
        divergent[-1],
        divergent,
    )

    with pytest.raises(SafetyAbort, match="没有朝锁定目标收敛"):
        demo._approach_pregrasp(_localization())

    assert demo.robot.moves == []
