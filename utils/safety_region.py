#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Image-space safety checks for shelf picking.

This module is intentionally hardware-free. It can reject crowded grasps before
the arm moves, using only detector boxes and optional depth values.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


Box = Tuple[int, int, int, int]
Detection = Dict[str, Any]


@dataclass(frozen=True)
class ImageSafetyConfig:
    image_width: int = 640
    image_height: int = 480
    corridor_width_px: int = 120
    corridor_top_px: int = 0
    corridor_bottom_padding_px: int = 35
    obstacle_padding_px: int = 12
    min_depth_gap_m: float = 0.08


def normalize_box(box: Sequence[float], image_width: int, image_height: int) -> Box:
    """Return a clipped integer xyxy box."""
    if len(box) != 4:
        raise ValueError(f"box must have four values, got {box!r}")

    x1, y1, x2, y2 = [int(round(float(v))) for v in box]
    left, right = sorted((x1, x2))
    top, bottom = sorted((y1, y2))

    left = max(0, min(image_width - 1, left))
    right = max(0, min(image_width - 1, right))
    top = max(0, min(image_height - 1, top))
    bottom = max(0, min(image_height - 1, bottom))
    return left, top, right, bottom


def expand_box(box: Sequence[float], padding_px: int, image_width: int, image_height: int) -> Box:
    x1, y1, x2, y2 = normalize_box(box, image_width, image_height)
    return normalize_box(
        (x1 - padding_px, y1 - padding_px, x2 + padding_px, y2 + padding_px),
        image_width,
        image_height,
    )


def box_center(box: Sequence[float], image_width: int, image_height: int) -> Tuple[float, float]:
    x1, y1, x2, y2 = normalize_box(box, image_width, image_height)
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def boxes_intersect(a: Sequence[float], b: Sequence[float]) -> bool:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    return ax1 <= bx2 and ax2 >= bx1 and ay1 <= by2 and ay2 >= by1


def approach_corridor(target_box: Sequence[float], config: ImageSafetyConfig) -> Box:
    """Build a vertical image-space approach corridor centered on the target."""
    cx, _ = box_center(target_box, config.image_width, config.image_height)
    half_width = config.corridor_width_px / 2.0
    _, _, _, target_bottom = normalize_box(target_box, config.image_width, config.image_height)
    bottom = target_bottom + config.corridor_bottom_padding_px
    return normalize_box(
        (cx - half_width, config.corridor_top_px, cx + half_width, bottom),
        config.image_width,
        config.image_height,
    )


def select_target(target_name: str, detections: Iterable[Detection]) -> Optional[Detection]:
    """Pick the highest-confidence exact-name match."""
    matches = [det for det in detections if det.get("name") == target_name and "box" in det]
    if not matches:
        return None
    return max(matches, key=lambda det: float(det.get("confidence", 0.0)))


def _depth_m(det: Detection) -> Optional[float]:
    for key in ("center_depth_m", "depth"):
        value = det.get(key)
        if value is not None:
            try:
                value_f = float(value)
            except (TypeError, ValueError):
                continue
            if value_f > 0:
                return value_f
    return None


def _same_depth_layer(target: Detection, obstacle: Detection, config: ImageSafetyConfig) -> bool:
    """Return true when depth cannot prove the obstacle is in a different layer."""
    target_depth = _depth_m(target)
    obstacle_depth = _depth_m(obstacle)
    if target_depth is None or obstacle_depth is None:
        return True
    return abs(target_depth - obstacle_depth) <= config.min_depth_gap_m


def evaluate_image_space_safety(
    target_name: str,
    detections: Iterable[Detection],
    config: ImageSafetyConfig | None = None,
) -> Dict[str, Any]:
    """Reject a target if another object blocks its image-space approach lane."""
    config = config or ImageSafetyConfig()
    detections = list(detections)
    target = select_target(target_name, detections)
    if target is None:
        return {
            "safe": False,
            "reason": "target_not_found",
            "message": f"target '{target_name}' was not detected",
            "target": None,
            "corridor": None,
            "blockers": [],
        }

    corridor = approach_corridor(target["box"], config)
    blockers: List[Detection] = []
    for det in detections:
        if det is target or "box" not in det:
            continue
        obstacle_box = expand_box(det["box"], config.obstacle_padding_px, config.image_width, config.image_height)
        if boxes_intersect(corridor, obstacle_box) and _same_depth_layer(target, det, config):
            blockers.append(det)

    safe = not blockers
    blocker_names = [str(det.get("name", "unknown")) for det in blockers]
    message = (
        f"safe approach corridor for '{target_name}'"
        if safe
        else f"blocked approach corridor for '{target_name}': {', '.join(blocker_names)}"
    )
    return {
        "safe": safe,
        "reason": "clear" if safe else "blocked",
        "message": message,
        "target": target,
        "corridor": corridor,
        "blockers": blockers,
    }
