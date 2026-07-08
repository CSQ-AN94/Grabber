#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
左腕相机（left_wrist_0）eye-in-hand 手眼标定驱动脚本。

目标：解出 T_end_left_to_camera_leftwrist（左腕相机在左臂末端坐标系下的位姿）。
跟 run_eye_in_hand_calibration_right.py 是同一种方法（eye-in-hand，标定板固定
不动放环境里），可以直接复用同一个标定板摆放位置，只是这次移动左臂。

前提条件（缺一不可）：
  1. 棋盘格标定板固定不动（可以沿用标右腕相机那一轮的摆放位置，不用重新放）。
  2. WRIST_CAMERA_SERIAL 换成左腕相机的真实序列号（跟右腕那轮是另一个序列号）。
  3. LEFT_POSES_DEG 需要用 pose_reader.py 遥操左臂 + 看左腕相机画面采集。

用法:
  python3 scripts/run_eye_in_hand_calibration_left.py
"""

import sys
import os
import time
import dataclasses

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from utils.config import load_config
from utils.handeye_calibrator import HandEyeCalibrator
from sensors.camera_thread import CameraThread
from controllers.arm_controller import ArmController

TARGET_ARM = "left"

# !! 占位值：现场确认左腕相机的真实序列号后替换（跟右腕脚本用的是另一个序列号）!!
WRIST_CAMERA_SERIAL = "335522072194"  # 已实测确认：left_wrist_0

# 标定板参数——跟其他几轮一致（同一块板子）
BOARD_TYPE = "chessboard"
CHESSBOARD_CORNERS = (6, 9)
CHESSBOARD_SQUARE_LENGTH = 0.024

# !! 占位值：必须用 pose_reader.py 现场采集，替换成左腕相机能看到标定板的左臂姿态 !!
LEFT_POSES_DEG = [
    # [j1, j2, j3, j4, j5, j6, j7],
]


def main():
    if WRIST_CAMERA_SERIAL.startswith("REPLACE_ME"):
        print("[FATAL] WRIST_CAMERA_SERIAL 还是占位值，先现场确认左腕相机真实序列号。")
        sys.exit(1)
    if len(LEFT_POSES_DEG) < 5:
        print("[FATAL] LEFT_POSES_DEG 里的姿态不够（至少5组）。")
        print("        先用 pose_reader.py 169.254.128.18 遥操左臂 + 看左腕相机画面，采集标定板可见的姿态。")
        sys.exit(1)

    app_config = load_config()
    conn_config = dataclasses.replace(app_config.connections, active_arm=TARGET_ARM)

    print(f"=== 启动左腕相机 ({WRIST_CAMERA_SERIAL}) ===")
    camera_thread = CameraThread(
        serial=WRIST_CAMERA_SERIAL,
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

        calibrator = HandEyeCalibrator(
            arm_controller, camera_thread,
            board_type=BOARD_TYPE,
            chessboard_corners=CHESSBOARD_CORNERS,
            chessboard_square_length=CHESSBOARD_SQUARE_LENGTH,
        )
        T_end_to_camera = calibrator.run_calibration_process(LEFT_POSES_DEG)

        if T_end_to_camera is None:
            print("\n标定失败，请检查标定板是否在各姿态下都被左腕相机看到。")
            return

        print("\n" + "=" * 60)
        print("标定成功。这是 T_end_left_to_camera_leftwrist，抄进 config.yaml：")
        print("=" * 60)
        for row in np.round(T_end_to_camera, 6).tolist():
            print(f"  - {row}")

    finally:
        if arm_controller is not None:
            arm_controller.close()
        camera_thread.stop()
        camera_thread.join(timeout=3)


if __name__ == "__main__":
    main()
