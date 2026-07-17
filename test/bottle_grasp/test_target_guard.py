import numpy as np
import pytest

from bottle_grasp.core import (
    BottleDetectionLost,
    CameraFrameUnavailable,
    DemoParams,
    Localization,
    SafetyAbort,
)
from bottle_grasp.demo import BottleDemo
from bottle_grasp.target_guard import LockedTargetGuard


def test_guard_uses_head_adapter_when_wrist_adapter_loses_detection():
    target = np.array([0.02, 0.59, -0.135])
    head_calls = []
    guard = LockedTargetGuard(
        wrist_check=lambda _: (_ for _ in ()).throw(
            BottleDetectionLost("wrist detector miss")
        ),
        head_confirm=lambda point: head_calls.append(point.copy()),
    )

    result = guard.verify(target)

    assert result.source == "head"
    assert len(head_calls) == 1
    np.testing.assert_allclose(head_calls[0], target)


def test_guard_never_converts_rgbd_stream_failure_into_head_fallback():
    guard = LockedTargetGuard(
        wrist_check=lambda _: (_ for _ in ()).throw(
            CameraFrameUnavailable("RGB-D 画面中断")
        ),
        head_confirm=lambda _: pytest.fail("stream failure must stop immediately"),
    )

    with pytest.raises(CameraFrameUnavailable, match="画面中断"):
        guard.verify(np.zeros(3))


def _demo_with_head_adapter(head_point):
    demo = BottleDemo.__new__(BottleDemo)
    demo.params = DemoParams()
    demo.detector = object()
    demo.cfg = type(
        "Cfg",
        (),
        {
            "calibration": type(
                "Calibration",
                (),
                {"T_base_right_to_camera_head": np.eye(4)},
            )()
        },
    )()
    calls = []
    demo._start_camera = lambda name: calls.append(("camera", name))
    demo.stage = lambda name, message="": calls.append(("stage", name, message))

    def localize(label, transform_provider, params, depth_prior_base=None):
        calls.append(("localize", label, params.samples, list(depth_prior_base)))
        return Localization(
            point_camera=list(head_point),
            point_base=list(head_point),
            pixel=[320, 240],
            depth_m=0.5,
            depth_mad_m=0.001,
            position_spread_m=0.002,
            box=[280, 100, 360, 400],
            confidence=0.8,
            frame_count=params.samples,
        )

    demo.localize = localize
    return demo, calls


def test_head_adapter_confirms_without_rewriting_locked_target():
    target = np.array([0.02, 0.59, -0.135])
    demo, calls = _demo_with_head_adapter(target + np.array([0.01, 0.0, 0.0]))

    demo._confirm_locked_target_from_head(target)

    assert calls[0] == ("camera", "head")
    assert calls[1][0:3] == ("localize", "头部补充确认", 3)
    assert calls[2] == ("camera", "right_wrist")
    assert any(call[0:2] == ("stage", "头部补充确认通过") for call in calls)


def test_head_adapter_restores_wrist_then_aborts_if_target_moved():
    target = np.array([0.02, 0.59, -0.135])
    demo, calls = _demo_with_head_adapter(target + np.array([0.10, 0.0, 0.0]))

    with pytest.raises(SafetyAbort, match="当前路径作废"):
        demo._confirm_locked_target_from_head(target)

    assert ("camera", "right_wrist") in calls
