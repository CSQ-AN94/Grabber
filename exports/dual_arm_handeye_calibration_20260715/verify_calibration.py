"""Verify rigid-transform validity and dual-arm base-transform closure."""

from pathlib import Path

import numpy as np

from handeye_transform import load_calibration


ROOT = Path(__file__).resolve().parent
CALIBRATION_FILE = ROOT / "handeye_calibration.json"


def verify_rigid_transform(name: str, transform: np.ndarray) -> None:
    rotation = transform[:3, :3]
    if not np.allclose(transform[3], [0.0, 0.0, 0.0, 1.0], atol=1e-10):
        raise AssertionError(f"{name}: invalid homogeneous bottom row")
    if not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-6):
        raise AssertionError(f"{name}: rotation is not orthonormal")
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6):
        raise AssertionError(f"{name}: rotation determinant is not +1")


def main() -> None:
    calibration = load_calibration(CALIBRATION_FILE)
    transforms = calibration["transforms"]

    for name, transform in transforms.items():
        verify_rigid_transform(name, transform)

    right_to_left = transforms["T_base_right_to_base_left"]
    left_to_right = transforms["T_base_left_to_base_right"]
    closure = right_to_left @ left_to_right
    closure_error = float(np.max(np.abs(closure - np.eye(4))))
    if closure_error > 1e-9:
        raise AssertionError(
            f"Dual-arm base-transform closure error is too large: {closure_error}"
        )

    print(f"Checked {len(transforms)} rigid transforms.")
    print(f"Dual-arm base-transform closure max error: {closure_error:.3e}")
    print("Calibration verification passed.")


if __name__ == "__main__":
    main()
