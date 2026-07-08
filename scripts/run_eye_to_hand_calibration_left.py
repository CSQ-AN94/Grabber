#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
头部相机（base_0）eye-to-hand 手眼标定驱动脚本 —— 左臂版本。

目标：解出 T_base_left_to_camera_head（头部相机在左臂基座坐标系下的位姿）。
跟 run_eye_to_hand_calibration.py（右臂版本）配合使用：两边分别解出头部相机相对
各自基座的位姿后，用 scripts/compose_dual_arm_transform.py 组合成左右臂基座之间
的相对变换，从而把两条手臂的坐标系打通。

前提条件（缺一不可，其中第2条是本轮特有的重点）：
  1. 棋盘格标定板（CHESSBOARD_CORNERS/CHESSBOARD_SQUARE_LENGTH 必须跟右臂那轮
     完全一致）已经从右臂夹爪上取下来，重新固定装到【左臂】夹爪上。
  2. **头部俯仰/旋转舵机的角度必须跟标右臂那一轮完全一样，全程没有被动过**——
     这是两轮结果能够被正确组合的前提，如果头在两轮之间动过，组合出来的左右臂
     相对变换就是错的。
  3. CALIBRATION_POSES_DEG 换成一组左臂专属的关节角度（跟右臂那轮的角度无关，
     需要重新用 pose_reader.py 遥操左臂 + 观察头部相机画面采集，至少5组）。

用法:
  python3 scripts/run_eye_to_hand_calibration_left.py
"""

import sys
import os
import time
import subprocess
import dataclasses

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from utils.config import load_config
from utils.handeye_calibrator import HandEyeCalibrator
from sensors.camera_thread import CameraThread
from controllers.arm_controller import ArmController

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
HEAD_SERVO_LAUNCH_DIR = "/home/rm/rmc_aida_l_atom/scripts"
HEAD_SERVO_PYTHON = "/home/rm/miniconda3/bin/python3"  # 需要pyserial，必须用conda python


def ensure_head_fixed() -> None:
    """构造 ArmController 之后必须调用：实测发现初始化机械臂SDK过程中
    head_servo_ctrl.py 有时会意外消失，不管的话头部会跑偏，导致这一轮
    （必须跟右臂那轮头部角度完全一致）标定作废。这里检查+必要时手动拉起+
    强制恢复到基准角度。"""
    alive = subprocess.run(["pgrep", "-f", "head_servo_ctrl.py"], capture_output=True, text=True).stdout.strip()
    if not alive:
        print("[WARN] head_servo_ctrl.py 已经不在了，手动重新拉起...")
        subprocess.Popen(
            f"cd {HEAD_SERVO_LAUNCH_DIR} && {HEAD_SERVO_PYTHON} head_servo_ctrl.py "
            f"> /home/rm/head_servo_manual_restart.log 2>&1 &",
            shell=True,
        )
        time.sleep(3)

    print("=== 校验/恢复头部角度到基准值（必须跟右臂那轮完全一致）===")
    subprocess.run(
        ["python3", os.path.join(_SCRIPT_DIR, "head_position_lock.py"), "restore"],
        cwd=os.path.dirname(_SCRIPT_DIR),
    )


TARGET_ARM = "left"  # 本脚本固定标左臂，不读 config.yaml 的 active_arm

# 标定板参数——必须跟右臂那一轮（run_eye_to_hand_calibration.py）完全一致
BOARD_TYPE = "chessboard"
CHESSBOARD_CORNERS = (6, 9)
CHESSBOARD_SQUARE_LENGTH = 0.024

# !! 占位值：必须用 pose_reader.py 现场采集，替换成真实、安全、能看到标定板的左臂姿态 !!
CALIBRATION_POSES_DEG = [
    # [j1, j2, j3, j4, j5, j6, j7],
]


def main():
    if len(CALIBRATION_POSES_DEG) < 5:
        print("[FATAL] CALIBRATION_POSES_DEG 里的姿态不够（至少5组）。")
        print("        先用 pose_reader.py 169.254.128.18 遥操左臂 + 看头部相机画面，")
        print("        采集标定板可见的左臂姿态，再把关节角度填进这个脚本。")
        sys.exit(1)

    app_config = load_config()
    conn_config = dataclasses.replace(app_config.connections, active_arm=TARGET_ARM)

    print("=== 启动头部相机（确认跟标右臂那轮时角度一致，没有被动过）===")
    camera_thread = CameraThread(
        serial=app_config.camera.head_serial,
        width=app_config.camera.width,
        height=app_config.camera.height,
        fps=app_config.camera.fps,
    )
    camera_thread.start()
    time.sleep(3)
    if camera_thread.get_latest_frames()[0] is None:
        print("[FATAL] 相机数据获取失败")
        camera_thread.stop()
        camera_thread.join(timeout=3)
        sys.exit(1)

    arm_controller = None
    try:
        print(f"=== 初始化机械臂（强制 {TARGET_ARM} 臂，会停遥操）===")
        arm_controller = ArmController(conn_config, app_config.arm, app_config.gripper)

        ensure_head_fixed()

        calibrator = HandEyeCalibrator(
            arm_controller, camera_thread,
            board_type=BOARD_TYPE,
            chessboard_corners=CHESSBOARD_CORNERS,
            chessboard_square_length=CHESSBOARD_SQUARE_LENGTH,
        )
        T_base_to_camera = calibrator.run_eye_to_hand_calibration(CALIBRATION_POSES_DEG)

        if T_base_to_camera is None:
            print("\n标定失败，请检查标定板是否在各姿态下都被相机看到。")
            return

        print("\n" + "=" * 60)
        print(f"标定成功。这是 T_base_{TARGET_ARM}_to_camera_head，抄进 config.yaml，")
        print("并留着跟右臂那轮的结果一起喂给 compose_dual_arm_transform.py：")
        print("=" * 60)
        for row in np.round(T_base_to_camera, 6).tolist():
            print(f"  - {row}")

    finally:
        if arm_controller is not None:
            arm_controller.close()
        camera_thread.stop()
        camera_thread.join(timeout=3)


if __name__ == "__main__":
    main()
