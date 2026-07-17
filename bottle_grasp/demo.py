"""Autonomous head-camera to wrist-camera bottle grasp state machine."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import cv2
import numpy as np
from scipy.spatial.transform import Rotation

from .camera_access import (
    CameraAccessError,
    hardware_reset_camera,
    prepare_camera_access,
)
from .collision import check_approach_corridor
from .core import (
    BottleDetectionLost,
    CameraFrameUnavailable,
    DemoParams,
    Localization,
    SafetyAbort,
    interpolate_poses,
    look_at_camera_pose,
    matrix_pose,
    pose_matrix,
)
from .dashboard import Dashboard, PreviewWorker, SharedState
from . import head_lock
from .perception import BottleDetector, depth_point_for_detection
from .planner import MoveItPlanner
from .robot import ArmJointReader, RobotSession
from .safe_planner import PlanTarget, SafeMotionPlanner, VerifiedPlan
from .safety import SafetyProfile, load_safety_profile
from .scene import build_scene_voxels, head_scene_points
from .table_model import (
    TABLE_KEEPOUT_ID,
    adapt_profile_to_table,
    fit_table_top,
)
from .target_guard import LockedTargetGuard, ProjectedTargetAssociation

LOG = logging.getLogger("bottle_demo")


class BottleDemo:
    def __init__(self, args, config):
        self.args = args
        self.cfg = config
        self.params = DemoParams()
        self.stop_event = threading.Event()
        self.state = SharedState(self.stop_event)
        self.project_root = Path(args.config).resolve().parent
        self.run_dir = Path(args.output_dir) / datetime.now().strftime("%Y%m%d_%H%M%S")
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.run_log_handler = logging.FileHandler(self.run_dir / "run.log")
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
        self.grasp_rotation: Optional[np.ndarray] = None

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
        LOG.info("[%s] %s", name, message)
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
            self.preview = None
        if self.camera:
            self.camera.stop()
            if self.camera.is_alive():
                self.camera.join(timeout=3)
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
        skip_head = self.args.resume_at_wrist or getattr(
            self.args, "finish_from_current", False
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
                raise SafetyAbort("用户停止")
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
            if self.camera_name == "right_wrist":
                shape = color.shape
                predicate = lambda det: self._plausible_close_bottle(det, shape)
            detection = detector.detect(color, predicate)
            if detection is None:
                self.state.update(
                    detection=None, message="未检测到符合形状的 bottle"
                )
                continue
            self.state.update(detection=detection)
            # 实测深度优先（实测证明透明瓶近距离深度可靠，MAD 1-2mm）；
            # 只有当帧内深度质量门禁失败时才退回先验纵深+二维修正。
            try:
                point_camera, z, mad, pixel = depth_point_for_detection(
                    depth, detection, K, depth_params
                )
            except SafetyAbort as exc:
                if depth_prior_base is None:
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
                self.state.update(message="透明瓶：深度不可测，退回纵深先验+二维修正")
            T_base_camera = transform_provider()
            point_base = (T_base_camera @ np.r_[point_camera, 1])[:3]
            camera_points.append(point_camera)
            base_points.append(point_base)
            depths.append(z)
            mads.append(mad)
            detections.append(detection)
            pixels.append(pixel)
            LOG.info(
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
                    candidates.append(
                        T_base_camera
                        @ np.linalg.inv(self.T_flange_wrist_camera)
                    )
        return candidates

    def _observation_plan_targets(
        self, target_base: np.ndarray
    ) -> list[PlanTarget]:
        current = np.asarray(self.robot.joints_deg(), dtype=float)
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
                joints = self.robot.solve_flange_ik(flange, self.params)
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
                    )
                )
            except SafetyAbort as exc:
                LOG.debug("观察位候选 %d 被拒绝: %s", index, exc)
        if not accepted:
            raise SafetyAbort("所有右腕观察位候选均越界、近限位或逆解失败")
        accepted.sort(key=lambda target: target.score)
        self.stage(
            "生成右腕观察位候选",
            (
                f"端点通过 {len(accepted)} 个；"
                f"最多尝试前 {self.params.global_plan_max_candidates} 个"
            ),
        )
        return accepted

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
            self.stage(
                "构建障碍场景",
                f"使用 {len(self.scene_boxes)} 个静态电子围栏禁入区",
            )
            return
        _, depth = self.camera.get_latest_frames()
        K, _ = self.camera.get_camera_intrinsics()
        self.head_scene_voxels = build_scene_voxels(
            depth,
            K,
            self.T_base_head_camera,
            localization,
            self.params,
            min_depth_m=self.params.head_min_depth_m,
            max_depth_m=self.params.head_max_depth_m,
            bottom_crop=self.params.scene_image_bottom_crop,
        )
        self.scene_voxels = list(self.head_scene_voxels)
        table_fit = self._adapt_fence_to_measured_table(depth, K, localization)
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
        self.stage(
            "构建障碍场景",
            (
                f"{len(self.scene_boxes)} 个电子围栏禁入区；"
                f"{len(self.scene_voxels)} 个动态 RGB-D 体素"
            ),
        )

    def _adapt_fence_to_measured_table(
        self, depth, K, localization: Localization
    ):
        """每轮实测桌面，让电子围栏跟着真实桌子走（容差外拒跑）。

        MoveIt 的动态体素本来就每轮反映真实桌面；会过期的是静态配置的
        table_top 禁区和贴着旧桌面高度画的允许区下沿。桌子比配置低/远时，
        旧盒子会挡住真实桌面上方明明可用的空间（虚假拒绝）；比配置高/近时
        围栏漏保护。这里在 table_fit_height_tolerance_m 的信封内自适应，
        超出信封说明布置真的变了，fail-closed 拒跑并提示重新测量。
        """
        table_fit = fit_table_top(
            head_scene_points(
                depth,
                K,
                self.T_base_head_camera,
                self.params,
                min_depth_m=self.params.head_min_depth_m,
                max_depth_m=self.params.head_max_depth_m,
                bottom_crop=self.params.scene_image_bottom_crop,
            ),
            np.asarray(localization.point_base, dtype=float),
            self.params,
        )
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
                f"实测桌面 z={table_fit.height_m:.3f}"
                f"（{table_fit.inliers} 内点），禁区顶面 "
                f"{old_top:.3f} -> {new_top:.3f}"
            ),
        )
        return table_fit

    def _verified_plan_targets(
        self,
        name: str,
        targets: list[PlanTarget],
    ) -> VerifiedPlan:
        safe_planner = SafeMotionPlanner(
            moveit=self.planner,
            robot=self.robot,
            left_robot=self.left_robot,
            safety=self.safety,
            params=self.params,
            report=self.stage,
        )
        return safe_planner.plan(
            name=name,
            targets=targets,
            obstacle_points=self.scene_voxels,
            collision_boxes=self.scene_boxes,
        )

    def _plan_flange(
        self,
        name: str,
        target_flange: np.ndarray,
        goal_joints: Optional[list[float]] = None,
    ) -> dict:
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
                )
            ],
        )
        return verified.trajectory

    def _plan_observation(self, target_base: np.ndarray) -> dict:
        verified = self._verified_plan_targets(
            "moveit_observation",
            self._observation_plan_targets(target_base),
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
        self.stage(
            name,
            f"{len(plan['points_deg'])} 个 MoveIt 轨迹点，SDK {self.params.travel_speed}%",
        )
        self.robot.execute_planned_joints(
            plan["points_deg"],
            self.params.travel_speed,
            self.params.planned_joint_step_deg,
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
        self.robot.plan_ik(transit_path, self.params, allow_first_jump=True)
        self.collision_gate(wrist_target, target_base)
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

    def collision_gate(self, localization: Localization, target_base: np.ndarray):
        count = check_approach_corridor(
            camera=self.camera,
            robot=self.robot,
            localization=localization,
            target_base=target_base,
            T_flange_camera=self.T_flange_wrist_camera,
            params=self.params,
        )
        self.stage("右腕点云通道检查", f"通过，疑似障碍点 {count}")

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
        escaped = self.robot.escape_j4_singularity(params, self.safety)
        if escaped is not None:
            self.stage(
                "J4 奇异带弯肘逃逸",
                f"{name}: 起点在奇异带内，已弯肘至 J4={escaped[3]:.1f}° 后重建路径",
            )
        return self._plan_ik_avoiding_singularity(
            build_path(), params, allow_first_jump=allow_first_jump
        )

    def _plan_ik_avoiding_singularity(
        self,
        poses: list[list[float]],
        params: DemoParams,
        *,
        allow_first_jump: bool = False,
    ) -> list[list[float]]:
        """如 plan_ik，被拒绝时尝试绕接近轴（工具 z 轴）小角度重试。

        roll 重试能解决的是逆解分支/限位/关节跳变类拒绝；它改不了 |J4|
        （肘角大小由肩-腕距离唯一决定，绕工具 z 轴不移动腕心）。"起点已在
        J4 奇异带内"的场景由 _plan_local_leg 的关节空间弯肘逃逸处理，
        不要指望这里的 roll。返回值替换调用方原来的 poses 列表，因为真正
        被执行的姿态必须和通过逆解检查的姿态一致。
        """
        for roll_deg in (0, 8, -8, 15, -15, 25, -25):
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
                self.robot.plan_ik(
                    rotated, params, allow_first_jump=allow_first_jump
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
        current = matrix_pose(self.robot.current_tcp())
        if self.grasp_rotation is None:
            self.grasp_rotation = pose_matrix(current)[:3, :3].copy()
        for roll_deg in (0, 15, -15, 30, -30):
            rotation = self.grasp_rotation @ Rotation.from_euler(
                "z", roll_deg, degrees=True
            ).as_matrix()
            axis = rotation[:, 2]
            grasp = np.eye(4)
            grasp[:3, :3] = rotation
            grasp[:3, 3] = target
            pregrasp = grasp.copy()
            pregrasp[:3, 3] = target - axis * self.params.pregrasp_standoff_m
            pregrasp_pose = matrix_pose(pregrasp)
            grasp_pose = matrix_pose(grasp)
            path = interpolate_poses(current, pregrasp_pose, self.params.segment_m)
            approach_path = interpolate_poses(
                pregrasp_pose, grasp_pose, self.params.segment_m
            )
            try:
                for index, pose in enumerate(
                    [pregrasp_pose, *approach_path],
                    1,
                ):
                    self.safety.assert_tcp_point(
                        pose[:3], label=f"局部抓取路径点 {index}"
                    )
                self.robot.plan_ik(
                    [pregrasp_pose, *approach_path],
                    self.params,
                    allow_first_jump=True,
                )
                if roll_deg:
                    self.stage(
                        "局部抓取规划",
                        f"为避开 J4 奇异区，绕接近轴调整 {roll_deg:+d}°",
                    )
                return pregrasp_pose, grasp_pose, path
            except SafetyAbort as exc:
                LOG.warning("候选抓取角 %+.0f° 被拒绝: %s", roll_deg, exc)
        raise SafetyAbort("所有候选抓取角均未通过逆解/限位/奇异检查")

    def ensure_bottle_visible(self, target_base: Optional[np.ndarray] = None):
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

    def _confirm_locked_target_from_head(self, target_base: np.ndarray) -> None:
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

    def run(self):
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

        head_params = replace(
            self.params,
            min_depth_m=self.params.head_min_depth_m,
            max_depth_m=self.params.head_max_depth_m,
            max_position_spread_m=0.045,
        )
        head_target = self.localize(
            "头部粗定位", lambda: self.T_base_head_camera, head_params
        )
        self.safety.assert_tcp_point(
            head_target.point_base,
            label="头部定位的水瓶抓取点",
        )
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
        self._start_camera("right_wrist")
        wrist_target = self.localize(
            "右腕精定位",
            lambda: self.robot.current_flange() @ self.T_flange_wrist_camera,
            self.params,
            depth_prior_base=np.asarray(head_target.point_base),
        )
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
        self._finish_grasp_from_wrist(wrist_target)

    def _finish_grasp_from_wrist(self, wrist_target: Localization):
        """续抓/普通模式收尾：抓取抬升后按 --place-back/--return-home 决定后续动作。"""
        self._grasp_and_lift(wrist_target)
        if getattr(self.args, "place_back", False):
            self._place_back()
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

        # 预抓取复检同样只做存在性确认：近距截断视野下的定位会向瓶盖漂移，
        # 最终抓取点仍以初始完整视野的锁定为准。
        recheck_params = replace(
            self.params,
            samples=self.params.wrist_relocalization_samples,
        )
        refined = self.localize(
            "预抓取复检",
            lambda: self.robot.current_flange() @ self.T_flange_wrist_camera,
            recheck_params,
            depth_prior_base=np.asarray(wrist_target.point_base),
        )
        jump = float(
            np.linalg.norm(
                np.asarray(refined.point_base) - np.asarray(wrist_target.point_base)
            )
        )
        if jump > self.params.max_relocalization_jump_m:
            LOG.warning(
                "预抓取复检目标偏移 %.1f mm（近距视野截断伪影），"
                "保持初始锁定目标",
                jump * 1000,
            )
        _, final_grasp, _ = self.candidate_path(
            np.asarray(wrist_target.point_base)
        )
        final_path = interpolate_poses(
            matrix_pose(self.robot.current_tcp()),
            final_grasp,
            self.params.segment_m,
        )
        self.robot.plan_ik(final_path, self.params)
        self.collision_gate(refined, np.asarray(wrist_target.point_base))
        self.stage("低速最后接近", f"速度 {self.params.final_speed}%")
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
        (self.run_dir / "success.json").write_text(
            json.dumps(
                {
                    "final_tcp": matrix_pose(self.robot.current_tcp()),
                    "target": refined.point_base,
                    "gripper": gripper,
                },
                indent=2,
            )
        )
        return refined

    def _place_back(self):
        """把瓶子放回原位：放低→张开→退开→空载收拢夹爪。"""
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

        # 沿抓取接近轴反向退开一个预抓取距离，避免手指刮倒瓶子
        def build_retreat_path() -> list[list[float]]:
            tcp = self.robot.current_tcp()
            axis = tcp[:3, 2]
            retreat = tcp.copy()
            retreat[:3, 3] -= axis * self.params.pregrasp_standoff_m
            self.safety.assert_tcp_point(retreat[:3, 3], label="放回后退开点")
            return interpolate_poses(
                matrix_pose(tcp),
                matrix_pose(retreat),
                self.params.segment_m,
            )

        retreat_path = self._plan_local_leg(
            "退开", build_retreat_path, self.params
        )
        self.stage("退开", f"沿接近轴反向 {self.params.pregrasp_standoff_m * 100:.0f} cm")
        for pose in retreat_path:
            self.robot.move_linear(pose, self.params.final_speed)
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
        """真机运动前只读自检：机械臂在线、无错误码、夹爪使能。plan-only 跳过。"""
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
