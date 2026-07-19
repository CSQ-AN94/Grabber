"""Autonomous head-camera to wrist-camera bottle grasp state machine."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional, Sequence
from uuid import uuid4

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from .camera_access import (
    CameraAccessError,
    hardware_reset_camera,
    prepare_camera_access,
)
from . import console
from .collision import check_approach_corridor
from .core import (
    BottleDetectionLost,
    CameraFrameUnavailable,
    DemoParams,
    Localization,
    SafetyAbort,
    interpolate_joint_path,
    interpolate_poses,
    look_at_camera_pose,
    matrix_pose,
    pose_matrix,
    stop_reason,
)
from .dashboard import Dashboard, PreviewWorker, SharedState
from . import head_lock
from .perception import BottleDetector, depth_point_for_detection
from .planner import MoveItPlanner
from .robot import ArmJointReader, RobotSession
from .safe_planner import PlanTarget, SafeMotionPlanner, VerifiedPlan
from .safety import SafetyProfile, load_safety_profile
from .scene import build_scene_voxels, head_scene_points, union_scene_voxels
from .table_model import (
    TABLE_KEEPOUT_ID,
    adapt_profile_to_table,
    combine_table_fits,
    fit_table_top,
)
from .target_guard import GuardResult, LockedTargetGuard, ProjectedTargetAssociation

LOG = logging.getLogger("bottle_demo")


class BottleDemo:
    def __init__(self, args, config):
        self.args = args
        self.cfg = config
        self.params = DemoParams()
        self.stop_event = threading.Event()
        self.state = SharedState(self.stop_event)
        self.project_root = Path(args.config).resolve().parent
        run_name = (
            datetime.now().strftime("%Y%m%d_%H%M%S_%f")
            + f"_{uuid4().hex[:8]}"
        )
        self.run_dir = Path(args.output_dir) / run_name
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_log_handler = logging.FileHandler(self.run_dir / "run.log")
        # Evidence file: keeps DEBUG-level per-frame detail that the console
        # deliberately hides.
        self.run_log_handler.setLevel(logging.DEBUG)
        self.run_log_handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logging.getLogger().addHandler(self.run_log_handler)
        self.camera: Optional[Any] = None
        self.camera_name = ""
        self.robot: Optional[RobotSession] = None
        self.left_robot: Optional[ArmJointReader] = None
        self.planner: Optional[MoveItPlanner] = None
        self.detector: Optional[BottleDetector] = None
        self.wrist_detector: Optional[BottleDetector] = None
        self.dashboard: Optional[Dashboard] = None
        self.preview: Optional[PreviewWorker] = None
        self.safety: Optional[SafetyProfile] = None
        self.head_scene_voxels: list[list[float]] = []
        self.scene_voxels: list[list[float]] = []
        self.scene_boxes: list[dict] = []
        self.head_scene_captured_monotonic: Optional[float] = None
        self.grasp_rotation: Optional[np.ndarray] = None
        # Set by the entry point when console presentation is installed; the
        # workflow must stay runnable (tests, embedding) without it.
        self.timeline: Optional[console.RunTimeline] = None

    @property
    def T_flange_wrist_camera(self) -> np.ndarray:
        return np.asarray(
            self.cfg.calibration.T_end_right_to_camera_rightwrist, dtype=float
        )

    @property
    def T_base_head_camera(self) -> np.ndarray:
        return np.asarray(
            self.cfg.calibration.T_base_right_to_camera_head, dtype=float
        )

    @property
    def T_flange_tcp(self) -> np.ndarray:
        transform = np.eye(4)
        transform[2, 3] = self.params.tcp_z_m
        return transform

    def _is_read_only_vision_check(self) -> bool:
        return bool(
            getattr(self.args, "resume_at_wrist", False)
            and getattr(self.args, "stop_after_observation", False)
        )

    def stage(self, name: str, message: str = ""):
        # The stage flag lets the console formatter render workflow phases
        # differently from detail lines; file handlers ignore it.
        LOG.info(
            "%s %s" if message else "%s%s",
            name,
            message,
            extra={console.STAGE_FLAG: True},
        )
        if self.timeline is not None:
            self.timeline.mark(name)
        self.state.update(stage=name, message=message)

    @staticmethod
    def _plausible_close_bottle(detection, image_shape) -> bool:
        height, width = image_shape[:2]
        x1, y1, x2, y2 = detection.box
        box_width = max(1, x2 - x1)
        box_height = max(1, y2 - y1)
        area = box_width * box_height
        return (
            box_width >= 0.05 * width
            and box_height >= 0.25 * height
            and area >= 0.02 * width * height
            and box_height / box_width >= 1.15
        )

    def _start_camera(self, camera_name: str):
        from sensors.camera_thread import CameraThread

        if self.preview:
            self.preview.stop()
            if self.preview.is_alive():
                self.preview.join(timeout=2)
            if self.preview.is_alive():
                raise SafetyAbort("相机预览线程停止超时，拒绝切换相机")
            self.preview = None
        if self.camera:
            self.camera.stop()
            if self.camera.is_alive():
                self.camera.join(timeout=3)
            if self.camera.is_alive():
                raise SafetyAbort(
                    f"{self.camera_name or '当前'} 相机线程停止超时，"
                    "拒绝启动第二个 RGB-D pipeline"
                )
            self.camera = None
        serial = self.cfg.camera.serial_for(camera_name)
        if camera_name == "head":
            width, height = self.params.head_width, self.params.head_height
        else:
            width, height = self.cfg.camera.width, self.cfg.camera.height
        last_failure = "未知错误"
        for attempt in range(1, 4):
            try:
                prepare_camera_access(serial)
            except CameraAccessError as exc:
                raise SafetyAbort(f"{camera_name} 相机不可用: {exc}") from exc
            self.camera = CameraThread(
                serial=serial,
                width=width,
                height=height,
                fps=self.cfg.camera.fps,
                strict_serial=True,
                shared_name=camera_name,
            )
            if self.camera.initialization_successful:
                self.camera.start()
                deadline = time.time() + 5
                while (
                    self.camera.get_latest_frames()[0] is None
                    and time.time() < deadline
                ):
                    time.sleep(0.1)
                if self.camera.get_latest_frames()[0] is not None:
                    break
                last_failure = "pipeline 已启动但 5 秒内没有画面"
                self.camera.stop()
                if self.camera.is_alive():
                    self.camera.join(timeout=3)
                if self.camera.is_alive():
                    raise SafetyAbort(
                        f"{camera_name} 相机线程停止超时，拒绝重建 pipeline"
                    )
            else:
                detail = getattr(self.camera, "initialization_error", None)
                last_failure = detail or "pipeline 初始化失败"
                self.camera.stop()
            self.camera = None
            if attempt == 1:
                LOG.warning(
                    "%s 相机第一次打开失败（%s）；释放后重建 pipeline 一次",
                    camera_name,
                    last_failure,
                )
                time.sleep(1.0)
            elif attempt == 2:
                LOG.warning(
                    "%s 相机两次打开都无帧；执行一次相机硬件重启后最后重试",
                    camera_name,
                )
                try:
                    hardware_reset_camera(serial)
                except CameraAccessError as exc:
                    raise SafetyAbort(
                        f"{camera_name} 相机硬件恢复失败: {exc}"
                    ) from exc
        else:
            raise SafetyAbort(
                f"{camera_name} 相机重建及硬件重启后仍无画面: {last_failure}"
            )
        self.camera_name = camera_name
        if camera_name == "right_wrist" and self.wrist_detector is None:
            fallback = (
                self.project_root
                / "intelligence"
                / "yolo_models"
                / "yolo11n.pt"
            )
            self.wrist_detector = BottleDetector(str(fallback), 0.05)
        self.preview = PreviewWorker(self.camera, self.state)
        self.preview.start()
        self.state.update(detection=None, depth_m=None)

    def _ensure_head_reference(self):
        """在一切开始前，强制把头部舵机拉回标定基准角度（俯仰最低、左右居中）。

        `T_base_right_to_camera_head` 只在头部处于这个角度时有效——头部可能
        被人手动摆过（现场调试 head_camera_control.py），或者被 SDK 初始化
        的未知副作用带偏（旧 ArmController 有过这个实测坑，RobotSession 是
        否也有暂未排除，见项目记忆）。不管原因是什么，每次运行都强制校正
        一遍，不假设"应该还在原位"。
        """
        if getattr(self.args, "finish_from_current", False) or self._is_read_only_vision_check():
            # Finish does not use vision.  `resume check` promises not to move
            # hardware, so it cannot correct the head servos.  Motion-capable
            # resume does use the fixed head camera as an independent fallback.
            return
        current = head_lock.read_current_angle()
        if head_lock.is_at_reference(current):
            self.stage("头部基准位确认", f"未漂移: {current}")
            return
        self.stage(
            "头部基准位校正",
            f"当前 {current}，目标 {head_lock.HEAD_REFERENCE}",
        )
        if not self.args.execute:
            LOG.warning(
                "头部偏离标定基准角度，但当前非 --execute 不实际驱动舵机；"
                "真机执行前必须先解决，否则头部相机定位不可信"
            )
            return
        result = head_lock.restore_reference()
        if not result["ok"]:
            raise SafetyAbort(
                f"头部无法回到标定基准角度: {result.get('reason')}"
            )
        self.stage(
            "头部基准位已校正",
            f"{result['angle']}，用了 {result['steps']} 步",
        )

    def initialize(self):
        self._ensure_head_reference()
        self.safety = load_safety_profile(
            self.args.safety_config,
            self.args.safety_profile,
            require_verified=self.args.execute,
        )
        self.scene_boxes = self.safety.moveit_collision_boxes()
        self.stage(
            "初始化",
            (
                f"电子围栏 profile={self.safety.name}；"
                "固定头部 RGB-D 搜索水瓶"
            ),
        )
        task_mode = getattr(self.args, "task_mode", None)
        # Both supported task modes create a fresh fixed-head lock.  In
        # particular, FROM_OBSERVATION is a physical starting condition, not a
        # request to resume from an old localization file.
        skip_head = bool(
            not task_mode
            and (
                self.args.resume_at_wrist
                or getattr(self.args, "finish_from_current", False)
            )
        )
        needs_head_fallback = bool(
            self.args.resume_at_wrist
            and self.args.execute
            and not self._is_read_only_vision_check()
        )
        if not skip_head or needs_head_fallback:
            self.detector = BottleDetector(
                self.cfg.vision.model_path,
                self.params.confidence,
                fallback_model_path=str(
                    self.project_root / "intelligence" / "yolo_models" / "yolo11n.pt"
                ),
                fallback_confidence=0.05,
            )
        self.dashboard = Dashboard(self.state, self.args.host, self.args.port)
        self.dashboard.start()
        self._start_camera("right_wrist" if skip_head else "head")

        read_only_vision_check = self._is_read_only_vision_check()
        needs_robot = (
            self.args.plan_only or self.args.execute or read_only_vision_check
        )
        if needs_robot:
            self.robot = RobotSession(
                self.cfg.connections.right_arm_ip,
                self.cfg.connections.arm_port,
                self.stop_event,
                self.params.tcp_z_m,
                self.params.moveit_link7_to_controller_flange_m,
                take_control=self.args.execute and not read_only_vision_check,
            )
        needs_planner = self.args.plan_only or (
            self.args.execute and not read_only_vision_check
        )
        if needs_planner:
            self.left_robot = ArmJointReader(
                self.cfg.connections.left_arm_ip,
                self.cfg.connections.arm_port,
            )
            self.planner = MoveItPlanner(self.project_root, self.run_dir)
            self.planner.start()

    def _load_resume_localization(self) -> Localization:
        output_dir = Path(self.args.output_dir)
        candidates = [
            path
            for path in output_dir.glob("*/*_localization.json")
            if "右腕" in path.name or "预抓取" in path.name
        ]

        def resume_priority(path: Path):
            if "右腕续抓定位" in path.name:
                priority = 0
            elif "右腕精定位" in path.name:
                priority = 1
            else:
                priority = 2
            return priority, -path.stat().st_mtime

        candidates.sort(key=resume_priority)
        for path in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                localization = Localization(**payload)
            except (OSError, TypeError, ValueError, json.JSONDecodeError):
                continue
            self.stage(
                "加载续抓先验",
                f"{path.parent.name}/{path.name}: {localization.point_base}",
            )
            return localization
        raise SafetyAbort("续抓模式找不到上一轮腕部稳定定位记录")

    def localize(
        self,
        label: str,
        transform_provider: Callable[[], np.ndarray],
        depth_params: DemoParams,
        depth_prior_base: Optional[np.ndarray] = None,
        *,
        allow_depth_prior_fallback: bool = True,
    ) -> Localization:
        self.stage(label, f"{self.camera_name} 连续采集 {depth_params.samples} 帧")
        K, _ = self.camera.get_camera_intrinsics()
        if K is None:
            raise SafetyAbort("相机内参不可用")
        camera_points, base_points = [], []
        depths, mads, detections, pixels = [], [], [], []
        last_timestamp = 0.0
        deadline = time.time() + max(10, depth_params.samples * 2.5)
        while len(camera_points) < depth_params.samples and time.time() < deadline:
            if self.stop_event.is_set():
                raise SafetyAbort(stop_reason(self.stop_event))
            timestamp = self.camera.get_frame_timestamp()
            if timestamp <= last_timestamp:
                time.sleep(0.03)
                continue
            last_timestamp = timestamp
            color, depth = self.camera.get_latest_frames()
            if color is None or depth is None:
                continue
            detector = (
                self.wrist_detector
                if self.camera_name == "right_wrist"
                else self.detector
            )
            predicate = None
            association = None
            T_base_camera = None
            if self.camera_name == "right_wrist":
                shape = color.shape
                if depth_prior_base is None:
                    predicate = lambda det: self._plausible_close_bottle(det, shape)
                else:
                    T_base_camera = transform_provider()
                    association = ProjectedTargetAssociation.from_view(
                        target_base=np.asarray(depth_prior_base, dtype=float),
                        T_base_camera=T_base_camera,
                        intrinsics=K,
                        image_shape=shape,
                    )
                    predicate = association.accepts
            elif depth_prior_base is not None:
                # Independent head confirmations must associate the same
                # locked object too; with multiple bottles, a generic class
                # detection is not evidence that the released target stayed
                # at its table location.
                T_base_camera = transform_provider()
                association = ProjectedTargetAssociation.from_view(
                    target_base=np.asarray(depth_prior_base, dtype=float),
                    T_base_camera=T_base_camera,
                    intrinsics=K,
                    image_shape=color.shape,
                )
                predicate = association.accepts
            detection = detector.detect(color, predicate)
            if detection is None:
                self.state.update(
                    detection=None, message="未检测到符合形状的 bottle"
                )
                continue
            self.state.update(detection=detection)
            # A wrist view of a transparent cylinder measures a visible
            # surface, not its centre.  Worse, a box touching the image border
            # has no stable height semantics.  When the fixed head has already
            # locked the object, wrist data may refine horizontal centring but
            # never overwrite locked depth/grasp height.
            if self.camera_name == "right_wrist" and depth_prior_base is not None:
                assert association is not None and T_base_camera is not None
                try:
                    point_camera, point_base, pixel, z = (
                        association.refine_locked_depth(
                            detection=detection,
                            target_base=np.asarray(depth_prior_base, dtype=float),
                            T_base_camera=T_base_camera,
                            intrinsics=K,
                        )
                    )
                except SafetyAbort as exc:
                    self.state.update(message=str(exc))
                    continue
                mad = 0.0
                truncated = association.touches_image_border(
                    detection, color.shape
                )
                self.state.update(
                    message=(
                        "腕部截断框：保持头部锁定深度/抓取高度，仅修正横向"
                        if truncated
                        else "腕部关联：保持头部锁定深度，仅修正横向"
                    )
                )
            else:
                try:
                    point_camera, z, mad, pixel = depth_point_for_detection(
                        depth, detection, K, depth_params
                    )
                except SafetyAbort as exc:
                    if (
                        depth_prior_base is None
                        or not allow_depth_prior_fallback
                    ):
                        self.state.update(message=str(exc))
                        continue
                    T_base_camera = transform_provider()
                    prior_camera = (
                        np.linalg.inv(T_base_camera)
                        @ np.r_[np.asarray(depth_prior_base, dtype=float), 1.0]
                    )[:3]
                    z = float(prior_camera[2])
                    if not (
                        depth_params.min_depth_m
                        <= z
                        <= depth_params.max_depth_m
                    ):
                        self.state.update(message=f"先验深度越界: {z:.3f} m")
                        continue
                    x1, y1, x2, y2 = detection.box
                    u = 0.5 * (x1 + x2)
                    v = y1 + depth_params.grasp_height_fraction * (y2 - y1)
                    point_camera = np.array(
                        [
                            (u - K[0, 2]) * z / K[0, 0],
                            (v - K[1, 2]) * z / K[1, 1],
                            z,
                        ],
                        dtype=float,
                    )
                    mad = 0.0
                    pixel = (float(u), float(v))
                if T_base_camera is None:
                    T_base_camera = transform_provider()
                point_base = (T_base_camera @ np.r_[point_camera, 1])[:3]
            camera_points.append(point_camera)
            base_points.append(point_base)
            depths.append(z)
            mads.append(mad)
            detections.append(detection)
            pixels.append(pixel)
            # Per-frame detail is evidence, not something an operator needs
            # seven copies of on screen; the console shows the consensus line
            # below, the run log keeps every frame at DEBUG.
            LOG.debug(
                "%s 帧 %d box=%s conf=%.3f base=[%.3f, %.3f, %.3f]",
                label,
                len(camera_points),
                detection.box,
                detection.confidence,
                point_base[0],
                point_base[1],
                point_base[2],
            )
            self.state.update(
                depth_m=z,
                message=f"有效帧 {len(camera_points)}/{depth_params.samples}",
            )
            time.sleep(0.08)

        if len(camera_points) < depth_params.samples:
            raise SafetyAbort(
                f"检测/深度稳定帧不足: {len(camera_points)}/{depth_params.samples}"
            )
        base = np.asarray(base_points, dtype=float)
        distances = np.linalg.norm(base[:, None, :] - base[None, :, :], axis=2)
        support = distances <= depth_params.max_position_spread_m
        support_counts = np.count_nonzero(support, axis=1)
        seed = int(np.argmax(support_counts))
        required = max(3, int(np.ceil(0.70 * len(base))))
        inliers = np.flatnonzero(support[seed])
        if len(inliers) < required:
            raise SafetyAbort(
                "多帧定位没有稳定共识: "
                f"最大同簇 {len(inliers)}/{len(base)}"
            )
        center = np.median(base[inliers], axis=0)
        inliers = np.flatnonzero(
            np.linalg.norm(base - center, axis=1)
            <= depth_params.max_position_spread_m
        )
        if len(inliers) < required:
            raise SafetyAbort(
                "多帧定位离群过滤后不足: "
                f"{len(inliers)}/{len(base)}"
            )
        center = np.median(base[inliers], axis=0)
        spread = float(
            np.max(np.linalg.norm(base[inliers] - center, axis=1))
        )
        if spread > depth_params.max_position_spread_m:
            raise SafetyAbort(f"多帧三维位置过散: {spread * 1000:.1f} mm")
        best = max(
            (detections[index] for index in inliers),
            key=lambda item: item.confidence,
        )
        localization = Localization(
            np.median(np.asarray(camera_points)[inliers], axis=0).tolist(),
            center.tolist(),
            np.median(np.asarray(pixels)[inliers], axis=0).tolist(),
            float(np.median(np.asarray(depths)[inliers])),
            float(np.median(np.asarray(mads)[inliers])),
            spread,
            list(best.box),
            best.confidence,
            len(inliers),
        )
        self.stage(
            f"{label}稳定",
            (
                f"共识帧 {len(inliers)}/{len(base)}，"
                f"散布 {spread * 1000:.1f} mm"
            ),
        )
        self._save_localization(label, localization)
        return localization

    def _save_localization(self, label: str, localization: Localization):
        color, depth = self.camera.get_latest_frames()
        stem = label.replace(" ", "_")
        if color is not None:
            cv2.imwrite(str(self.run_dir / f"{stem}_color.jpg"), color)
        if depth is not None:
            np.save(self.run_dir / f"{stem}_depth_m.npy", depth)
        (self.run_dir / f"{stem}_localization.json").write_text(
            json.dumps(asdict(localization), indent=2), encoding="utf-8"
        )

    def _observation_flange_candidates(
        self, target_base: np.ndarray
    ) -> list[np.ndarray]:
        # Make a copy: normalizing a NumPy slice in-place must not mutate the
        # detected bottle position used to construct the observation pose.
        horizontal = np.array(target_base[:2], dtype=float, copy=True)
        if np.linalg.norm(horizontal) < 0.1:
            horizontal = np.array([1.0, 0.0])
        horizontal /= np.linalg.norm(horizontal)
        lateral_axis = np.array([-horizontal[1], horizontal[0]])
        candidates = []
        for standoff in (0.30, 0.36, 0.40, 0.26):
            for height in (0.08, 0.03, 0.13, -0.02):
                for lateral in (0.0, 0.06, -0.06):
                    camera_position = target_base.copy()
                    camera_position[:2] -= horizontal * standoff
                    camera_position[:2] += lateral_axis * lateral
                    camera_position[2] += height
                    T_base_camera = look_at_camera_pose(
                        target_base, camera_position
                    )
                    optical_pitch_deg = float(
                        np.degrees(
                            np.arcsin(
                                np.clip(T_base_camera[2, 2], -1.0, 1.0)
                            )
                        )
                    )
                    if not (
                        self.params.observation_camera_min_pitch_deg
                        <= optical_pitch_deg
                        <= self.params.observation_camera_max_pitch_deg
                    ):
                        continue
                    candidates.append(
                        T_base_camera
                        @ np.linalg.inv(self.T_flange_wrist_camera)
                    )
        return candidates

    def _grasp_precheck_margin(
        self, target: PlanTarget, target_base: np.ndarray
    ) -> float | None:
        """返回该观察位通过抓取预演的最宽限位余量档位。

        分级而不是一刀切：2026-07-18 晚真机 watch 实测，10° 软余量的二元
        筛选把 11 个端点砍到只剩 1 个（瓶子位置本身处在手臂舒适区边缘，
        多数观察姿态天然贴限位），而唯一幸存者又恰好是 MoveIt 规划不出
        路径的端点（error=99999），没有备胎直接中止。现在按
        宽(10°)→中(6.5°)→执行余量(3°) 三档降级预演：宽余量候选优先，
        窄余量的保留但排后。None = 连执行余量都过不了，真正不可行。
        """
        margins = (
            self.params.observation_grasp_margin_deg,
            (
                self.params.observation_grasp_margin_deg
                + self.params.joint_limit_margin_deg
            )
            / 2,
            self.params.joint_limit_margin_deg,
        )
        for margin in margins:
            if self._grasp_precheck_ok(target, target_base, margin):
                return float(margin)
        return None

    def _grasp_precheck_ok(
        self,
        target: PlanTarget,
        target_base: np.ndarray,
        limit_margin_deg: float,
    ) -> bool:
        """预演从该观察位出发的抓取接近段是否在给定限位余量下可行。

        2026-07-18 真机 observe 实测的教训：观察位只按"转移代价+3°硬限位
        余量"选，选出了 J2 距限位 3.3° 的端点——人到了，抓取阶段 5 个 roll
        全部死于"J2 距限位过近"。观察位和抓取不是两个独立问题：这里用
        candidate_path() 完全相同的几何（观察姿态朝向作为抓取朝向、同一组
        roll 候选、同样的围栏+IK+奇异检查），从候选关节角出发做纯离线预演。
        更宽的余量档位吸收头部定位和腕部精定位之间约 3cm 的目标漂移。
        """
        tcp = target.flange @ self.T_flange_tcp
        base_rotation = tcp[:3, :3]
        precheck_params = replace(
            self.params,
            joint_limit_margin_deg=limit_margin_deg,
            # The observation endpoint must leave enough elbow bend for the
            # complete continuation.  Merely staying outside the controller's
            # hard 8-degree band reproduced the real "arrived, then singular"
            # failure after wrist relocalization.
            j4_singularity_deg=max(
                self.params.j4_singularity_deg,
                self.params.j4_escape_deg,
            ),
        )
        for roll_deg in (0, 15, -15, 30, -30):
            rotation = base_rotation @ Rotation.from_euler(
                "z", roll_deg, degrees=True
            ).as_matrix()
            _, _, _, full_path = self._local_pick_place_geometry(
                tcp,
                target_base,
                rotation,
            )
            try:
                for index, pose in enumerate(full_path, 1):
                    self.safety.assert_tcp_point(
                        pose[:3], label=f"完整抓放预检路径点 {index}"
                    )
                self.robot.plan_ik(
                    full_path,
                    precheck_params,
                    allow_first_jump=False,
                    seed_joints_deg=target.goal_joints,
                )
                return True
            except SafetyAbort as exc:
                LOG.debug(
                    "%s 抓取预检 roll %+d° 不可行: %s",
                    target.label,
                    roll_deg,
                    exc,
                )
        return False

    def _observation_plan_targets(
        self,
        target_base: np.ndarray,
        current_joints_deg: Optional[Sequence[float]] = None,
    ) -> list[PlanTarget]:
        current = np.asarray(
            (
                self.robot.joints_deg()
                if current_joints_deg is None
                else current_joints_deg
            ),
            dtype=float,
        )
        if current.shape != (7,) or not np.all(np.isfinite(current)):
            raise SafetyAbort("观察位候选评分起点必须是 7 个有限关节角")
        accepted = []
        for index, flange in enumerate(
            self._observation_flange_candidates(target_base), 1
        ):
            try:
                tcp = flange @ self.T_flange_tcp
                self.safety.assert_tcp_point(
                    tcp[:3, 3],
                    label=f"右腕观察位候选 {index}",
                )
                joints = self.robot.solve_flange_ik(
                    flange,
                    self.params,
                    seed_joints_deg=current,
                )
                score = float(
                    np.linalg.norm(
                        np.asarray(joints, dtype=float) - current
                    )
                )
                accepted.append(
                    PlanTarget(
                        label=f"右腕观察位候选 {index}",
                        flange=flange,
                        goal_joints=tuple(joints),
                        score=score,
                        # Execute the exact controller-IK branch that passed
                        # the continuation precheck; a pose goal may end on a
                        # different redundant branch near a singularity.
                        goal_constraint="joints",
                    )
                )
            except SafetyAbort as exc:
                LOG.debug("观察位候选 %d 被拒绝: %s", index, exc)
        if not accepted:
            raise SafetyAbort("所有右腕观察位候选均越界、近限位或逆解失败")
        graded: list[tuple[float, PlanTarget]] = []
        for target in accepted:
            margin = self._grasp_precheck_margin(
                target, np.asarray(target_base)
            )
            if margin is None:
                LOG.info(
                    "%s 连执行余量也未通过抓取预演，淘汰", target.label
                )
            else:
                LOG.info(
                    "%s 抓取预演可行，限位余量档位 %.1f°",
                    target.label,
                    margin,
                )
                graded.append((margin, target))
        if not graded:
            raise SafetyAbort(
                f"{len(accepted)} 个观察位端点全部未通过抓取预演"
                "（从这些姿态出发的接近段会撞限位/奇异/围栏）——"
                "目标可能位于可达边缘，考虑调整瓶子位置或移动底盘"
            )
        graded.sort(key=lambda item: (-item[0], item[1].score))
        roomy = sum(
            1
            for margin, _ in graded
            if margin >= self.params.observation_grasp_margin_deg
        )
        self.stage(
            "生成右腕观察位候选",
            (
                f"端点通过 {len(accepted)} 个；抓取预演可行（完整抓放） {len(graded)} 个"
                f"（宽余量 {roomy} 个，优先尝试）；"
                f"最多尝试前 {self.params.global_plan_max_candidates} 个"
            ),
        )
        return [target for _, target in graded]

    def _select_observation_flange(
        self, target_base: np.ndarray
    ) -> tuple[np.ndarray, list[float]]:
        """Compatibility helper returning the best endpoint, without planning."""
        target = self._observation_plan_targets(target_base)[0]
        return target.flange, list(target.goal_joints)

    def _build_head_scene(self, localization: Localization):
        if not self.safety.use_dynamic_rgbd:
            self.head_scene_voxels = []
            self.scene_voxels = []
            self.head_scene_captured_monotonic = time.monotonic()
            self.stage(
                "构建障碍场景",
                f"使用 {len(self.scene_boxes)} 个静态电子围栏禁入区",
            )
            return
        K, _ = self.camera.get_camera_intrinsics()
        if K is None:
            raise SafetyAbort("头部相机内参不可用")
        captured_monotonic = time.monotonic()
        depth_frames = self._collect_fresh_depth_frames(
            self.params.scene_samples, label="头部障碍场景"
        )
        per_frame_voxels = [
            build_scene_voxels(
                depth,
                K,
                self.T_base_head_camera,
                localization,
                self.params,
                min_depth_m=self.params.head_min_depth_m,
                max_depth_m=self.params.head_max_depth_m,
                bottom_crop=self.params.scene_image_bottom_crop,
            )
            for depth in depth_frames
        ]
        self.head_scene_voxels = union_scene_voxels(
            per_frame_voxels, self.params
        )
        self.scene_voxels = list(self.head_scene_voxels)
        table_fit = self._adapt_fence_to_measured_table(
            depth_frames, K, localization
        )
        self.head_scene_captured_monotonic = captured_monotonic
        (self.run_dir / "head_scene.json").write_text(
            json.dumps(
                {
                    "safety_profile": self.safety.name,
                    "voxel_count": len(self.scene_voxels),
                    "collision_boxes": self.scene_boxes,
                    "table_fit": (
                        None if table_fit is None else asdict(table_fit)
                    ),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        per_frame_counts = [len(item) for item in per_frame_voxels]
        self.stage(
            "构建障碍场景",
            (
                f"{len(self.scene_boxes)} 个电子围栏禁入区；"
                f"{len(self.scene_voxels)} 个动态 RGB-D 体素"
                f"（{len(depth_frames)} 帧并集，单帧 {per_frame_counts}）"
            ),
        )

    def _collect_fresh_depth_frames(
        self, count: int, *, label: str
    ) -> list[np.ndarray]:
        """Collect `count` distinct fresh depth frames, or refuse to proceed.

        Frames are keyed on the camera timestamp so this cannot silently
        return the same buffer N times — which would look like consensus
        while providing none.
        """
        if count < 1:
            raise SafetyAbort(f"{label} 的采样帧数必须至少为 1")
        frames: list[np.ndarray] = []
        last_timestamp = 0.0
        deadline = time.time() + max(6.0, count * 2.0)
        while len(frames) < count and time.time() < deadline:
            if self.stop_event.is_set():
                raise SafetyAbort(stop_reason(self.stop_event))
            timestamp = self.camera.get_frame_timestamp()
            if timestamp <= last_timestamp:
                time.sleep(0.03)
                continue
            last_timestamp = timestamp
            _, depth = self.camera.get_latest_frames()
            if depth is None:
                continue
            frames.append(depth)
        if len(frames) < count:
            raise SafetyAbort(
                f"{label} 只取到 {len(frames)}/{count} 个新鲜深度帧，"
                "RGB-D 流不稳定，拒绝用不足的采样构建避障场景"
            )
        return frames

    def _adapt_fence_to_measured_table(
        self, depth_frames: Sequence[np.ndarray], K, localization: Localization
    ):
        """每轮实测桌面，让电子围栏跟着真实桌子走（容差外拒跑）。

        MoveIt 的动态体素本来就每轮反映真实桌面；会过期的是静态配置的
        table_top 禁区和贴着旧桌面高度画的允许区下沿。桌子比配置低/远时，
        旧盒子会挡住真实桌面上方明明可用的空间（虚假拒绝）；比配置高/近时
        围栏漏保护。这里在 table_fit_height_tolerance_m 的信封内自适应，
        超出信封说明布置真的变了，fail-closed 拒跑并提示重新测量。

        高度来自多帧：单帧的统计学去噪（分箱众数+中位数）扛得住散点噪声，
        但扛不住整帧状态不对（有人手经过、曝光刚切换）。帧间不一致就拒跑，
        因为这个测量结果会直接决定本轮围栏怎么调。
        """
        # A profile without a table keepout never needed the measurement, so
        # skip the RGB-D work entirely and do not let frame disagreement
        # abort a run it cannot affect.
        if not any(
            box.id == TABLE_KEEPOUT_ID for box in self.safety.keepout_boxes
        ):
            return None
        target = np.asarray(localization.point_base, dtype=float)
        fits = [
            fit_table_top(
                head_scene_points(
                    depth,
                    K,
                    self.T_base_head_camera,
                    self.params,
                    min_depth_m=self.params.head_min_depth_m,
                    max_depth_m=self.params.head_max_depth_m,
                    bottom_crop=self.params.scene_image_bottom_crop,
                ),
                target,
                self.params,
            )
            for depth in depth_frames
        ]
        table_fit = combine_table_fits(fits, self.params)
        adapted = adapt_profile_to_table(self.safety, table_fit, self.params)
        if adapted is self.safety:
            return table_fit
        old_top = next(
            box
            for box in self.safety.keepout_boxes
            if box.id == TABLE_KEEPOUT_ID
        ).maximum[2]
        self.safety = adapted
        self.scene_boxes = self.safety.moveit_collision_boxes()
        new_top = next(
            box
            for box in self.safety.keepout_boxes
            if box.id == TABLE_KEEPOUT_ID
        ).maximum[2]
        self.stage(
            "桌面围栏自适应",
            (
                f"{len(fits)} 帧一致，实测桌面 z={table_fit.height_m:.3f}"
                f"（最少 {table_fit.inliers} 内点），禁区顶面 "
                f"{old_top:.3f} -> {new_top:.3f}"
            ),
        )
        return table_fit

    def _verified_plan_targets(
        self,
        name: str,
        targets: list[PlanTarget],
        start_right_joints_deg: Optional[Sequence[float]] = None,
        continuation_validator: Optional[
            Callable[[PlanTarget, dict], None]
        ] = None,
        trajectory_validator: Optional[
            Callable[[PlanTarget, dict], None]
        ] = None,
        enforce_endpoint_vertical_floor: bool = False,
    ) -> VerifiedPlan:
        safe_planner = SafeMotionPlanner(
            moveit=self.planner,
            robot=self.robot,
            left_robot=self.left_robot,
            safety=self.safety,
            params=self.params,
            report=self.stage,
        )
        verified = safe_planner.plan(
            name=name,
            targets=targets,
            obstacle_points=self.scene_voxels,
            collision_boxes=self.scene_boxes,
            start_right_joints_deg=start_right_joints_deg,
            continuation_validator=continuation_validator,
            trajectory_validator=trajectory_validator,
            enforce_endpoint_vertical_floor=enforce_endpoint_vertical_floor,
        )
        captured = getattr(self, "head_scene_captured_monotonic", None)
        if captured is not None:
            verified.trajectory["scene_captured_monotonic"] = float(
                captured
            )
        return verified

    def _plan_flange(
        self,
        name: str,
        target_flange: np.ndarray,
        goal_joints: Optional[list[float]] = None,
    ) -> dict:
        explicit_joint_goal = goal_joints is not None
        if goal_joints is None:
            goal_joints = self.robot.solve_flange_ik(
                target_flange, self.params
            )
        verified = self._verified_plan_targets(
            name,
            [
                PlanTarget(
                    label="固定目标",
                    flange=target_flange,
                    goal_joints=tuple(goal_joints),
                    goal_constraint=("joints" if explicit_joint_goal else "pose"),
                )
            ],
        )
        return verified.trajectory

    def _assert_no_vertical_undershoot(
        self,
        *,
        label: str,
        start_joints_deg: Sequence[float],
        trajectory: dict,
    ) -> None:
        """Reject a transfer that drops below both endpoints before rising."""
        points = trajectory.get("points_deg") or []
        if not points:
            raise SafetyAbort(f"{label}轨迹为空，无法检查垂直路线")
        start = np.asarray(start_joints_deg, dtype=float)
        if start.shape != (7,) or not np.all(np.isfinite(start)):
            raise SafetyAbort(f"{label}规划起点不是 7 个有限关节角")
        dense = interpolate_joint_path(
            start, points, self.params.planned_joint_step_deg
        )
        tcp_z = [
            float(self.robot.tcp_from_joints(start)[2, 3]),
            *[
                float(self.robot.tcp_from_joints(joints)[2, 3])
                for joints in dense
            ],
        ]
        if not np.all(np.isfinite(tcp_z)):
            raise SafetyAbort(f"{label}轨迹 TCP 高度含非有限值")
        lower_endpoint = min(tcp_z[0], tcp_z[-1])
        lowest = min(tcp_z)
        undershoot = lower_endpoint - lowest
        if (
            undershoot
            > self.params.observation_vertical_undershoot_tolerance_m
        ):
            raise SafetyAbort(
                f"{label}路线会先下探再回升: "
                f"最低点低于较低端点 {undershoot * 1000:.1f} mm "
                f"(上限 {self.params.observation_vertical_undershoot_tolerance_m * 1000:.0f} mm)"
            )

    def _plan_observation_staging(
        self,
        start_right_joints_deg: Optional[Sequence[float]] = None,
    ) -> Optional[dict]:
        """Plan the open/high departure leg configured for a low parked arm."""
        staging = self.safety.observation_staging_joints_deg
        if staging is None:
            return None
        start = np.asarray(
            (
                self.robot.joints_deg()
                if start_right_joints_deg is None
                else start_right_joints_deg
            ),
            dtype=float,
        )
        goal = np.asarray(staging, dtype=float)
        if (
            start.shape != (7,)
            or goal.shape != (7,)
            or not np.all(np.isfinite(start))
            or not np.all(np.isfinite(goal))
        ):
            raise SafetyAbort("观察准备位的起点/终点关节角无效")
        max_delta = float(np.max(np.abs(goal - start)))
        if max_delta <= self.params.planned_start_tolerance_deg:
            self.stage(
                "观察准备位",
                f"当前姿态已在准备位容差内（最大差 {max_delta:.2f}°），无需移动",
            )
            return None

        target_flange = self.robot.controller_flange_from_joints(goal)
        target_tcp = self.robot.tcp_from_joints(goal)
        if (
            np.asarray(target_flange).shape != (4, 4)
            or np.asarray(target_tcp).shape != (4, 4)
            or not np.all(np.isfinite(target_flange))
            or not np.all(np.isfinite(target_tcp))
        ):
            raise SafetyAbort("观察准备位 SDK FK 无效")
        self.safety.assert_tcp_point(
            np.asarray(target_tcp)[:3, 3], label="抬高展开观察准备位"
        )

        def validate_transfer_shape(
            _target: PlanTarget, trajectory: dict
        ) -> None:
            self._assert_no_vertical_undershoot(
                label="到观察准备位",
                start_joints_deg=start,
                trajectory=trajectory,
            )

        verified = self._verified_plan_targets(
            "moveit_observation_staging",
            [
                PlanTarget(
                    label="抬高展开观察准备位",
                    flange=np.asarray(target_flange, dtype=float),
                    goal_joints=tuple(map(float, goal)),
                    score=float(np.linalg.norm(goal - start)),
                    goal_constraint="joints",
                )
            ],
            start_right_joints_deg=start,
            trajectory_validator=validate_transfer_shape,
            enforce_endpoint_vertical_floor=True,
        )
        self.stage(
            "选择观察准备位路线",
            (
                f"从当前姿态先抬高并展开；最大关节变化 {max_delta:.1f}°，"
                f"规划尝试 {verified.attempts} 次"
            ),
        )
        return verified.trajectory

    def _plan_observation(
        self,
        target_base: np.ndarray,
        start_right_joints_deg: Optional[Sequence[float]] = None,
    ) -> dict:
        target_point = np.asarray(target_base, dtype=float)
        planning_start = np.asarray(
            (
                self.robot.joints_deg()
                if start_right_joints_deg is None
                else start_right_joints_deg
            ),
            dtype=float,
        )
        if (
            planning_start.shape != (7,)
            or not np.all(np.isfinite(planning_start))
        ):
            raise SafetyAbort("观察位规划起点必须是 7 个有限关节角")

        def validate_transfer_shape(
            _target: PlanTarget, trajectory: dict
        ) -> None:
            self._assert_no_vertical_undershoot(
                label="观察位",
                start_joints_deg=planning_start,
                trajectory=trajectory,
            )

        def validate_actual_endpoint(
            target: PlanTarget, trajectory: dict
        ) -> None:
            points = trajectory.get("points_deg") or []
            if not points:
                raise SafetyAbort("观察位轨迹为空，无法预演后续抓放")
            endpoint = tuple(map(float, points[-1]))
            actual_flange = self.robot.controller_flange_from_joints(endpoint)
            actual_target = replace(
                target,
                flange=actual_flange,
                goal_joints=endpoint,
                goal_constraint="joints",
            )
            margin = self._grasp_precheck_margin(
                actual_target, target_point
            )
            if margin is None:
                raise SafetyAbort(
                    "MoveIt 实际观察终点无法完成后续接近/抓取/抬升/放回"
                )

        verified = self._verified_plan_targets(
            "moveit_observation",
            self._observation_plan_targets(
                target_point,
                current_joints_deg=planning_start,
            ),
            start_right_joints_deg=planning_start,
            continuation_validator=validate_actual_endpoint,
            trajectory_validator=validate_transfer_shape,
            enforce_endpoint_vertical_floor=True,
        )
        self.stage(
            "选择右腕观察位",
            (
                f"{verified.target.label}，关节变化评分 "
                f"{verified.target.score:.1f}；规划尝试 {verified.attempts} 次"
            ),
        )
        return verified.trajectory

    def _execute_plan(self, name: str, plan: dict) -> None:
        def assert_scene_fresh() -> None:
            scene_time = plan.get("scene_captured_monotonic")
            if scene_time is None and getattr(self.args, "task_mode", None):
                raise SafetyAbort("规划凭证缺少 RGB-D 场景时间戳，禁止执行")
            if scene_time is None:
                return
            scene_age = time.monotonic() - float(scene_time)
            if (
                not np.isfinite(scene_age)
                or scene_age < 0
                or scene_age > self.params.scene_max_age_s
            ):
                raise SafetyAbort(
                    "规划场景已过期，禁止按旧障碍快照运动: "
                    f"age={scene_age:.1f}s, limit={self.params.scene_max_age_s:.1f}s"
                )

        assert_scene_fresh()

        expected_left = plan.get("start_left_joints_deg")
        monitor_done = threading.Event()
        monitor_errors: list[SafetyAbort] = []
        monitor = None

        def assert_left_snapshot() -> None:
            if expected_left is None:
                if getattr(self.args, "task_mode", None):
                    raise SafetyAbort("规划凭证缺少左臂起点快照，禁止执行")
                return
            if self.left_robot is None:
                raise SafetyAbort("无法读取规划时参与碰撞场景的左臂状态")
            expected = np.asarray(expected_left, dtype=float)
            actual = np.asarray(self.left_robot.joints_deg(), dtype=float)
            if (
                expected.shape != (7,)
                or actual.shape != (7,)
                or not np.all(np.isfinite(expected))
                or not np.all(np.isfinite(actual))
            ):
                raise SafetyAbort("左臂规划快照或实时反馈含非有限数/维度无效")
            error = float(np.max(np.abs(actual - expected)))
            if error > self.params.planned_start_tolerance_deg:
                raise SafetyAbort(
                    "轨迹已过期：左臂已偏离碰撞规划快照，拒绝执行: "
                    f"最大关节差={error:.2f}°，"
                    f"上限={self.params.planned_start_tolerance_deg:.2f}°"
                )

        if expected_left is not None or getattr(self.args, "task_mode", None):
            assert_left_snapshot()
            # Reading a remote left arm can block for seconds.  Recheck the
            # RGB-D snapshot *after* that read so a 44-second scene cannot be
            # executed at 46 seconds (the previous TOCTOU window).
            assert_scene_fresh()

            def monitor_left_arm() -> None:
                while not monitor_done.wait(0.5):
                    try:
                        assert_left_snapshot()
                    except SafetyAbort as exc:
                        monitor_errors.append(exc)
                        setattr(self.stop_event, "source", "left_arm_drift")
                        self.stop_event.set()
                        return

            monitor = threading.Thread(
                target=monitor_left_arm,
                name="bottle-left-arm-snapshot-guard",
                daemon=True,
            )
            monitor.start()

        self.stage(
            name,
            f"{len(plan['points_deg'])} 个 MoveIt 轨迹点，SDK {self.params.transit_speed}%",
        )
        motion_error: BaseException | None = None
        try:
            self.robot.execute_planned_joints(
                plan["points_deg"],
                self.params.transit_speed,
                self.params.planned_joint_step_deg,
                expected_start_joints_deg=plan.get("start_joints_deg"),
                start_tolerance_deg=self.params.planned_start_tolerance_deg,
                tracking_tolerance_deg=self.params.planned_tracking_tolerance_deg,
            )
        except BaseException as exc:
            motion_error = exc
        finally:
            monitor_done.set()
            if monitor is not None:
                monitor.join(timeout=9.0)
        if monitor is not None and monitor.is_alive():
            self.stop_event.set()
            self.robot.hold()
            raise SafetyAbort("左臂状态监控线程未能及时退出，拒绝继续任务")
        if monitor_errors:
            raise monitor_errors[0]
        if motion_error is not None:
            raise motion_error
        if expected_left is not None:
            assert_left_snapshot()

    def _refresh_head_scene_for_global_motion(
        self, locked_target: Localization
    ) -> None:
        """Reacquire a fixed-head world snapshot before a later global leg."""
        if self.camera_name != "head":
            self._start_camera("head")
        params = replace(
            self.params,
            samples=self.params.wrist_relocalization_samples,
            min_depth_m=self.params.head_min_depth_m,
            max_depth_m=self.params.head_max_depth_m,
            max_position_spread_m=0.06,
        )
        target = self.localize(
            "返回前头部场景确认",
            lambda: self.T_base_head_camera,
            params,
            depth_prior_base=np.asarray(locked_target.point_base, dtype=float),
        )
        shift = float(
            np.linalg.norm(
                np.asarray(target.point_base, dtype=float)
                - np.asarray(locked_target.point_base, dtype=float)
            )
        )
        if shift > self.params.head_confirmation_tolerance_m:
            raise SafetyAbort(
                "返回前瓶子位置已改变，禁止沿旧任务场景规划: "
                f"shift={shift * 1000:.1f}mm"
            )
        self._build_head_scene(target)
        self.stage(
            "返回前刷新障碍场景",
            f"固定头部重采场景；瓶子偏移 {shift * 1000:.1f} mm",
        )

    def _refresh_and_revalidate_plan(
        self,
        *,
        name: str,
        plan: dict,
        locked_target: Localization,
    ) -> None:
        """Refresh a slow global search and revalidate its exact trajectory."""
        self._refresh_head_scene_for_global_motion(locked_target)
        if self.planner is None or self.left_robot is None:
            raise SafetyAbort("刷新全局轨迹时 MoveIt/左臂读取器未初始化")
        planned_start = np.asarray(plan.get("start_joints_deg"), dtype=float)
        actual_start = np.asarray(self.robot.joints_deg(), dtype=float)
        if (
            planned_start.shape != (7,)
            or actual_start.shape != (7,)
            or not np.all(np.isfinite(planned_start))
            or not np.all(np.isfinite(actual_start))
        ):
            raise SafetyAbort("刷新轨迹复核的右臂起点无效")
        start_error = float(np.max(np.abs(actual_start - planned_start)))
        if start_error > self.params.planned_start_tolerance_deg:
            raise SafetyAbort(
                "刷新场景时右臂已偏离规划起点，必须重新规划: "
                f"最大关节差={start_error:.2f}°"
            )
        left = self.left_robot.joints_deg()
        dense = interpolate_joint_path(
            actual_start,
            plan.get("points_deg") or [],
            self.params.planned_joint_step_deg,
        )
        self.robot.validate_planned_joints(
            plan.get("points_deg") or [],
            self.params.planned_joint_step_deg,
            self.safety,
            start_joints_deg=actual_start,
        )
        self.planner.validate_exact_path(
            name=f"{name}_fresh_scene",
            start_left_joints_deg=left,
            points_deg=dense,
            obstacles=self.safety.points_to_moveit(self.scene_voxels),
            boxes=self.scene_boxes,
            planning_frame=self.safety.moveit_frame,
            tool_guard={
                "xy": self.params.tool_guard_xy_m,
                "length": self.params.tool_guard_length_m,
                "center_z": self.params.tool_guard_center_z_m,
            },
            voxel_size=self.params.scene_voxel_m,
        )
        plan["start_joints_deg"] = actual_start.tolist()
        plan["start_left_joints_deg"] = list(map(float, left))
        plan["scene_captured_monotonic"] = float(
            self.head_scene_captured_monotonic
        )
        self.stage(
            "新鲜场景轨迹复核",
            f"{name}: 原轨迹在新采 RGB-D/左臂快照下仍有效",
        )

    def _approach_pregrasp(self, wrist_target: Localization):
        """一次规划、直线分段接近到预抓取位。

        原先每前进一段就向 MoveIt 重新规划一次（蠕动式走走停停）；全局转移
        已由 SafeMotionPlanner 统一做 MoveIt 碰撞规划、后验碰撞复核和电子围栏
        复核。近距离接近仍用更可预测的直线分段，并由候选姿态围栏校验 + plan_ik
        连续性/限位/奇异检查 + 腕部点云通道检查 + 每段 RGB-D 存活检查保护。
        目标已由 7 帧锁定；横移时暂时离开 YOLO 视野只警告，到达预抓取位后
        的复检仍必须重新检测到瓶子，才会进入最后接近。
        """
        target_base = np.asarray(wrist_target.point_base)
        pregrasp_pose, _, transit_path = self.candidate_path(target_base)
        start_distance = float(
            np.linalg.norm(self.robot.current_tcp()[:3, 3] - target_base)
        )
        distances = [
            float(np.linalg.norm(np.asarray(pose[:3]) - target_base))
            for pose in transit_path
        ]
        if not distances:
            raise SafetyAbort("预抓取转移路径为空")
        if any(
            distance > start_distance + 0.005 for distance in distances
        ):
            raise SafetyAbort(
                "预抓取路径没有朝锁定目标收敛: "
                f"start={start_distance:.3f}m path={np.round(distances, 3).tolist()}"
            )
        if abs(distances[-1] - self.params.pregrasp_standoff_m) > 0.012:
            raise SafetyAbort(
                "预抓取终点距锁定目标不等于预定悬停距离: "
                f"actual={distances[-1]:.3f}m "
                f"expected={self.params.pregrasp_standoff_m:.3f}m"
            )
        # candidate_path 已校验预抓取点与最终接近段；这里补上转移段逐点围栏。
        for index, pose in enumerate(transit_path, 1):
            self.safety.assert_tcp_point(
                pose[:3], label=f"预抓取转移路径点 {index}"
            )
        self.robot.plan_ik(transit_path, self.params, allow_first_jump=False)
        self.collision_gate(wrist_target.box, target_base)
        self.stage(
            "直线接近预抓取位",
            (
                f"{len(transit_path)} 段，速度 {self.params.travel_speed}%；"
                f"距锁定目标 {start_distance * 100:.1f}→"
                f"{distances[-1] * 100:.1f} cm"
            ),
        )
        guard = LockedTargetGuard(
            wrist_check=lambda point: self.ensure_bottle_visible(
                target_base=point
            ),
            head_confirm=self._confirm_locked_target_from_head,
        )
        for index, (pose, distance) in enumerate(
            zip(transit_path, distances), 1
        ):
            guard_result = guard.verify(target_base)
            if guard_result.source == "head":
                LOG.warning(
                    "腕部检测丢失；固定头部相机已确认锁定目标，继续预抓取转移"
                )
            elif guard_result.source == "head_cached":
                LOG.warning(
                    "腕部检测再次丢失；本段沿用本次转移内刚完成的头部确认"
                )
            LOG.info(
                "锁定目标接近 %d/%d：TCP 距目标 %.1f cm，视觉来源=%s",
                index,
                len(transit_path),
                distance * 100,
                guard_result.source,
            )
            self.robot.move_linear(pose, self.params.travel_speed)

    def collision_gate(
        self,
        target_box: Optional[Sequence[int]],
        target_base: np.ndarray,
    ) -> None:
        count = check_approach_corridor(
            camera=self.camera,
            robot=self.robot,
            target_box=target_box,
            target_base=target_base,
            T_flange_camera=self.T_flange_wrist_camera,
            params=self.params,
        )
        self.stage("右腕点云通道检查", f"通过，疑似障碍点 {count}")

    def _scene_without_locked_target(
        self, target_base: np.ndarray
    ) -> list[list[float]]:
        """Remove only the locked bottle cylinder from the global RGB-D scene."""
        points = np.asarray(self.scene_voxels, dtype=float)
        target = np.asarray(target_base, dtype=float)
        if points.size == 0:
            return []
        if (
            points.ndim != 2
            or points.shape[1] != 3
            or target.shape != (3,)
            or not np.all(np.isfinite(points))
            or not np.all(np.isfinite(target))
        ):
            raise SafetyAbort("局部 MoveIt 场景点或锁定目标无效")
        radial = np.linalg.norm(points[:, :2] - target[:2], axis=1)
        is_target = (
            (radial <= self.params.target_occupancy_radius_m)
            & (
                points[:, 2]
                >= target[2] - self.params.target_occupancy_below_grasp_m
            )
            & (
                points[:, 2]
                <= target[2] + self.params.target_occupancy_above_grasp_m
            )
        )
        return points[~is_target].tolist()

    def _validate_local_joint_path(
        self,
        *,
        name: str,
        joints: Sequence[Sequence[float]],
        target_base: np.ndarray,
    ) -> None:
        """Validate an exact local IK chain with SDK fence and full MoveIt."""
        if not getattr(getattr(self, "args", None), "task_mode", None):
            return
        if self.planner is None or self.left_robot is None:
            raise SafetyAbort("完整任务局部路径缺少 MoveIt/左臂碰撞状态")
        start = self.robot.joints_deg()
        left = self.left_robot.joints_deg()
        dense = interpolate_joint_path(
            start, joints, self.params.planned_joint_step_deg
        )
        self.robot.validate_planned_joints(
            joints,
            self.params.planned_joint_step_deg,
            self.safety,
            start_joints_deg=start,
        )
        sequence = int(getattr(self, "_local_validation_sequence", 0)) + 1
        self._local_validation_sequence = sequence
        self.planner.validate_exact_path(
            name=f"local_{sequence:02d}_{name}",
            start_left_joints_deg=left,
            points_deg=dense,
            obstacles=self.safety.points_to_moveit(
                self._scene_without_locked_target(target_base)
            ),
            boxes=self.scene_boxes,
            planning_frame=self.safety.moveit_frame,
            tool_guard={
                "xy": self.params.tool_guard_xy_m,
                "length": self.params.tool_guard_length_m,
                "center_z": self.params.tool_guard_center_z_m,
            },
            voxel_size=self.params.scene_voxel_m,
        )
        self.stage(
            "局部全链碰撞复核",
            f"{name}: SDK 围栏与 MoveIt 全链/自碰/左臂/场景均通过",
        )

    def _plan_local_leg(
        self,
        name: str,
        build_path: Callable[[], list[list[float]]],
        params: DemoParams,
        *,
        allow_first_jump: bool = False,
    ) -> list[list[float]]:
        """本地笛卡尔小段（抬升/下降/退开）的统一规划入口。

        先处理"起点已在 J4 奇异带内"：绕接近轴 roll 改不了 |J4|（肘角
        大小由肩-腕距离唯一决定，绕工具 z 轴不移动腕心），2026-07-17 真机
        finish 就是这样把所有 roll 重试耗尽的。唯一干净的出路是关节空间
        弯肘逃逸（robot.escape_j4_singularity，逐点围栏校验后 movej），
        逃逸会移动 TCP，所以路径必须在逃逸之后再从新姿态构建——这就是
        这里收一个 build_path 回调而不是现成路径的原因。
        """
        if getattr(getattr(self, "args", None), "task_mode", None):
            current = np.asarray(self.robot.joints_deg(), dtype=float)
            if current.shape != (7,) or not np.all(np.isfinite(current)):
                raise SafetyAbort(f"{name} 前实时关节状态无效")
            if abs(float(current[3])) < params.j4_singularity_deg:
                raise SafetyAbort(
                    f"{name} 前 J4={current[3]:.1f}° 已进入奇异带；"
                    "完整任务禁止用未经过场景规划的临时弯肘 movej 旁路"
                )
            escaped = None
        else:
            escaped = self.robot.escape_j4_singularity(params, self.safety)
        if escaped is not None:
            self.stage(
                "J4 奇异带弯肘逃逸",
                f"{name}: 起点在奇异带内，已弯肘至 J4={escaped[3]:.1f}° 后重建路径",
            )
        return self._plan_ik_avoiding_singularity(
            build_path(),
            params,
            allow_first_jump=allow_first_jump,
        )

    def _plan_ik_avoiding_singularity(
        self,
        poses: list[list[float]],
        params: DemoParams,
        *,
        allow_first_jump: bool = False,
        roll_degrees: Sequence[float] = (0, 8, -8, 15, -15, 25, -25),
    ) -> list[list[float]]:
        """如 plan_ik，被拒绝时尝试绕接近轴（工具 z 轴）小角度重试。

        roll 重试能解决的是逆解分支/限位/关节跳变类拒绝；它改不了 |J4|
        （肘角大小由肩-腕距离唯一决定，绕工具 z 轴不移动腕心）。"起点已在
        J4 奇异带内"的场景由 _plan_local_leg 的关节空间弯肘逃逸处理，
        不要指望这里的 roll。返回值替换调用方原来的 poses 列表，因为真正
        被执行的姿态必须和通过逆解检查的姿态一致。
        """
        for roll_deg in roll_degrees:
            if roll_deg:
                roll = Rotation.from_euler(
                    "z", roll_deg, degrees=True
                ).as_matrix()
                rotated = []
                for pose in poses:
                    T = pose_matrix(pose).copy()
                    T[:3, :3] = T[:3, :3] @ roll
                    rotated.append(matrix_pose(T))
            else:
                rotated = list(poses)
            try:
                planned = self.robot.plan_ik(
                    rotated, params, allow_first_jump=allow_first_jump
                )
                target = getattr(self, "local_contact_target_base", None)
                if target is not None:
                    self._validate_local_joint_path(
                        name="local_leg",
                        joints=planned,
                        target_base=np.asarray(target, dtype=float),
                    )
                if roll_deg:
                    self.stage(
                        "绕接近轴避奇异",
                        f"当前姿态贴近 J4 奇异区，旋转 {roll_deg:+d}° 后逆解通过",
                    )
                return rotated
            except SafetyAbort as exc:
                LOG.warning("绕轴 %+.0f° 仍未通过逆解: %s", roll_deg, exc)
        raise SafetyAbort(
            "多个旋转角度均未能避开 J4 奇异区，放弃移动——若拒绝原因是"
            "路径中途进入奇异带，说明目标接近手臂最大伸展，roll 无法解决，"
            "需要调整目标高度/距离或移动底盘"
        )

    def candidate_path(
        self, target: np.ndarray
    ) -> tuple[list[float], list[float], list[list[float]]]:
        current_tcp = self.robot.current_tcp()
        current = matrix_pose(current_tcp)
        if self.grasp_rotation is None:
            self.grasp_rotation = pose_matrix(current)[:3, :3].copy()
        for roll_deg in (0, 15, -15, 30, -30):
            rotation = self.grasp_rotation @ Rotation.from_euler(
                "z", roll_deg, degrees=True
            ).as_matrix()
            pregrasp_pose, grasp_pose, path, full_path = (
                self._local_pick_place_geometry(
                    current_tcp,
                    target,
                    rotation,
                )
            )
            try:
                for index, pose in enumerate(full_path, 1):
                    self.safety.assert_tcp_point(
                        pose[:3], label=f"完整局部抓放路径点 {index}"
                    )
                planned = self.robot.plan_ik(
                    full_path,
                    self.params,
                    allow_first_jump=False,
                )
                self._validate_local_joint_path(
                    name="complete_pick_place",
                    joints=planned,
                    target_base=np.asarray(target, dtype=float),
                )
                if roll_deg:
                    self.stage(
                        "局部抓取规划",
                        (
                            f"完整抓放预演为避开 J4 奇异区，"
                            f"绕接近轴调整 {roll_deg:+d}°"
                        ),
                    )
                return pregrasp_pose, grasp_pose, path
            except SafetyAbort as exc:
                LOG.warning("候选抓取角 %+.0f° 被拒绝: %s", roll_deg, exc)
        raise SafetyAbort("所有候选抓取角均未通过逆解/限位/奇异检查")

    def _local_pick_place_geometry(
        self,
        start_tcp: np.ndarray,
        target: np.ndarray,
        rotation: np.ndarray,
    ) -> tuple[list[float], list[float], list[list[float]], list[list[float]]]:
        """Build the complete local tail used to qualify an observation pose.

        The old precheck jumped directly from the observation joint seed to a
        pregrasp pose and only checked the final approach.  It could therefore
        approve an observation pose whose very next Cartesian segment crossed
        J4's singular band.  This geometry mirrors every later local motion:
        observation→pregrasp→grasp→lift→lower→retreat.
        """
        start = np.asarray(start_tcp, dtype=float)
        target = np.asarray(target, dtype=float)
        rotation = np.asarray(rotation, dtype=float)
        if (
            start.shape != (4, 4)
            or target.shape != (3,)
            or rotation.shape != (3, 3)
            or not np.all(np.isfinite(start))
            or not np.all(np.isfinite(target))
            or not np.all(np.isfinite(rotation))
        ):
            raise SafetyAbort("完整局部抓放预演收到无效几何")
        axis = rotation[:, 2]
        grasp = np.eye(4)
        grasp[:3, :3] = rotation
        grasp[:3, 3] = target - axis * self.params.grasp_stop_short_m
        pregrasp = grasp.copy()
        pregrasp[:3, 3] = target - axis * self.params.pregrasp_standoff_m
        lift = grasp.copy()
        lift[2, 3] += self.params.lift_m

        pregrasp_pose = matrix_pose(pregrasp)
        grasp_pose = matrix_pose(grasp)
        transit = interpolate_poses(
            matrix_pose(start), pregrasp_pose, self.params.segment_m
        )
        approach = interpolate_poses(
            pregrasp_pose, grasp_pose, self.params.segment_m
        )
        lift_path = interpolate_poses(
            grasp_pose, matrix_pose(lift), self.params.segment_m
        )
        lower_path = interpolate_poses(
            matrix_pose(lift), grasp_pose, self.params.segment_m
        )
        retreat = grasp.copy()
        retreat[:3, 3] -= axis * self.params.retreat_standoff_m
        retreat_path = interpolate_poses(
            grasp_pose, matrix_pose(retreat), self.params.segment_m
        )
        return (
            pregrasp_pose,
            grasp_pose,
            transit,
            [*transit, *approach, *lift_path, *lower_path, *retreat_path],
        )

    def ensure_bottle_visible(
        self, target_base: Optional[np.ndarray] = None
    ):
        if self.camera.get_frame_timestamp() < time.time() - self.params.frame_timeout_s:
            raise CameraFrameUnavailable("RGB-D 画面中断")
        color, _ = self.camera.get_latest_frames()
        if color is None:
            raise CameraFrameUnavailable("RGB-D 彩色画面缺失")
        detector = (
            self.wrist_detector
            if self.camera_name == "right_wrist"
            else self.detector
        )
        predicate = None
        association = None
        if self.camera_name == "right_wrist":
            if target_base is None:
                shape = color.shape
                predicate = lambda det: self._plausible_close_bottle(det, shape)
            else:
                K, _ = self.camera.get_camera_intrinsics()
                if K is None:
                    raise CameraFrameUnavailable("RGB-D 相机内参缺失")
                association = ProjectedTargetAssociation.from_view(
                    target_base=np.asarray(target_base, dtype=float),
                    T_base_camera=(
                        self.robot.current_flange()
                        @ self.T_flange_wrist_camera
                    ),
                    intrinsics=K,
                    image_shape=color.shape,
                )
                predicate = association.accepts
        detection = detector.detect(color, predicate)
        if detection is None:
            detail = ""
            if association is not None:
                detail = (
                    f"；锁定目标投影={np.round(association.pixel, 1).tolist()}"
                    f" in_image={association.in_image}"
                )
            raise BottleDetectionLost(
                "移动过程中与锁定目标关联的 bottle 检测丢失" + detail
            )
        return detection

    def _confirm_locked_target_from_head(
        self,
        target_base: np.ndarray,
        *,
        restore_wrist: bool = True,
    ) -> Localization:
        """Pause between segments and independently confirm via the head camera.

        The head result never overwrites the 7-frame wrist lock.  A meaningful
        shift means the bottle may have moved, so the current path is no longer
        valid and must stop instead of being patched in flight.
        """
        if self.detector is None:
            raise BottleDetectionLost("腕部检测丢失且头部检测器未初始化")
        target = np.asarray(target_base, dtype=float)
        head_target = None
        original_error = None
        try:
            self._start_camera("head")
            head_params = replace(
                self.params,
                samples=self.params.wrist_relocalization_samples,
                min_depth_m=self.params.head_min_depth_m,
                max_depth_m=self.params.head_max_depth_m,
                max_position_spread_m=0.06,
            )
            head_target = self.localize(
                "头部补充确认",
                lambda: self.T_base_head_camera,
                head_params,
                depth_prior_base=target,
            )
        except SafetyAbort as exc:
            original_error = exc
        finally:
            if restore_wrist:
                try:
                    self._start_camera("right_wrist")
                except SafetyAbort as restore_exc:
                    raise SafetyAbort(
                        f"头部补充确认后无法恢复右腕相机: {restore_exc}"
                    ) from restore_exc
        if original_error is not None:
            raise BottleDetectionLost(
                f"腕部检测丢失，头部相机也未能确认锁定目标: {original_error}"
            ) from original_error
        shift = float(
            np.linalg.norm(np.asarray(head_target.point_base) - target)
        )
        if shift > self.params.head_confirmation_tolerance_m:
            raise SafetyAbort(
                "头部相机确认瓶子已偏离锁定目标，当前路径作废: "
                f"shift={shift * 1000:.1f}mm "
                f"limit={self.params.head_confirmation_tolerance_m * 1000:.0f}mm"
            )
        self.stage(
            "头部补充确认通过",
            f"目标相对腕部锁定点偏移 {shift * 1000:.1f} mm",
        )
        return head_target

    def _confirm_target_at_pregrasp(self, locked: Localization) -> GuardResult:
        """Confirm presence without redefining the locked grasp target.

        At pregrasp distance the eye-in-hand view is commonly clipped or
        occluded by the fingers.  Re-running full wrist 3-D localization there
        caused the real 2026-07-18 ``0/3`` abort even though the fixed head had
        just confirmed the bottle.  A live wrist-associated detection is
        preferred; only detector loss (never RGB-D stream loss) may fall back
        to the independent fixed-head observer.
        """
        target = np.asarray(locked.point_base, dtype=float)
        guard = LockedTargetGuard(
            wrist_check=lambda point: self.ensure_bottle_visible(
                target_base=point
            ),
            head_confirm=self._confirm_locked_target_from_head,
        )
        result = guard.verify(target)
        self.stage(
            "预抓取目标确认",
            (
                "腕部关联检测通过，保持原锁定抓取点"
                if result.source == "wrist"
                else "腕部局部视野丢失，固定头部确认通过；保持原锁定抓取点"
            ),
        )
        return result

    def _measure_target_from_head_3d(
        self,
        label: str,
        expected_base: np.ndarray,
    ) -> Localization:
        """Measure, never synthesize, a target associated with ``expected_base``."""
        if self.detector is None:
            raise BottleDetectionLost(f"{label}时固定头部检测器未初始化")
        if getattr(self, "camera_name", "") != "head":
            self._start_camera("head")
        head_params = replace(
            self.params,
            samples=self.params.wrist_relocalization_samples,
            min_depth_m=self.params.head_min_depth_m,
            max_depth_m=self.params.head_max_depth_m,
            max_position_spread_m=0.04,
        )
        return self.localize(
            label,
            lambda: self.T_base_head_camera,
            head_params,
            depth_prior_base=np.asarray(expected_base, dtype=float),
            allow_depth_prior_fallback=False,
        )

    def _confirm_lifted_target(self, locked: Localization) -> Localization:
        """Prove upward departure despite post-grasp box occlusion.

        The fingers hide the lower bottle after grasping, shortening YOLO's
        box.  Its 66%-of-box depth sample therefore moves upward on the bottle
        itself and is not the same semantic point as before the lift.  Require
        reliable evidence that the target moved upward without jumping to a
        horizontally different object; do not require that unstable point to
        equal exactly ``locked + lift_m``.
        """
        original = np.asarray(locked.point_base, dtype=float)
        expected = original.copy()
        expected[2] += self.params.lift_m
        measured = self._measure_target_from_head_3d("抬升三维确认", expected)
        point = np.asarray(measured.point_base, dtype=float)
        delta = point - original
        upward = float(delta[2])
        horizontal = float(np.linalg.norm(delta[:2]))
        if (
            upward < self.params.lift_confirmation_min_displacement_m
            or horizontal > self.params.lift_confirmation_max_horizontal_m
        ):
            raise SafetyAbort(
                "抬升三维确认失败（方向判定）: "
                f"向上位移={upward * 1000:.1f}mm "
                f"水平漂移={horizontal * 1000:.1f}mm"
            )
        self.stage(
            "抬升三维确认通过",
            f"向上位移 {upward * 1000:.1f} mm；水平漂移 "
            f"{horizontal * 1000:.1f} mm；保持固定头部观察",
        )
        return measured

    def _confirm_released_target(self, locked: Localization) -> str:
        """Confirm by fresh fixed-head 3-D that release returned to the lock."""
        target = np.asarray(locked.point_base, dtype=float)
        measured = self._measure_target_from_head_3d("放回三维确认", target)
        error = float(
            np.linalg.norm(np.asarray(measured.point_base, dtype=float) - target)
        )
        if error > self.params.release_confirmation_tolerance_m:
            raise SafetyAbort(
                "放回三维确认失败: "
                f"距锁定点 {error * 1000:.1f}mm，"
                f"上限 {self.params.release_confirmation_tolerance_m * 1000:.1f}mm"
            )
        self.stage(
            "放回视觉确认",
            f"固定头部实测瓶子距锁定放置点 {error * 1000:.1f} mm",
        )
        return "head"

    def _fresh_head_target(self) -> Localization:
        """Acquire a head target owned exclusively by the current run."""
        head_params = replace(
            self.params,
            min_depth_m=self.params.head_min_depth_m,
            max_depth_m=self.params.head_max_depth_m,
            max_position_spread_m=0.045,
        )
        target = self.localize(
            "头部粗定位", lambda: self.T_base_head_camera, head_params
        )
        self.safety.assert_tcp_point(
            target.point_base,
            label="头部定位的水瓶抓取点",
        )
        return target

    def _fresh_wrist_target(self, head_target: Localization) -> Localization:
        """Acquire a new wrist association without replacing locked depth/height."""
        self._start_camera("right_wrist")
        return self.localize(
            "右腕精定位",
            lambda: self.robot.current_flange() @ self.T_flange_wrist_camera,
            self.params,
            depth_prior_base=np.asarray(head_target.point_base, dtype=float),
        )

    def _verify_wrist_observation_start(self, target: Localization) -> None:
        """Reject a task started outside the calibrated wrist observation domain."""
        self.robot.assert_arm_healthy()
        current_tcp = self.robot.current_tcp()
        if (
            np.asarray(current_tcp).shape != (4, 4)
            or not np.all(np.isfinite(current_tcp))
        ):
            raise SafetyAbort("右腕观察位实时 TCP 无效")
        self.safety.assert_tcp_point(
            np.asarray(current_tcp)[:3, 3], label="右腕观察位当前 TCP"
        )
        point = np.asarray(target.point_base, dtype=float)
        point_camera = np.asarray(target.point_camera, dtype=float)
        if point.shape != (3,) or not np.all(np.isfinite(point)):
            raise SafetyAbort("右腕观察位目标坐标无效")
        if point_camera.shape != (3,) or not np.all(np.isfinite(point_camera)):
            raise SafetyAbort("右腕观察位相机坐标无效")
        depth = float(point_camera[2])
        minimum = self.params.pregrasp_standoff_m + 0.025
        maximum = min(self.params.max_depth_m, 0.55)
        if not minimum <= depth <= maximum:
            raise SafetyAbort(
                "当前右臂不在可用观察位：锁定目标的腕部纵深 "
                f"{depth:.3f} m，不在 [{minimum:.3f}, {maximum:.3f}] m"
            )
        self.safety.assert_tcp_point(point, label="右腕锁定的水瓶抓取点")
        self.local_contact_target_base = point.copy()
        # This is a no-motion IK/fence gate.  It proves the current physical
        # pose can enter the shared pregrasp recipe before any gripper action;
        # task mode additionally validates the exact IK chain in MoveIt.
        self.candidate_path(point)
        self.stage(
            "右腕观察位验证",
            f"新鲜目标纵深 {depth:.3f} m，完整抓放路径逆解/围栏/全链碰撞通过",
        )

    def run(self):
        task_mode = getattr(self.args, "task_mode", None)
        if task_mode:
            from .task import BottlePickPlaceTask, StartMode

            return BottlePickPlaceTask(self).run(StartMode(task_mode))

        self.initialize()
        self._preflight()
        if getattr(self.args, "finish_from_current", False):
            return self._finish_from_current()
        if self.args.resume_at_wrist:
            prior = self._load_resume_localization()
            self.safety.assert_tcp_point(
                prior.point_base,
                label="续抓保存的水瓶抓取点",
            )
            self.head_scene_voxels = []
            self.scene_voxels = []
            # 首次续抓定位必须全靠实测深度（不传先验），保证位置是独立
            # 测量：桌子/瓶子可能在两次运行之间被挪动过，陈旧先验会污染
            # 绝对位置。保存的先验只用作跳变门槛的参照。
            wrist_target = self.localize(
                "右腕续抓定位",
                lambda: self.robot.current_flange()
                @ self.T_flange_wrist_camera,
                self.params,
            )
            jump = float(
                np.linalg.norm(
                    np.asarray(wrist_target.point_base)
                    - np.asarray(prior.point_base)
                )
            )
            if jump > self.params.resume_prior_jump_m:
                raise SafetyAbort(
                    f"续抓目标相对保存位置跳变 {jump * 1000:.1f} mm"
                )
            if jump > self.params.max_relocalization_jump_m:
                LOG.warning(
                    "续抓目标相对保存先验偏移 %.1f mm"
                    "（桌子/瓶子可能被挪动过），以本次腕部定位为准",
                    jump * 1000,
                )
            if self.args.stop_after_observation:
                self.stage("续抓视觉确认完成", "本轮不发送运动命令")
                time.sleep(self.args.observe_seconds)
                return
            return self._finish_grasp_from_wrist(wrist_target)

        head_target = self._fresh_head_target()
        if not (self.args.plan_only or self.args.execute):
            self.stage("头部观察完成", "已自主发现水瓶；未连接或移动机械臂")
            time.sleep(self.args.observe_seconds)
            return

        self._build_head_scene(head_target)
        observation_plan = self._plan_observation(
            np.asarray(head_target.point_base)
        )
        if self.args.plan_only:
            self.stage(
                "自主规划完成",
                f"观察位轨迹 {len(observation_plan['points_deg'])} 点；未执行任何运动",
            )
            time.sleep(self.args.observe_seconds)
            return

        self._execute_plan("避障移动到右腕观察位", observation_plan)
        wrist_target = self._fresh_wrist_target(head_target)
        if self.args.stop_after_observation:
            self.stage(
                "观察位测试完成",
                (
                    f"右腕已检测水瓶，深度 {wrist_target.depth_m:.3f} m；"
                    "本轮不抓取"
                ),
            )
            time.sleep(self.args.observe_seconds)
            return
        if getattr(self.args, "confirm_before_grasp", False):
            self._wait_for_grasp_confirmation()
        self._finish_grasp_from_wrist(wrist_target)

    def _wait_for_grasp_confirmation(self):
        """观察位人工确认关卡：到位、检测到瓶子后暂停，Enter 继续/STOP 中止。

        跟"跑完 observe 停住、再另开一次 cycle"不同，这一步不重启进程——
        相机、YOLO 模型、MoveIt 只启动一次（这些初始化合计约 30-40 秒），
        操作者只是在同一次运行里对着已经到位的真实姿态按 Enter。这也避免
        了 2026-07-18 那次"observe 停住后接续抓脚本，走的是另一条跳过头部
        相机/抓取预检的代码路径"——确认后继续走的是同一个 _finish_grasp_
        from_wrist，跟 grasp/cycle 完全同一条路。
        """
        self.stage(
            "等待人工确认",
            "已到观察位并检测到水瓶；确认无误后按 Enter 继续抓取，Ctrl+C/STOP 中止",
        )
        confirmed = threading.Event()

        def _read_confirmation():
            try:
                sys.stdin.readline()
            except Exception:
                pass
            confirmed.set()

        threading.Thread(target=_read_confirmation, daemon=True).start()
        while not confirmed.is_set():
            if self.stop_event.wait(0.2):
                raise SafetyAbort("确认抓取前收到停止请求")
        self.stage("人工确认通过", "继续执行抓取")

    def _finish_grasp_from_wrist(self, wrist_target: Localization):
        """续抓/普通模式收尾：抓取抬升后按 --place-back/--return-home 决定后续动作。"""
        self._grasp_and_lift(wrist_target)
        if getattr(self.args, "place_back", False):
            self._place_back(wrist_target)
            if getattr(self.args, "return_home", False):
                self._return_home()
                self.stage("完成并保持", "已放回并返回初始姿态；STOP/Ctrl+C 结束")
            else:
                self.stage("完成并保持", "已放回；STOP/Ctrl+C 结束")
        else:
            self.stage("完成并保持", "不搬运、不放置；STOP/Ctrl+C 只保持")
        while not self.stop_event.wait(0.5):
            pass
        if getattr(self.args, "restore_teleop", False):
            self._restore_teleop()

    def _finish_from_current(self):
        """从当前姿态直接收尾：假设夹爪已抓着水瓶（上一轮运行遗留、保持在原地），
        跳过头部/腕部定位与抓取，只做放回（可选）+返回初始姿态（可选）。
        """
        self.stage(
            "从当前姿态收尾",
            "假设夹爪已抓稳水瓶，跳过定位/抓取，直接进入放回/返回流程",
        )
        if getattr(self.args, "place_back", False):
            self._place_back()
        if getattr(self.args, "return_home", False):
            self._return_home()
        self.stage("完成", "STOP/Ctrl+C 结束")
        while not self.stop_event.wait(0.5):
            pass
        if getattr(self.args, "restore_teleop", False):
            self._restore_teleop()

    def _grasp_and_lift(self, wrist_target: Localization) -> Localization:
        """从当前腕部姿态完成：直线接近 → 最后接近 → 力控夹取 → 抬升 5cm。

        返回锁定用的 refined 定位；不做放回、不阻塞——后续由调用方按
        --place-back 决定放回或保持。
        """
        self.stage(
            "从当前腕部姿态续抓",
            "视觉闭环、电子围栏校验和直线分段接近",
        )
        # 观察位夹爪前方是自由空间：先实测今天的空夹闭合基线，抓取判定
        # 不再依赖写死常量（2026-07-15 常量阈值把真实成功误判成空夹）。
        self.stage("夹爪空夹标定", "自由空间闭合一次，实测空夹基线")
        baseline = self.robot.calibrate_empty_close(self.params)
        self.stage("打开夹爪", f"空夹基线实测 pos={baseline}")

        self._approach_pregrasp(wrist_target)

        # Presence only: the 3-D target remains the head-locked/wrist-refined
        # estimate from observation distance.  A clipped near view has no
        # authority to rewrite depth or physical grasp height.
        confirmation = self._confirm_target_at_pregrasp(wrist_target)
        current_wrist_box = (
            confirmation.detection.box
            if confirmation.detection is not None
            else None
        )
        refined = wrist_target
        _, final_grasp, _ = self.candidate_path(
            np.asarray(wrist_target.point_base)
        )
        final_path = interpolate_poses(
            matrix_pose(self.robot.current_tcp()),
            final_grasp,
            self.params.segment_m,
        )
        self.robot.plan_ik(final_path, self.params)
        self.collision_gate(
            current_wrist_box,
            np.asarray(wrist_target.point_base),
        )
        self.stage(
            "低速最后接近",
            f"速度 {self.params.final_speed}%；相对视觉目标提前停止 "
            f"{self.params.grasp_stop_short_m * 100:.0f} cm",
        )
        for pose in final_path:
            # 最后10cm夹爪手指必然逐渐挡住瓶子，检测丢失是预期现象：
            # 画面中断仍然致命，检测丢失降级为警告（目标已锁定+人守急停）。
            try:
                self.ensure_bottle_visible(
                    target_base=np.asarray(wrist_target.point_base)
                )
            except BottleDetectionLost as exc:
                LOG.warning("最后接近中检测丢失（预期为夹爪遮挡）: %s", exc)
            self.robot.move_linear(pose, self.params.final_speed)

        self.stage("夹紧水瓶")
        gripper = self.robot.close_gripper(self.params)

        def build_lift_path() -> list[list[float]]:
            lift = self.robot.current_tcp()
            lift[2, 3] += self.params.lift_m
            return interpolate_poses(
                matrix_pose(self.robot.current_tcp()),
                matrix_pose(lift),
                self.params.segment_m,
            )

        lift_path = self._plan_local_leg("抬升", build_lift_path, self.params)
        self.stage("抬升 5 cm", "抓取后保持")
        for pose in lift_path:
            self.robot.move_linear(pose, self.params.final_speed)
        lifted_measurement = self._confirm_lifted_target(wrist_target)
        (self.run_dir / "grasp_lift.json").write_text(
            json.dumps(
                {
                    "final_tcp": matrix_pose(self.robot.current_tcp()),
                    "target": refined.point_base,
                    "head_lift_measurement": lifted_measurement.point_base,
                    "gripper": gripper,
                },
                indent=2,
            )
        )
        return refined

    def _place_back(self, locked_target: Optional[Localization] = None):
        """把瓶子放回原位：放低→张开→退开→确认释放→空载收拢。"""
        def build_lower_path() -> list[list[float]]:
            lower = self.robot.current_tcp()
            lower[2, 3] -= self.params.lift_m
            return interpolate_poses(
                matrix_pose(self.robot.current_tcp()),
                matrix_pose(lower),
                self.params.segment_m,
            )

        lower_path = self._plan_local_leg("放低", build_lower_path, self.params)
        self.stage("放回桌面", f"下降 {self.params.lift_m * 100:.0f} cm")
        for pose in lower_path:
            self.robot.move_linear(pose, self.params.final_speed)

        self.stage("松开夹爪")
        self.robot.open_gripper(self.params)

        # 沿抓取接近轴反向退开独立配置的释放后距离，避免手指刮倒瓶子。
        # 这里不能复用 pregrasp_standoff：观察悬停和释放后净空是两个需求。
        def build_retreat_path() -> list[list[float]]:
            tcp = self.robot.current_tcp()
            axis = tcp[:3, 2]
            retreat = tcp.copy()
            retreat[:3, 3] -= axis * self.params.retreat_standoff_m
            self.safety.assert_tcp_point(retreat[:3, 3], label="放回后退开点")
            return interpolate_poses(
                matrix_pose(tcp),
                matrix_pose(retreat),
                self.params.segment_m,
            )

        retreat_path = self._plan_local_leg(
            "退开", build_retreat_path, self.params
        )
        self.stage(
            "退开",
            f"沿接近轴反向 {self.params.retreat_standoff_m * 100:.0f} cm",
        )
        for pose in retreat_path:
            self.robot.move_linear(pose, self.params.travel_speed)
        if locked_target is not None:
            self._confirm_released_target(locked_target)
        self.stage("收拢夹爪", "手臂已退开，空载闭合夹爪")
        self.robot.close_empty_gripper(self.params)
        self.stage("放回完成", "瓶子已放回，手臂已退开，夹爪已收拢")

    def _return_home(self):
        """MoveIt 规划返回 profile 里配置的初始/垂下姿态（关节空间目标）。

        用的是跟"移动到观察位"完全相同的 SafeMotionPlanner：MoveIt 规划、
        MoveIt 密集状态后验碰撞复核、电子围栏密集 TCP 复核，以及失败后的
        有限自动换路。风险等级跟去程一致，不是另一套旁路实现。
        """
        home = self.safety.home_joints_deg
        if not home:
            raise SafetyAbort(
                f"profile {self.safety.name} 未配置 home_joints_deg，无法自动返回初始姿态"
            )
        target_flange = self.robot.controller_flange_from_joints(list(home))
        plan = self._plan_flange(
            "moveit_return_home", target_flange, goal_joints=list(home)
        )
        self._execute_plan("返回初始姿态", plan)
        current = np.asarray(self.robot.joints_deg(), dtype=float)
        error = float(np.max(np.abs(current - np.asarray(home, dtype=float))))
        self.stage("已返回初始姿态", f"距目标关节角最大偏差 {error:.2f}°")

    def _preflight(self):
        """真机运动前自检：机械臂在线、无错误码、夹爪使能+收拢。plan-only 跳过。"""
        if not self.args.execute or self._is_read_only_vision_check():
            return
        recover = getattr(self.robot, "recover_transient_joint_frame_loss", None)
        recovered = recover() if callable(recover) else []
        if recovered:
            self.stage(
                "瞬态关节错误已恢复",
                f"已清除并连续复核通过: {','.join(f'J{joint}' for joint in recovered)}",
            )
        health = self.robot.assert_arm_healthy()
        self.robot.current_tcp()  # 内部校验 arm_err/sys_err，异常即抛
        controller_fence = self.robot.controller_fence_status()
        fence_state = controller_fence["state"]
        enabled = bool(fence_state.get("enable_state", False))
        self.stage(
            "控制器原生围栏检查",
            (
                f"enable={enabled}；current={controller_fence['current']}；"
                f"saved={controller_fence['saved']}"
            ),
        )
        if enabled:
            raise SafetyAbort(
                "控制器原生电子围栏仍处于启用状态；本程序不会擅自删除或"
                "关闭硬件安全配置。先核对/停用旧围栏后再运动: "
                f"{controller_fence}"
            )
        state = self.robot.gripper_state()
        self.stage(
            "运动前自检",
            (
                "控制器及 7 个关节无错误码且已使能；"
                f"夹爪 enable={state.get('enable_state')}；"
                f"controller={health['controller']}"
            ),
        )
        if not getattr(self.args, "finish_from_current", False):
            self._close_gripper_if_open(state)

    def _close_gripper_if_open(self, state: dict):
        """转移开始前把张开的夹爪收拢到空载基线。

        张开的手指是比 tool_guard 固定防撞盒更宽、更不可预测的碰撞形状，
        闭合是已知、更小的包络，也不会在长距离转移途中勾挂到东西。用
        close_empty_gripper（无抓取判定的收拢语义）而不是 close_gripper——
        这里不是在抓取，强行套用抓取判定只会把"本来就是空的"误判成失败。
        只有 --finish-from-current（假设夹爪已抓着水瓶）跳过这一步，由
        `_preflight` 的调用方保证。
        """
        pos = int(state["pos"][0])
        if pos <= self.params.gripper_pretransit_open_threshold:
            return
        self.stage(
            "夹爪预备闭合",
            f"运动前检测到夹爪未闭合 (pos={pos})，先收拢到空载基线再继续",
        )
        self.robot.close_empty_gripper(self.params)

    def _restore_teleop(self):
        """best-effort 恢复官方遥操（--restore-teleop）。找不到脚本就只打印提示。"""
        import subprocess

        script = os.environ.get(
            "UPSTART_ALL", "/home/rm/rmc_aida_l_atom/scripts/upstart_all.sh"
        )
        if not os.path.exists(script):
            LOG.warning(
                "未找到 %s，无法自动恢复遥操；请手动运行官方 upstart_all.sh", script
            )
            return
        self.stage("恢复遥操", f"运行 {script}")
        subprocess.Popen(
            f"bash '{script}' > /home/rm/upstart_all_from_demo.log 2>&1 &",
            shell=True,
        )

    def close(self):
        self.stop_event.set()
        summary = {
            "stage": self.state.status(),
            "plan_only": bool(self.args.plan_only),
            "execute": bool(self.args.execute),
        }
        if self.dashboard:
            self.dashboard.close()
        if self.preview:
            self.preview.stop()
            if self.preview.is_alive():
                self.preview.join(timeout=2)
        if self.planner:
            self.planner.close()
        if self.robot:
            if self.robot.take_control:
                try:
                    summary["final_tcp"] = matrix_pose(self.robot.current_tcp())
                except Exception as exc:
                    summary["final_tcp_error"] = str(exc)
                self.robot.hold()
            self.robot.close()
        if self.left_robot:
            self.left_robot.close()
        (self.run_dir / "run_summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if self.camera:
            self.camera.stop()
            if self.camera.is_alive():
                self.camera.join(timeout=3)
        logging.getLogger().removeHandler(self.run_log_handler)
        self.run_log_handler.close()
