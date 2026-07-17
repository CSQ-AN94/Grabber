"""Locked-target visibility supervision for multi-camera grasp motion.

The interface deliberately separates three different facts that the old
``ensure_bottle_visible`` boolean collapsed together:

* the RGB-D stream is alive;
* a wrist detection is associated with the already locked 3-D target;
* an independent head observer can confirm that target when the wrist view
  genuinely loses it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from .core import BottleDetectionLost, Detection


@dataclass(frozen=True)
class GuardResult:
    source: str


class LockedTargetGuard:
    """Verify one locked target, using head confirmation at most once per leg."""

    def __init__(
        self,
        *,
        wrist_check: Callable[[np.ndarray], None],
        head_confirm: Callable[[np.ndarray], None],
    ):
        self._wrist_check = wrist_check
        self._head_confirm = head_confirm
        self._head_confirmed = False

    def verify(self, target_base: np.ndarray) -> GuardResult:
        target = np.asarray(target_base, dtype=float)
        try:
            self._wrist_check(target)
            return GuardResult("wrist")
        except BottleDetectionLost:
            # CameraFrameUnavailable and every other SafetyAbort deliberately
            # pass through: only a live-frame detector miss is degradable.
            if not self._head_confirmed:
                self._head_confirm(target)
                self._head_confirmed = True
                return GuardResult("head")
            return GuardResult("head_cached")


@dataclass(frozen=True)
class ProjectedTargetAssociation:
    """Associate raw bottle boxes with a locked 3-D target projection."""

    pixel: tuple[float, float]
    in_front: bool
    in_image: bool

    @classmethod
    def from_view(
        cls,
        *,
        target_base: np.ndarray,
        T_base_camera: np.ndarray,
        intrinsics: np.ndarray,
        image_shape,
    ) -> "ProjectedTargetAssociation":
        target = np.r_[np.asarray(target_base, dtype=float), 1.0]
        point_camera = np.linalg.inv(np.asarray(T_base_camera, dtype=float)) @ target
        z = float(point_camera[2])
        if z <= 1e-6:
            return cls((float("nan"), float("nan")), False, False)
        K = np.asarray(intrinsics, dtype=float)
        u = float(K[0, 0] * point_camera[0] / z + K[0, 2])
        v = float(K[1, 1] * point_camera[1] / z + K[1, 2])
        height, width = image_shape[:2]
        return cls((u, v), True, 0 <= u < width and 0 <= v < height)

    def accepts(self, detection: Detection) -> bool:
        if not self.in_front or not self.in_image:
            return False
        x1, y1, x2, y2 = detection.box
        width = max(1, x2 - x1)
        height = max(1, y2 - y1)
        margin_x = max(12.0, 0.18 * width)
        margin_y = max(12.0, 0.18 * height)
        u, v = self.pixel
        return (
            x1 - margin_x <= u <= x2 + margin_x
            and y1 - margin_y <= v <= y2 + margin_y
        )
