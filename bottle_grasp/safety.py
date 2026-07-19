"""Configuration-driven electronic fence checks for real-arm planning."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np

from .core import SafetyAbort


class FenceViolation(SafetyAbort):
    """Structured electronic-fence rejection suitable for replanning."""

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        label: str,
        point: Sequence[float],
        object_id: str | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.label = label
        self.point = tuple(map(float, point))
        self.object_id = object_id


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
    home_joints_deg: tuple[float, ...] | None
    # Optional open/high posture used to leave a low natural-hang start before
    # solving the target-dependent observation transfer.  This is distinct
    # from ``home_joints_deg``: home is where the task parks; staging is a
    # proven planning seed that avoids asking one global search to both unfold
    # a near-singular arm and arrive at the bottle-facing wrist pose.
    observation_staging_joints_deg: tuple[float, ...] | None = None

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
            raise FenceViolation(
                f"{label} 越出总工作空间: {np.round(point, 4).tolist()}",
                kind="workspace",
                label=label,
                point=point,
                object_id=self.tcp_workspace.id,
            )
        for obstacle in self.keepout_boxes:
            if obstacle.contains_expanded(point, margin):
                raise FenceViolation(
                    f"{label} 进入禁入区 {obstacle.id}: "
                    f"{np.round(point, 4).tolist()}",
                    kind="keepout",
                    label=label,
                    point=point,
                    object_id=obstacle.id,
                )
        # Allowed zones are authored as already-safe corridors. Do not shrink
        # each box independently: doing so creates artificial gaps where two
        # valid transit volumes overlap. Clearance is still enforced against
        # the outer workspace and every expanded keepout object above.
        if not any(zone.contains(point, 0.0) for zone in self.allowed_tcp_zones):
            raise FenceViolation(
                f"{label} 不在任何允许区: {np.round(point, 4).tolist()}",
                kind="allowed_zone",
                label=label,
                point=point,
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
        # 复核否决。这里把四个水平侧面各向外垫，顶面也垫同样距离，让规划
        # 阶段就留足余量；底面不影响桌面上方的规划。
        #
        # 2026-07-17 真机 observe 实测：clearance_m+1cm 的旧余量不够——MoveIt
        # 按其内部路径采样分辨率认为"没碰垫大的盒子"，但独立围栏用更密的
        # 插值复核发现实际路径已经比垫大后的盒子边界还深入 1~1.7cm（8个候选、
        # 16次尝试全部在这个narrow band里被拒）。根因是 OMPL 边碰撞检测的
        # 离散化盲区，已在 moveit_headless.py 用
        # longest_valid_segment_fraction 0.01->0.0025（4倍更密）从源头收紧，
        # 采样间隔按此比例线性缩小，预期把 1~1.7cm 的偏差压到约 0.25~0.4cm。
        #
        # 2026-07-18：把这里的余量从 +5cm 回调到 +2cm——clearance_m(2.5cm)+2cm
        # =4.5cm 仍比旧实测的最大偏差 1.7cm 宽裕得多，对采样密度修复后的
        # 预期偏差（~0.4cm）留有约10倍安全系数。但这个具体数值组合
        # （更密的lvsf + 更小的padding）还没有真机验证过，不能只信这个
        # 推算——下次连机器人必须先跑 observe/plan 多轮确认没有回到
        # narrow-band拒绝循环，再信任这个余量。
        padding = self.clearance_m + 0.02
        result = []
        for box in self.keepout_boxes:
            item = box.moveit_box()
            item["size"][0] += 2 * padding
            item["size"][1] += 2 * padding
            item["center"][2] += padding / 2
            item["size"][2] += padding
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

    def replan_exclusion_box(
        self,
        violation: FenceViolation,
        *,
        object_id: str,
        size_m: float,
    ) -> dict:
        """Turn an independently rejected TCP point into MoveIt feedback."""
        center = self.point_to_moveit(violation.point)
        return {
            "id": str(object_id),
            "center": center.tolist(),
            "size": [float(size_m)] * 3,
        }


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
    # 允许各轴 ±1 的对角旋转（每个轴仍映射到自身，只翻符号）：盒子的
    # size 语义与 min/max 重排在这种变换下保持成立。实测 right_controller_base
    # 相对 platform_base_link 是 yaw 180°（diag(-1,-1,1)），纯平移是错的。
    rotation = transform[:3, :3]
    if not np.allclose(np.abs(rotation), np.eye(3), atol=1e-6):
        raise SafetyAbort(
            "当前长方体围栏只支持与 platform_base_link 轴对齐"
            "（各轴仅允许±翻转）的坐标变换"
        )
    if not np.isclose(np.linalg.det(rotation), 1.0, atol=1e-6):
        raise SafetyAbort(
            "T_moveit_from_profile 旋转部分行列式必须为 +1（不允许镜像反射）"
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
    home_raw = raw.get("home_joints_deg")
    home_joints_deg = None
    if home_raw is not None:
        home = np.asarray(home_raw, dtype=float)
        if home.shape != (7,) or not np.all(np.isfinite(home)):
            raise SafetyAbort(
                f"电子围栏 profile {profile_name} 的 home_joints_deg 必须是 7 个有限数"
            )
        home_joints_deg = tuple(map(float, home))
    staging_raw = raw.get("observation_staging_joints_deg")
    observation_staging_joints_deg = None
    if staging_raw is not None:
        staging = np.asarray(staging_raw, dtype=float)
        if staging.shape != (7,) or not np.all(np.isfinite(staging)):
            raise SafetyAbort(
                f"电子围栏 profile {profile_name} 的 "
                "observation_staging_joints_deg 必须是 7 个有限数"
            )
        observation_staging_joints_deg = tuple(map(float, staging))
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
        home_joints_deg=home_joints_deg,
        observation_staging_joints_deg=observation_staging_joints_deg,
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
