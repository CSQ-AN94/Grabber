"""Standalone helpers for the shared dual-arm hand-eye calibration."""

import json
from pathlib import Path
from typing import Any, Dict, Optional

import numpy as np


CalibrationData = Dict[str, Any]


def load_calibration(path: str | Path) -> CalibrationData:
    """Load the shared calibration JSON and convert transforms to arrays."""
    with Path(path).open("r", encoding="utf-8") as stream:
        data = json.load(stream)

    transforms = data.get("transforms", {})
    if not transforms:
        raise ValueError("Calibration file does not contain a transforms section")

    data["transforms"] = {
        name: _as_transform(matrix, name)
        for name, matrix in transforms.items()
    }
    return data


def _as_transform(matrix: Any, name: str = "transform") -> np.ndarray:
    transform = np.asarray(matrix, dtype=float)
    if transform.shape != (4, 4):
        raise ValueError(f"{name} must be a 4x4 matrix")
    return transform


def _base_transform(
    calibration: CalibrationData,
    target_arm: str,
    source_arm: str,
) -> np.ndarray:
    if target_arm not in ("left", "right"):
        raise ValueError("target_arm must be 'left' or 'right'")
    if source_arm not in ("left", "right"):
        raise ValueError("source_arm must be 'left' or 'right'")
    if target_arm == source_arm:
        return np.eye(4)

    key = f"T_base_{target_arm}_to_base_{source_arm}"
    return calibration["transforms"][key]


def camera_to_arm_base(
    calibration: CalibrationData,
    camera: str,
    target_arm: str,
    T_base_to_end: Optional[np.ndarray] = None,
) -> np.ndarray:
    """Return the transform from a camera frame to an arm base frame.

    For a wrist camera, ``T_base_to_end`` must be the current pose of the
    corresponding wrist's arm end frame in that arm's base frame.
    """
    transforms = calibration["transforms"]

    if camera == "head":
        return transforms[f"T_base_{target_arm}_to_camera_head"]

    if camera == "right_wrist":
        source_arm = "right"
        wrist_key = "T_end_right_to_camera_rightwrist"
    elif camera == "left_wrist":
        source_arm = "left"
        wrist_key = "T_end_left_to_camera_leftwrist"
    else:
        raise ValueError("camera must be 'head', 'right_wrist', or 'left_wrist'")

    if T_base_to_end is None:
        raise ValueError(f"{camera} requires the current T_base_to_end")

    T_source_base_to_end = _as_transform(T_base_to_end, "T_base_to_end")
    T_source_base_to_camera = (
        T_source_base_to_end @ transforms[wrist_key]
    )
    return (
        _base_transform(calibration, target_arm, source_arm)
        @ T_source_base_to_camera
    )


def transform_point(transform: np.ndarray, point_xyz: np.ndarray) -> np.ndarray:
    """Transform one XYZ point and return XYZ in the destination frame."""
    transform = _as_transform(transform)
    point = np.asarray(point_xyz, dtype=float)
    if point.shape != (3,):
        raise ValueError("point_xyz must contain exactly three values")
    point_h = np.append(point, 1.0)
    return (transform @ point_h)[:3]
