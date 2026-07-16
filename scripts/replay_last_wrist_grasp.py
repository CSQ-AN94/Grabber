#!/usr/bin/env python3
"""Replay the last verified wrist-camera bottle grasp from its pregrasp pose."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bottle_grasp.collision import check_approach_corridor
from bottle_grasp.core import DemoParams, Localization, SafetyAbort, interpolate_poses, matrix_pose
from bottle_grasp.robot import RobotSession
from bottle_grasp.safety import load_safety_profile
from sensors.camera_thread import CameraThread
from utils.config import load_config

LOG = logging.getLogger("replay_wrist_grasp")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default=str(ROOT / "config.yaml"))
    parser.add_argument(
        "--safety-config",
        default=str(ROOT / "bottle_grasp" / "safety_profiles.json"),
    )
    parser.add_argument("--safety-profile", default="table_demo")
    parser.add_argument(
        "--localization",
        default=str(
            ROOT
            / "outputs"
            / "bottle_grasp"
            / "20260716_003756"
            / "右腕续抓定位_localization.json"
        ),
    )
    parser.add_argument(
        "--corridor-localization",
        default=str(
            ROOT
            / "outputs"
            / "bottle_grasp"
            / "20260716_003756"
            / "预抓取复检_localization.json"
        ),
        help="same-pose wrist detection used only to mask the bottle in corridor checks",
    )
    parser.add_argument(
        "--output-dir",
        default=str(ROOT / "outputs" / "bottle_grasp_replay"),
    )
    parser.add_argument(
        "--gripper-already-open",
        action="store_true",
        help="skip the open command after an operator visually confirms it is open",
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    cfg = load_config(args.config)
    params = DemoParams()
    safety = load_safety_profile(
        args.safety_config,
        args.safety_profile,
        require_verified=True,
    )
    localization = Localization(
        **json.loads(Path(args.localization).read_text(encoding="utf-8"))
    )
    corridor_localization = Localization(
        **json.loads(
            Path(args.corridor_localization).read_text(encoding="utf-8")
        )
    )
    target = np.asarray(localization.point_base, dtype=float)
    output_dir = Path(args.output_dir) / time.strftime("%Y%m%d_%H%M%S")
    output_dir.mkdir(parents=True, exist_ok=True)
    stop_event = threading.Event()
    signal.signal(signal.SIGINT, lambda *_: stop_event.set())
    signal.signal(signal.SIGTERM, lambda *_: stop_event.set())

    camera = CameraThread(
        serial=cfg.camera.right_wrist_serial,
        width=cfg.camera.width,
        height=cfg.camera.height,
        fps=cfg.camera.fps,
        strict_serial=True,
    )
    if not camera.initialization_successful:
        raise SafetyAbort("右腕相机初始化失败")
    camera.start()
    deadline = time.time() + 5.0
    color = depth = None
    while time.time() < deadline:
        color, depth = camera.get_latest_frames()
        if color is not None and depth is not None:
            break
        time.sleep(0.1)
    if color is None or depth is None:
        raise SafetyAbort("右腕 RGB-D 无新画面")
    cv2.imwrite(str(output_dir / "before_grasp.jpg"), color)

    robot = RobotSession(
        cfg.connections.right_arm_ip,
        cfg.connections.arm_port,
        stop_event,
        params.tcp_z_m,
        params.moveit_link7_to_controller_flange_m,
        take_control=True,
    )
    try:
        current = robot.current_tcp()
        vector = target - current[:3, 3]
        distance = float(np.linalg.norm(vector))
        if not 0.070 <= distance <= 0.100:
            raise SafetyAbort(
                f"当前不在已验证预抓取位: 距锁定点 {distance * 1000:.1f} mm"
            )
        alignment = float(vector @ current[:3, 2] / distance)
        if alignment < 0.98:
            raise SafetyAbort(
                f"当前接近轴与成功轨迹不一致: alignment={alignment:.3f}"
            )

        grasp = current.copy()
        grasp[:3, 3] = target
        grasp_pose = matrix_pose(grasp)
        approach_path = interpolate_poses(
            matrix_pose(current), grasp_pose, params.segment_m
        )
        lift = grasp.copy()
        lift[2, 3] += params.lift_m
        lift_path = interpolate_poses(
            grasp_pose, matrix_pose(lift), params.segment_m
        )
        safety.assert_tcp_path(
            [pose[:3] for pose in [*approach_path, *lift_path]]
        )
        robot.plan_ik([*approach_path, *lift_path], params)

        blockers = check_approach_corridor(
            camera=camera,
            robot=robot,
            localization=corridor_localization,
            target_base=target,
            T_flange_camera=np.asarray(
                cfg.calibration.T_end_right_to_camera_rightwrist,
                dtype=float,
            ),
            params=params,
        )
        LOG.info(
            "重放检查通过: 距离 %.1f mm, 轴对齐 %.3f, 通道障碍点 %d",
            distance * 1000,
            alignment,
            blockers,
        )

        if args.gripper_already_open:
            LOG.info("现场已确认夹爪打开，跳过重复打开命令")
        else:
            robot.open_gripper(params)
        LOG.info("低速重放最后接近")
        for pose in approach_path:
            robot.move_linear(pose, params.final_speed)

        LOG.info("RM Plus 内部力限幅夹紧并验证物体宽度")
        gripper = robot.close_gripper(params)
        LOG.info("夹爪状态: %s", gripper)

        LOG.info("抬升 5 cm")
        for pose in lift_path:
            robot.move_linear(pose, params.final_speed)

        result = {
            "target": target.tolist(),
            "final_tcp": matrix_pose(robot.current_tcp()),
            "gripper": gripper,
        }
        (output_dir / "success.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        LOG.info("抓取完成并保持；Ctrl+C 仅停止保持")
        while not stop_event.wait(0.5):
            pass
        return 0
    finally:
        robot.hold()
        robot.close()
        camera.stop()
        if camera.is_alive():
            camera.join(timeout=3)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SafetyAbort as exc:
        LOG.error("安全中止: %s", exc)
        raise SystemExit(2)
