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

from .collision import check_approach_corridor
from .core import (
    DemoParams,
    Localization,
    SafetyAbort,
    interpolate_poses,
    look_at_camera_pose,
    matrix_pose,
    pose_matrix,
)
from .dashboard import Dashboard, PreviewWorker, SharedState
from .perception import BottleDetector, depth_point_for_detection
from .planner import MoveItPlanner
from .robot import ArmJointReader, RobotSession
from .safety import (
    SafetyProfile,
    load_guided_joint_path,
    load_safety_profile,
)
from .scene import build_scene_voxels

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
        self.guided_path: Optional[dict] = None
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
        self.camera = CameraThread(
            serial=serial,
            width=width,
            height=height,
            fps=self.cfg.camera.fps,
            strict_serial=True,
        )
        if not self.camera.initialization_successful:
            raise SafetyAbort(f"{camera_name} 相机初始化失败")
        self.camera.start()
        deadline = time.time() + 5
        while self.camera.get_latest_frames()[0] is None and time.time() < deadline:
            time.sleep(0.1)
        if self.camera.get_latest_frames()[0] is None:
            raise SafetyAbort(f"{camera_name} 相机无画面")
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

    def initialize(self):
        self.safety = load_safety_profile(
            self.args.safety_config,
            self.args.safety_profile,
            require_verified=self.args.execute,
        )
        self.scene_boxes = self.safety.moveit_collision_boxes()
        # --guided-path 覆盖 profile 里配置的走廊：方便现场刚录完一条
        # 『垂下→观察位』走廊直接用，不必改 profile。
        guided_override = getattr(self.args, "guided_path", None)
        if guided_override:
            self.guided_path = load_guided_joint_path(Path(guided_override))
        elif self.safety.guided_path:
            self.guided_path = load_guided_joint_path(
                self.safety.guided_path
            )
        self.stage(
            "初始化",
            (
                f"电子围栏 profile={self.safety.name}；"
                "固定头部 RGB-D 搜索水瓶"
            ),
        )
        if not self.args.resume_at_wrist:
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
        self._start_camera(
            "right_wrist" if self.args.resume_at_wrist else "head"
        )

        if self.args.plan_only or self.args.execute:
            self.robot = RobotSession(
                self.cfg.connections.right_arm_ip,
                self.cfg.connections.arm_port,
                self.stop_event,
                self.params.tcp_z_m,
                self.params.moveit_link7_to_controller_flange_m,
                take_control=self.args.execute,
            )
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

    def _guided_observation_plan(self) -> dict:
        points = self.guided_path["points_deg"]
        start = np.asarray(points[0], dtype=float)
        current = np.asarray(self.robot.joints_deg(), dtype=float)
        start_error = float(np.max(np.abs(current - start)))
        goal_error = float(
            np.max(np.abs(current - np.asarray(points[-1], dtype=float)))
        )
        entry_points = []
        if goal_error <= self.safety.guided_start_tolerance_deg:
            self.stage(
                "已在示教观察位",
                f"当前距记录终点最大 {goal_error:.3f}°，跳过全局移动",
            )
            return {
                "success": True,
                "planning_time": 0.0,
                "joint_names": [f"r_joint{i}" for i in range(1, 8)],
                "points_deg": [],
                "source": "guided_path_at_goal",
            }
        if start_error > self.safety.guided_start_tolerance_deg:
            T_start_controller_flange = (
                self.robot.controller_flange_from_joints(start.tolist())
            )
            entry = self.planner.plan(
                name="guided_entry",
                start_joints_deg=current.tolist(),
                start_left_joints_deg=self.left_robot.joints_deg(),
                goal_joints_deg=start.tolist(),
                target_flange=self.safety.pose_to_moveit(
                    T_start_controller_flange
                ),
                obstacles=self.safety.points_to_moveit(self.scene_voxels),
                boxes=self.scene_boxes,
                workspace=self.safety.moveit_workspace(),
                planning_frame=self.safety.moveit_frame,
                tool_guard={
                    "xy": self.params.tool_guard_xy_m,
                    "length": self.params.tool_guard_length_m,
                    "center_z": self.params.tool_guard_center_z_m,
                },
                voxel_size=self.params.scene_voxel_m,
            )
            entry_checked = self.robot.validate_planned_joints(
                entry["points_deg"],
                self.params.planned_joint_step_deg,
                self.safety,
            )
            entry_points = entry["points_deg"]
            self.stage(
                "示教起点接入规划",
                (
                    f"当前距起点 {start_error:.1f}°；"
                    f"MoveIt {len(entry_points)} 点，"
                    f"电子围栏 {entry_checked} 点通过"
                ),
            )
        dense = [
            points[0],
            *self.robot._dense_joint_path(
                points[0],
                points[1:],
                self.params.planned_joint_step_deg,
            ),
        ]
        checked = self.robot.validate_planned_joints(
            points,
            self.params.planned_joint_step_deg,
            self.safety,
            start_joints_deg=points[0],
        )
        validation = self.planner.validate_exact_path(
            name="guided_observation",
            start_left_joints_deg=self.left_robot.joints_deg(),
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
        self.stage(
            "示教通道检查通过",
            (
                f"记录 {len(points)} 点，密集检查 {checked} 点，"
                f"MoveIt {validation['checked_states']} 状态；"
                f"当前距起点 {start_error:.1f}°，距终点 {goal_error:.1f}°"
            ),
        )
        return {
            "success": True,
            "planning_time": 0.0,
            "joint_names": [f"r_joint{i}" for i in range(1, 8)],
            "points_deg": [*entry_points, *points],
            "source": "guided_path",
        }

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
                v = y1 + 0.48 * (y2 - y1)
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

    def _select_observation_flange(
        self, target_base: np.ndarray
    ) -> tuple[np.ndarray, list[float]]:
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
                accepted.append((score, flange, joints, index))
            except SafetyAbort as exc:
                LOG.debug("观察位候选 %d 被拒绝: %s", index, exc)
        if not accepted:
            raise SafetyAbort("所有右腕观察位候选均越界、近限位或逆解失败")
        score, flange, joints, index = min(accepted, key=lambda item: item[0])
        self.stage(
            "选择右腕观察位",
            f"候选 {index}，关节变化评分 {score:.1f}",
        )
        return flange, joints

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
        (self.run_dir / "head_scene.json").write_text(
            json.dumps(
                {
                    "safety_profile": self.safety.name,
                    "voxel_count": len(self.scene_voxels),
                    "collision_boxes": self.scene_boxes,
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

    def _refresh_wrist_scene(self, localization: Localization):
        if not self.safety.use_dynamic_rgbd:
            self.scene_voxels = []
            return
        _, depth = self.camera.get_latest_frames()
        K, _ = self.camera.get_camera_intrinsics()
        T_base_camera = self.robot.current_flange() @ self.T_flange_wrist_camera
        wrist_voxels = build_scene_voxels(
            depth,
            K,
            T_base_camera,
            localization,
            self.params,
            min_depth_m=self.params.min_depth_m,
            max_depth_m=self.params.max_depth_m,
            bottom_crop=depth.shape[0],
            max_voxels=self.params.wrist_scene_max_voxels,
        )
        voxel = self.params.scene_voxel_m
        all_points = np.asarray(
            [*self.head_scene_voxels, *wrist_voxels], dtype=float
        )
        if all_points.size == 0:
            self.scene_voxels = []
            return
        keys = np.floor(all_points / voxel).astype(np.int32)
        _, indices = np.unique(keys, axis=0, return_index=True)
        merged = all_points[np.sort(indices)]
        if len(merged) > self.params.merged_scene_max_voxels:
            target = np.asarray(localization.point_base, dtype=float)
            distance = np.linalg.norm(merged - target, axis=1)
            merged = merged[
                np.argsort(distance)[: self.params.merged_scene_max_voxels]
            ]
        self.scene_voxels = merged.tolist()
        self.stage(
            "右腕局部建图",
            (
                f"头部 {len(self.head_scene_voxels)} + "
                f"右腕 {len(wrist_voxels)}，融合后 {len(self.scene_voxels)} 体素"
            ),
        )

    def _plan_flange(
        self,
        name: str,
        target_flange: np.ndarray,
        goal_joints: Optional[list[float]] = None,
    ) -> dict:
        T_link7_controller_flange = np.eye(4)
        T_link7_controller_flange[2, 3] = (
            self.params.moveit_link7_to_controller_flange_m
        )
        target_link7 = target_flange @ np.linalg.inv(
            T_link7_controller_flange
        )
        target_moveit = self.safety.pose_to_moveit(target_link7)
        if goal_joints is None:
            goal_joints = self.robot.solve_flange_ik(
                target_flange, self.params
            )
        plan = self.planner.plan(
            name=name,
            start_joints_deg=self.robot.joints_deg(),
            start_left_joints_deg=self.left_robot.joints_deg(),
            goal_joints_deg=goal_joints,
            target_flange=target_moveit,
            obstacles=self.safety.points_to_moveit(self.scene_voxels),
            boxes=self.scene_boxes,
            workspace=self.safety.moveit_workspace(),
            planning_frame=self.safety.moveit_frame,
            tool_guard={
                "xy": self.params.tool_guard_xy_m,
                "length": self.params.tool_guard_length_m,
                "center_z": self.params.tool_guard_center_z_m,
            },
            voxel_size=self.params.scene_voxel_m,
        )
        checked = self.robot.validate_planned_joints(
            plan["points_deg"],
            self.params.planned_joint_step_deg,
            self.safety,
        )
        self.stage("电子围栏离线复核", f"{name}: {checked} 个密集 TCP 点通过")
        return plan

    def _execute_plan(
        self,
        name: str,
        plan: dict,
        max_dense_points: int | None = None,
    ) -> bool:
        self.stage(
            name,
            f"{len(plan['points_deg'])} 个 MoveIt 轨迹点，SDK {self.params.travel_speed}%",
        )
        return self.robot.execute_planned_joints(
            plan["points_deg"],
            self.params.travel_speed,
            self.params.planned_joint_step_deg,
            max_dense_points=max_dense_points,
        )

    def _move_to_pregrasp_with_active_replanning(
        self, initial: Localization
    ) -> Localization:
        current = initial
        relocalization_params = replace(
            self.params,
            samples=self.params.wrist_relocalization_samples,
            max_position_spread_m=0.035,
        )
        for cycle in range(1, self.params.pregrasp_replan_cycles + 1):
            self._refresh_wrist_scene(current)
            pregrasp_pose, _, _ = self.candidate_path(
                np.asarray(current.point_base)
            )
            subgoals = interpolate_poses(
                matrix_pose(self.robot.current_tcp()),
                pregrasp_pose,
                self.params.segment_m,
            )
            subgoal_pose = subgoals[0]
            target_flange = (
                pose_matrix(subgoal_pose) @ np.linalg.inv(self.T_flange_tcp)
            )
            plan = self._plan_flange(
                f"moveit_pregrasp_{cycle:02d}", target_flange
            )
            self.stage(
                f"预抓取子目标 {cycle}",
                (
                    f"剩余 {len(subgoals)} 段；"
                    f"本段 TCP 终点 {np.round(subgoal_pose[:3], 4).tolist()}"
                ),
            )
            self._execute_plan(f"预抓取分段 {cycle}", plan)
            if len(subgoals) == 1:
                return current
            # 分段复检只做"瓶子还在且没被大幅挪动"的确认，不覆盖初始锁定：
            # 相机逼近时瓶子下半截逐渐出画，截断视野下的定位点会沿瓶身向
            # 瓶盖方向系统性漂移（实测每段爬升1-2cm），拿它更新目标会把
            # 抓取点引到瓶盖上。初始完整视野的定位才是抓取点的权威来源。
            refined = self.localize(
                f"右腕分段复检_{cycle:02d}",
                lambda: self.robot.current_flange()
                @ self.T_flange_wrist_camera,
                relocalization_params,
                depth_prior_base=np.asarray(current.point_base),
            )
            jump = float(
                np.linalg.norm(
                    np.asarray(refined.point_base)
                    - np.asarray(current.point_base)
                )
            )
            if jump > self.params.max_relocalization_jump_m:
                LOG.warning(
                    "分段复检目标偏移 %.1f mm（近距视野截断伪影），"
                    "保持初始锁定目标继续",
                    jump * 1000,
                )
        raise SafetyAbort("预抓取分段重规划次数用尽，未到达目标")

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

    def ensure_bottle_visible(self):
        if self.camera.get_frame_timestamp() < time.time() - self.params.frame_timeout_s:
            raise SafetyAbort("RGB-D 画面中断")
        color, _ = self.camera.get_latest_frames()
        detector = (
            self.wrist_detector
            if self.camera_name == "right_wrist"
            else self.detector
        )
        predicate = None
        if self.camera_name == "right_wrist" and color is not None:
            shape = color.shape
            predicate = lambda det: self._plausible_close_bottle(det, shape)
        detection = None if color is None else detector.detect(color, predicate)
        if detection is None:
            raise SafetyAbort("移动过程中符合形状的 bottle 检测丢失")

    def run(self):
        if getattr(self.args, "full_cycle", False):
            return self.run_full_cycle()
        self.initialize()
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
            self.stage("打开夹爪")
            self.robot.open_gripper()
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
        if self.guided_path:
            observation_plan = self._guided_observation_plan()
        else:
            observation_flange, observation_goal_joints = (
                self._select_observation_flange(
                    np.asarray(head_target.point_base)
                )
            )
            observation_plan = self._plan_flange(
                "moveit_observation",
                observation_flange,
                observation_goal_joints,
            )
        if self.args.plan_only:
            self.stage(
                "自主规划完成",
                f"观察位轨迹 {len(observation_plan['points_deg'])} 点；未执行任何运动",
            )
            time.sleep(self.args.observe_seconds)
            return

        if observation_plan["points_deg"]:
            self._execute_plan("避障移动到右腕观察位", observation_plan)
        else:
            self.stage("保持右腕观察位", "已在示教终点，不发送运动命令")
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
        self.stage("打开夹爪")
        self.robot.open_gripper(self.params)
        self._finish_grasp_from_wrist(wrist_target)

    def _finish_grasp_from_wrist(self, wrist_target: Localization):
        """续抓/普通模式收尾：抓取抬升后按 --place-back 决定放回或保持。"""
        self._grasp_and_lift(wrist_target)
        if getattr(self.args, "place_back", False):
            self._place_back()
            self.stage("完成并保持", "已放回；STOP/Ctrl+C 结束")
        else:
            self.stage("完成并保持", "不搬运、不放置；STOP/Ctrl+C 只保持")
        while not self.stop_event.wait(0.5):
            pass

    def _grasp_and_lift(self, wrist_target: Localization) -> Localization:
        """从当前腕部姿态完成：分段接近 → 最后接近 → 力控夹取 → 抬升 5cm。

        返回锁定用的 refined 定位；不做放回、不阻塞——后续由调用方决定
        （run() 保持/放回，run_full_cycle() 放回并返回垂下姿态）。
        """
        self.stage(
            "从当前腕部姿态续抓",
            "视觉闭环、局部 MoveIt 规划和分段接近",
        )

        wrist_target = self._move_to_pregrasp_with_active_replanning(
            wrist_target
        )

        # 预抓取复检同样只做存在性确认：近距截断视野下的定位会向瓶盖漂移，
        # 最终抓取点仍以初始完整视野的锁定为准。
        refined = self.localize(
            "预抓取复检",
            lambda: self.robot.current_flange() @ self.T_flange_wrist_camera,
            self.params,
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
                self.ensure_bottle_visible()
            except SafetyAbort as exc:
                if "画面中断" in str(exc):
                    raise
                LOG.warning("最后接近中检测丢失（预期为夹爪遮挡）: %s", exc)
            self.robot.move_linear(pose, self.params.final_speed)

        self.stage("夹紧水瓶")
        gripper = self.robot.close_gripper(self.params)
        lift = self.robot.current_tcp()
        lift[2, 3] += self.params.lift_m
        lift_path = interpolate_poses(
            matrix_pose(self.robot.current_tcp()),
            matrix_pose(lift),
            self.params.segment_m,
        )
        self.robot.plan_ik(lift_path, self.params)
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
        """把瓶子放回桌面原位：放低→张开→沿接近轴反向退开（2026-07-16真机验证过的顺序）。"""
        lower = self.robot.current_tcp()
        lower[2, 3] -= self.params.lift_m
        lower_path = interpolate_poses(
            matrix_pose(self.robot.current_tcp()),
            matrix_pose(lower),
            self.params.segment_m,
        )
        self.robot.plan_ik(lower_path, self.params)
        self.stage("放回桌面", f"下降 {self.params.lift_m * 100:.0f} cm")
        for pose in lower_path:
            self.robot.move_linear(pose, self.params.final_speed)

        self.stage("松开夹爪")
        self.robot.open_gripper(self.params)

        # 沿抓取接近轴反向退开一个预抓取距离，避免手指刮倒瓶子
        tcp = self.robot.current_tcp()
        axis = tcp[:3, 2]
        retreat = tcp.copy()
        retreat[:3, 3] -= axis * self.params.pregrasp_standoff_m
        self.safety.assert_tcp_point(retreat[:3, 3], label="放回后退开点")
        retreat_path = interpolate_poses(
            matrix_pose(tcp),
            matrix_pose(retreat),
            self.params.segment_m,
        )
        self.robot.plan_ik(retreat_path, self.params)
        self.stage("退开", f"沿接近轴反向 {self.params.pregrasp_standoff_m * 100:.0f} cm")
        for pose in retreat_path:
            self.robot.move_linear(pose, self.params.final_speed)
        self.stage("放回完成", "瓶子已放回，手臂已退开")

    # ---------------- 完整循环：垂下 → 观察 → 抓取 → 放回 → 垂回 ----------------

    def _corridor_points(self) -> list[list[float]]:
        """返回示教转移走廊的关节路点（首点=垂下起始姿态，末点=观察位）。"""
        if not self.guided_path:
            raise SafetyAbort(
                "完整循环需要一条示教转移走廊，但当前没有加载到。"
                "先用 scripts/record_right_arm_guided_path.py 录一条"
                "『垂下起始 → 右腕观察位』的安全路线，再用 --guided-path 指定，"
                "或把它填进 safety profile 的 guided_path。"
            )
        return [list(map(float, p)) for p in self.guided_path["points_deg"]]

    def _assert_at_pose(self, joints_target, label: str):
        """确认右臂当前关节角在目标姿态容差内，否则中止（避免从错误起点乱走）。"""
        current = np.asarray(self.robot.joints_deg(), dtype=float)
        target = np.asarray(joints_target, dtype=float)
        error = float(np.max(np.abs(current - target)))
        if error > self.safety.guided_start_tolerance_deg:
            raise SafetyAbort(
                f"{label}：当前关节距目标最大 {error:.1f}° > 容差 "
                f"{self.safety.guided_start_tolerance_deg}°。"
                "请先把右臂拖到走廊起点（垂下姿态）附近再运行。"
            )
        self.stage(label, f"当前距目标 {error:.2f}°，在容差内")

    def _preflight(self):
        """真机运动前只读自检：机械臂在线、无错误码、夹爪使能。plan-only 跳过。"""
        if not self.args.execute:
            return
        self.robot.current_tcp()  # 内部校验 arm_err/sys_err，异常即抛
        state = self.robot.gripper_state()
        self.stage(
            "运动前自检",
            f"机械臂在线无错误码；夹爪 enable={state.get('enable_state')}",
        )

    def _execute_joint_waypoints(
        self,
        name: str,
        points_deg: list[list[float]],
        start_joints: list[float] | None = None,
    ):
        """离线电子围栏逐点复核 + SDK 执行一串关节路点（转移段专用）。

        走廊是人工示教录制的，全臂几何天然无碰撞；离线复核用密集插值 FK 逐点
        校验 TCP 是否越过桌面禁入区/工作空间，兜住"桌子挪了/走廊选错"这类粗错。
        """
        checked = self.robot.validate_planned_joints(
            points_deg,
            self.params.planned_joint_step_deg,
            self.safety,
            start_joints_deg=start_joints,
        )
        self.stage("转移离线复核", f"{name}：{checked} 个密集 TCP 点通过电子围栏")
        if not self.args.execute:
            self.stage(name, f"plan-only：{len(points_deg)} 个路点未执行")
            return
        self.robot.execute_planned_joints(
            points_deg,
            self.params.travel_speed,
            self.params.planned_joint_step_deg,
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

    def run_full_cycle(self):
        """完整一轮：垂下 → 观察位 → 抓取 → 抬升 → 放回 → 垂回垂下姿态。

        转移段（垂下↔观察位）默认用示教走廊：人工录制的安全路线，离线电子围栏
        逐点复核，环境未变时全臂安全——这是当前 MoveIt 碰撞检查失效情况下唯一
        可信的大范围转移方式。抓取段是自主视觉闭环。修好 MoveIt 碰撞后可用
        --autonomous-transit 换成全自主规划（见 docs 手册）。
        """
        self.initialize()
        self._preflight()

        corridor = self._corridor_points()
        hang_pose = corridor[0]
        observation_pose = corridor[-1]
        self.stage(
            "完整循环",
            f"走廊 {len(corridor)} 点；起始垂下姿态 J={np.round(hang_pose, 1).tolist()}",
        )

        # 1. 必须从走廊起点（垂下姿态）附近开始
        self._assert_at_pose(hang_pose, "确认起始垂下姿态")

        # 2. 头部粗定位水瓶（固定头部相机）
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
            head_target.point_base, label="头部定位的水瓶抓取点"
        )
        self._build_head_scene(head_target)

        # 3. 转移：垂下 → 观察位（示教走廊正向）
        self._execute_joint_waypoints(
            "前往观察位（示教走廊）", corridor, start_joints=hang_pose
        )
        if not self.args.execute:
            self.stage(
                "plan-only 完成",
                "已离线复核走廊+头部定位；抓取与返回段需真机 --execute 现场验证",
            )
            time.sleep(self.args.observe_seconds)
            return

        # 4. 腕部完整视野锁定抓取点
        self._start_camera("right_wrist")
        wrist_target = self.localize(
            "右腕精定位",
            lambda: self.robot.current_flange() @ self.T_flange_wrist_camera,
            self.params,
            depth_prior_base=np.asarray(head_target.point_base),
        )

        # 5. 抓取 + 抬升
        self.stage("打开夹爪")
        self.robot.open_gripper(self.params)
        self._grasp_and_lift(wrist_target)

        # 6. 放回桌面 + 退开
        self._place_back()

        # 7. 返回：先回到走廊终点（观察位），再反向走廊回垂下姿态
        self._execute_joint_waypoints("回到走廊终点（观察位）", [observation_pose])
        self._execute_joint_waypoints(
            "返回垂下姿态（示教走廊反向）",
            corridor[::-1],
            start_joints=observation_pose,
        )
        self._assert_at_pose(hang_pose, "确认已回到垂下姿态")

        self.stage("完整循环完成", "已回到垂下姿态，夹爪张开；一轮结束")
        if getattr(self.args, "restore_teleop", False):
            self._restore_teleop()

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
