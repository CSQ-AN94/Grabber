"""Configuration-driven electronic fence checks for real-arm planning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .core import SafetyAbort


@dataclass(frozen=True)
class FenceBox:
    id: str
    minimum: tuple[float, float, float]
    maximum: tuple[float, float, float]

    @classmethod
    def from_dict(cls, data: dict, *, prefix: str) -> "FenceBox":
        object_id = str(data.get("id", prefix))
        minimum = np.asarray(data.get("min"), dtype=float)
        maximum = np.asarray(data.get("max"), dtype=float)
        if minimum.shape != (3,) or maximum.shape != (3,):
            raise SafetyAbort(f"电子围栏 {object_id} 的 min/max 必须各有 3 个数")
        if not np.all(np.isfinite(minimum)) or not np.all(np.isfinite(maximum)):
            raise SafetyAbort(f"电子围栏 {object_id} 包含非有限数值")
        if np.any(maximum <= minimum):
            raise SafetyAbort(f"电子围栏 {object_id} 的 max 必须大于 min")
        return cls(
            id=object_id,
            minimum=tuple(map(float, minimum)),
            maximum=tuple(map(float, maximum)),
        )

    def contains(self, point: Sequence[float], margin_m: float = 0.0) -> bool:
        point = np.asarray(point, dtype=float)
        lower = np.asarray(self.minimum) + margin_m
        upper = np.asarray(self.maximum) - margin_m
        return bool(np.all(point >= lower) and np.all(point <= upper))

    def contains_expanded(
        self, point: Sequence[float], margin_m: float = 0.0
    ) -> bool:
        point = np.asarray(point, dtype=float)
        lower = np.asarray(self.minimum) - margin_m
        upper = np.asarray(self.maximum) + margin_m
        return bool(np.all(point >= lower) and np.all(point <= upper))

    def moveit_box(self) -> dict:
        minimum = np.asarray(self.minimum, dtype=float)
        maximum = np.asarray(self.maximum, dtype=float)
        return {
            "id": f"fence_{self.id}",
            "center": ((minimum + maximum) / 2).tolist(),
            "size": (maximum - minimum).tolist(),
        }


@dataclass(frozen=True)
class SafetyProfile:
    name: str
    description: str
    frame: str
    moveit_frame: str
    T_moveit_from_profile: np.ndarray
    verified_for_execution: bool
    clearance_m: float
    tcp_workspace: FenceBox
    allowed_tcp_zones: tuple[FenceBox, ...]
    keepout_boxes: tuple[FenceBox, ...]
    use_dynamic_rgbd: bool
    guided_path: Path | None
    guided_start_tolerance_deg: float

    def assert_tcp_point(
        self,
        point: Sequence[float],
        *,
        label: str,
        margin_m: float | None = None,
    ):
        margin = self.clearance_m if margin_m is None else margin_m
        point = np.asarray(point, dtype=float)
        if point.shape != (3,) or not np.all(np.isfinite(point)):
            raise SafetyAbort(f"{label} 的 TCP 坐标无效: {point.tolist()}")
        if not self.tcp_workspace.contains(point, margin):
            raise SafetyAbort(
                f"{label} 越出总工作空间: {np.round(point, 4).tolist()}"
            )
        for obstacle in self.keepout_boxes:
            if obstacle.contains_expanded(point, margin):
                raise SafetyAbort(
                    f"{label} 进入禁入区 {obstacle.id}: "
                    f"{np.round(point, 4).tolist()}"
                )
        # Allowed zones are authored as already-safe corridors. Do not shrink
        # each box independently: doing so creates artificial gaps where two
        # valid transit volumes overlap. Clearance is still enforced against
        # the outer workspace and every expanded keepout object above.
        if not any(zone.contains(point, 0.0) for zone in self.allowed_tcp_zones):
            raise SafetyAbort(
                f"{label} 不在任何允许区: {np.round(point, 4).tolist()}"
            )

    def assert_tcp_path(self, points: Iterable[Sequence[float]]) -> int:
        count = 0
        for count, point in enumerate(points, 1):
            self.assert_tcp_point(point, label=f"轨迹 TCP 点 {count}")
        if count == 0:
            raise SafetyAbort("电子围栏检查收到空轨迹")
        return count

    def moveit_collision_boxes(self) -> list[dict]:
        # MoveIt 只做几何碰撞，不知道围栏检查还要求 clearance_m 的 TCP 余量；
        # 如果给它精确盒子，它会规划出"贴着盒面飞"的路径，随后被离线围栏
        # 复核否决。这里把顶面(+z)垫高 clearance_m+1cm 让规划阶段就绕开；
        # 侧面保持精确，避免挤掉桌边旁的示教通道。
        top_padding = self.clearance_m + 0.01
        result = []
        for box in self.keepout_boxes:
            item = box.moveit_box()
            item["center"][2] += top_padding / 2
            item["size"][2] += top_padding
            item["center"] = self.point_to_moveit(item["center"]).tolist()
            result.append(item)
        return result

    def moveit_workspace(self) -> dict:
        minimum = self.point_to_moveit(self.tcp_workspace.minimum)
        maximum = self.point_to_moveit(self.tcp_workspace.maximum)
        return {
            "min": np.minimum(minimum, maximum).tolist(),
            "max": np.maximum(minimum, maximum).tolist(),
        }

    def point_to_moveit(self, point: Sequence[float]) -> np.ndarray:
        return (self.T_moveit_from_profile @ np.r_[point, 1.0])[:3]

    def points_to_moveit(
        self, points: Iterable[Sequence[float]]
    ) -> list[list[float]]:
        return [self.point_to_moveit(point).tolist() for point in points]

    def pose_to_moveit(self, pose: np.ndarray) -> np.ndarray:
        return self.T_moveit_from_profile @ np.asarray(pose, dtype=float)


def load_safety_profile(
    path: str | Path,
    profile_name: str,
    *,
    require_verified: bool,
) -> SafetyProfile:
    path = Path(path)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SafetyAbort(f"电子围栏配置不存在: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SafetyAbort(f"电子围栏配置无法读取: {path}: {exc}") from exc
    profiles = data.get("profiles", {})
    if profile_name not in profiles:
        raise SafetyAbort(f"电子围栏 profile 不存在: {profile_name}")
    raw = profiles[profile_name]
    if not raw.get("enabled", False):
        raise SafetyAbort(f"电子围栏 profile 尚未启用: {profile_name}")
    verified = bool(raw.get("verified_for_execution", False))
    if require_verified and not verified:
        raise SafetyAbort(
            f"电子围栏 profile {profile_name} 尚未现场测量确认，禁止真机执行"
        )
    frame = str(raw.get("frame", ""))
    if frame != "right_controller_base":
        raise SafetyAbort(
            f"电子围栏坐标系必须是 right_controller_base，当前为 {frame!r}"
        )
    moveit_frame = str(raw.get("moveit_frame", ""))
    if moveit_frame != "platform_base_link":
        raise SafetyAbort(
            f"MoveIt 围栏坐标系必须是 platform_base_link，当前为 {moveit_frame!r}"
        )
    transform = np.asarray(raw.get("T_moveit_from_profile"), dtype=float)
    if transform.shape != (4, 4) or not np.all(np.isfinite(transform)):
        raise SafetyAbort("T_moveit_from_profile 必须是有效 4x4 矩阵")
    if not np.allclose(transform[:3, :3], np.eye(3), atol=1e-6):
        raise SafetyAbort(
            "当前长方体围栏只支持与 platform_base_link 轴对齐的坐标变换"
        )
    workspace = FenceBox.from_dict(
        raw.get("tcp_workspace", {}), prefix="tcp_workspace"
    )
    zones = tuple(
        FenceBox.from_dict(item, prefix=f"allowed_{index}")
        for index, item in enumerate(raw.get("allowed_tcp_zones", []))
    )
    if not zones:
        raise SafetyAbort(f"电子围栏 profile {profile_name} 没有允许区")
    keepouts = tuple(
        FenceBox.from_dict(item, prefix=f"keepout_{index}")
        for index, item in enumerate(raw.get("keepout_boxes", []))
    )
    profile = SafetyProfile(
        name=profile_name,
        description=str(raw.get("description", "")),
        frame=frame,
        moveit_frame=moveit_frame,
        T_moveit_from_profile=transform,
        verified_for_execution=verified,
        clearance_m=float(raw.get("clearance_m", 0.025)),
        tcp_workspace=workspace,
        allowed_tcp_zones=zones,
        keepout_boxes=keepouts,
        use_dynamic_rgbd=bool(raw.get("use_dynamic_rgbd", True)),
        guided_path=(
            None
            if not raw.get("guided_path")
            else (path.parent / str(raw["guided_path"])).resolve()
        ),
        guided_start_tolerance_deg=float(
            raw.get("guided_start_tolerance_deg", 3.0)
        ),
    )
    # Validate that each allowed zone is itself inside the global workspace.
    for zone in profile.allowed_tcp_zones:
        if not (
            profile.tcp_workspace.contains(zone.minimum, 0.0)
            and profile.tcp_workspace.contains(zone.maximum, 0.0)
        ):
            raise SafetyAbort(
                f"允许区 {zone.id} 超出总工作空间 {profile.tcp_workspace.id}"
            )
    return profile


def load_guided_joint_path(
    path: Path, min_joint_change_deg: float = 0.12
) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SafetyAbort(f"示教路径不存在: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise SafetyAbort(f"示教路径无法读取: {path}: {exc}") from exc
    if data.get("format") != "grabber_guided_path_v1":
        raise SafetyAbort(f"示教路径格式不支持: {path}")
    samples = data.get("samples", [])
    if len(samples) < 2:
        raise SafetyAbort(f"示教路径样本不足: {len(samples)}")
    joints = np.asarray(
        [sample.get("joints_deg") for sample in samples], dtype=float
    )
    if joints.ndim != 2 or joints.shape[1] != 7:
        raise SafetyAbort("示教路径必须是 N×7 关节角")
    if not np.all(np.isfinite(joints)):
        raise SafetyAbort("示教路径包含非有限关节角")
    compact = [joints[0]]
    for values in joints[1:-1]:
        if np.max(np.abs(values - compact[-1])) >= min_joint_change_deg:
            compact.append(values)
    compact.append(joints[-1])
    joints = np.asarray(compact, dtype=float)
    return {
        "path": str(path),
        "recorded_at": data.get("recorded_at"),
        "duration_s": float(samples[-1].get("t_s", 0.0)),
        "raw_point_count": len(samples),
        "points_deg": joints.tolist(),
    }
