#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
右腕相机（right_wrist_0）eye-in-hand 手眼标定驱动脚本。

目标：解出 T_end_right_to_camera_rightwrist（右腕相机在右臂末端坐标系下的位姿）。
跟头部相机那两轮（run_eye_to_hand_calibration[_left].py）方法完全不同：这次
标定板要固定不动放在环境里（不是绑在夹爪上），移动右臂让右腕相机从不同角度看
固定的标定板。

前提条件（缺一不可）：
  1. 棋盘格标定板牢固固定在桌面/支架上，标定过程中绝对不能挪动。
  2. WRIST_CAMERA_SERIAL 还没确认——机器人上另外两个RealSense序列号
     （405622073249 / 335522072194）哪个是右腕、哪个是左腕，需要现场用
     每个序列号各起一次相机拍张照确认（比如晃动右臂夹爪，看哪个相机画面里
     跟着动，就是 right_wrist_0）。确认后把下面的占位值替换掉。
  3. RIGHT_POSES_DEG 需要用 pose_reader.py 遥操右臂 + 看右腕相机画面采集，
     保证标定板在每个姿态下都能被右腕相机看到（近景，姿态范围跟头部相机那轮
     完全不同，不能沿用）。

用法:
  python3 scripts/run_eye_in_hand_calibration_right.py
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

TARGET_ARM = "right"

# !! 占位值：现场确认右腕相机的真实序列号后替换 !!
WRIST_CAMERA_SERIAL = "405622073249"  # 已实测确认：right_wrist_0

# 标定板参数——跟头部相机那两轮一致（同一块板子）
BOARD_TYPE = "chessboard"
CHESSBOARD_CORNERS = (6, 9)
CHESSBOARD_SQUARE_LENGTH = 0.024

# !! 占位值：必须用 pose_reader.py 现场采集，替换成右腕相机能看到标定板的右臂姿态 !!
RIGHT_POSES_DEG = [
    # [j1, j2, j3, j4, j5, j6, j7],
]


def main():
    if WRIST_CAMERA_SERIAL.startswith("REPLACE_ME"):
        print("[FATAL] WRIST_CAMERA_SERIAL 还是占位值，先现场确认右腕相机真实序列号。")
        sys.exit(1)
    if len(RIGHT_POSES_DEG) < 5:
        print("[FATAL] RIGHT_POSES_DEG 里的姿态不够（至少5组）。")
        print("        先用 pose_reader.py 遥操右臂 + 看右腕相机画面，采集标定板可见的姿态。")
        sys.exit(1)

    app_config = load_config()
    conn_config = dataclasses.replace(app_config.connections, active_arm=TARGET_ARM)

    print(f"=== 启动右腕相机 ({WRIST_CAMERA_SERIAL}) ===")
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
        T_end_to_camera = calibrator.run_calibration_process(RIGHT_POSES_DEG)

        if T_end_to_camera is None:
            print("\n标定失败，请检查标定板是否在各姿态下都被右腕相机看到。")
            return

        print("\n" + "=" * 60)
        print("标定成功。这是 T_end_right_to_camera_rightwrist，抄进 config.yaml：")
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
