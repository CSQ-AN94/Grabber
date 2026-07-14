#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
头部相机（base_0）eye-to-hand 手眼标定驱动脚本 —— 右臂版本。

目标：解出 T_base_right_to_camera_head（头部相机在右臂基座坐标系下的位姿）。
本脚本明确强制用右臂（TARGET_ARM），不依赖 config.yaml 里的 active_arm 设置，
避免以后有人改了 config 默认臂导致这个脚本悄悄标错手臂。

前提条件（缺一不可）：
  1. 棋盘格标定板（普通黑白方格，无marker；CHESSBOARD_CORNERS/CHESSBOARD_SQUARE_LENGTH
     需要现场数准/量准后确认）已经固定装在【右臂】夹爪上（不是像 eye-in-hand
     流程那样固定在环境里）。棋盘格不像ChArUco能容忍部分遮挡，每次拍照必须完整
     看到所有内角点。
  2. 头部俯仰/旋转舵机已经摆到一个固定角度，标定期间及整次 demo（包括后面标左臂
     那一轮）都不能再动头部，否则本次标定的 T_base_to_camera 立刻失效。
  3. CALIBRATION_POSES_DEG 已经用 pose_reader.py 手动遥操 + 观察头部相机画面，
     替换成一组"标定板在相机视野里、且姿态多样"的右臂关节角度（至少5组，建议8-13组）。

用法:
  python3 scripts/run_eye_to_hand_calibration.py

流程:
  1. 启动头部相机线程
  2. 构造 ArmController（强制连右臂，会停遥操，全程 SDK 控制）
  3. 依次移动到 CALIBRATION_POSES_DEG，拍照 + 记录末端位姿
  4. 解算 T_base_right_to_camera_head，打印结果 —— 需要手动抄进 config.yaml
  5. close() 时恢复遥操
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
    """构造 ArmController 之后，务必调用这个函数：实测发现初始化机械臂SDK过程中
    head_servo_ctrl.py 有时会意外消失（具体原因未完全查清，疑似SDK初始化的某个
    调用有副作用），如果不管，头部会失去持续位置指令、角度跑偏，导致整轮
    eye-to-hand标定全部作废。这里检查+必要时手动拉起+强制恢复到基准角度。"""
    alive = subprocess.run(["pgrep", "-f", "head_servo_ctrl.py"], capture_output=True, text=True).stdout.strip()
    if not alive:
        print("[WARN] head_servo_ctrl.py 已经不在了，手动重新拉起...")
        subprocess.Popen(
            f"cd {HEAD_SERVO_LAUNCH_DIR} && {HEAD_SERVO_PYTHON} head_servo_ctrl.py "
            f"> /home/rm/head_servo_manual_restart.log 2>&1 &",
            shell=True,
        )
        time.sleep(3)

    print("=== 校验/恢复头部角度到基准值 ===")
    subprocess.run(
        ["python3", os.path.join(_SCRIPT_DIR, "head_position_lock.py"), "restore"],
        cwd=os.path.dirname(_SCRIPT_DIR),
    )

TARGET_ARM = "right"  # 本脚本固定标右臂，不读 config.yaml 的 active_arm

# 标定板参数——现在用的是普通棋盘格（无marker），不是ChArUco了。
# !! 占位值：CHESSBOARD_SQUARE_LENGTH（方格边长，米）和 CHESSBOARD_CORNERS
# （内角点 列数,行数 = 方格数-1）需要现场量准/数准后确认 !!
BOARD_TYPE = "chessboard"
CHESSBOARD_CORNERS = (6, 9)       # (内角点列数, 内角点行数)
CHESSBOARD_SQUARE_LENGTH = 0.024  # 方格边长，米（"2.4cm"待确认）

# 逐帧重投影误差过滤（像素）：单帧PnP解算的RMS重投影误差超过这个阈值就直接丢弃这一帧，
# 不让个别检测有问题的姿态污染整体标定结果。之前那次跑的时候没开这个，13组一致性很差
# 但具体是不是某一两帧检测有问题拖累了整体，当时没有办法定位。
MAX_REPROJECTION_ERROR_PX = 2.0

# 传了这个目录，每个姿态拍到的原图 + 最终解算数据都会存盘，标定失败/一致性不好时
# 可以离线复查具体是哪几组姿态有问题，不用重新跑一遍机械臂。
OUTPUT_DIR = os.path.join(_SCRIPT_DIR, "..", "outputs", "eye_to_hand_right_calibration")

# 2026-07-08 现场用 scripts/collect_calibration_poses.py 采集，13组均已验证棋盘格可检测
CALIBRATION_POSES_DEG = [
    [33.41, 101.25, 52.31, 65.18, 9.38, 20.46, -146.35],
    [46.48, 107.47, 67.84, 29.23, -2.68, 58.25, -158.25],
    [52.14, 115.25, 57.78, 27.24, 14.66, 30.82, -158.25],
    [52.13, 115.26, 57.78, 27.24, 14.66, 30.82, -158.25],
    [65.35, 115.06, 55.53, 28.66, 14.52, 30.47, -158.25],
    [74.61, 110.36, 55.24, 28.67, 13.79, 30.2, -158.25],
    [67.53, 115.88, 45.99, 22.47, 45.72, 46.72, -158.32],
    [67.53, 115.99, 41.74, 9.19, 53.84, 47.46, -158.33],
    [60.87, 116.77, 25.61, 21.78, 50.63, 60.45, -158.45],
    [60.87, 116.81, 23.9, 15.98, 61.24, 49.62, -158.45],
    [65.49, 115.1, 19.06, 15.97, 58.03, 44.6, -157.13],
    [73.5, 110.79, 18.86, 11.41, 79.86, 55.47, -158.53],
    [63.98, 109.44, 18.81, 4.63, 45.79, 79.92, -166.61],
]


def main():
    if len(CALIBRATION_POSES_DEG) < 5:
        print("[FATAL] CALIBRATION_POSES_DEG 里的姿态不够（至少5组）。")
        print("        先用 pose_reader.py 遥操 + 看头部相机画面，采集标定板可见的右臂姿态，")
        print("        再把关节角度填进这个脚本。")
        sys.exit(1)

    app_config = load_config()
    conn_config = dataclasses.replace(app_config.connections, active_arm=TARGET_ARM)

    print("=== 启动头部相机 ===")
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
            max_reprojection_error_px=MAX_REPROJECTION_ERROR_PX,
        )
        T_base_to_camera = calibrator.run_eye_to_hand_calibration(
            CALIBRATION_POSES_DEG, output_dir=OUTPUT_DIR
        )

        if T_base_to_camera is None:
            print("\n标定失败/一致性不通过。原始数据已存到")
            print(f"  {OUTPUT_DIR}")
            print("可以离线检查 samples.npz 里的 reprojection_errors_px，看是不是某几组姿态检测质量差。")
            return

        print("\n" + "=" * 60)
        print(f"标定成功。这是 T_base_{TARGET_ARM}_to_camera_head，抄进 config.yaml：")
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
