#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量采集标定姿态的交互式命令行工具 —— 现场直接操作，不用来回问答。

图像来源二选一：
  - 不传 --camera-serial：从 head_camera_control.py 的 /snapshot.jpg 取头部图像。
  - 传 --camera-serial：严格打开指定的腕部RealSense，并使用它的真实内参。
  - 只读连接机械臂（不经过 ArmController），不碰遥操/头部舵机，可以放心跟
    拖动示教（长按末端绿色按钮）同时使用。

操作方式：
  1. 头部模式看浏览器画面；腕部模式配合 --display 看机器人桌面窗口
  2. 长按末端绿色按钮，把手臂拖到标定板清晰入镜的姿态，松开按钮停稳
  3. 回到终端按 Enter：脚本自动读关节角 + 取一帧验证标定板能否被检测到
     - 检测成功：记录这组姿态，追加保存到 --out 文件
     - 检测失败：提示重新调整，再按一次 Enter 重试（不会自动跳过）
  4. 集够 --target 组后自动退出，或随时输入 q 提前结束
  5. 结束时打印可以直接粘贴进 CALIBRATION_POSES_DEG 的格式

用法:
  python3 scripts/collect_calibration_poses.py [ARM_IP] [--out collected_poses.json] [--target 13]
  DISPLAY=:0 python3 scripts/collect_calibration_poses.py 169.254.128.19 \
    --camera-serial 405622073249 --board-type charuco --display \
    --square 0.030 --marker 0.0225 --squares-x 12 --squares-y 9 \
    --out right_wrist_poses.json --target 13
  默认 ARM_IP: 169.254.128.19（右臂）
"""

import argparse
import json
import os
import sys
import time
import urllib.request

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import cv2

try:
    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e
except ImportError:
    print("[FATAL] pip install robotic-arm")
    sys.exit(1)

from utils.handeye_calibrator import HandEyeCalibrator

SNAPSHOT_URL = "http://127.0.0.1:8765/snapshot.jpg"

# 近似内参，只用于头部采集阶段"能不能检测到标定板"的预检查，不影响最终标定精度
# ——真正的 run_eye_to_hand_calibration.py 会用 CameraThread 读到的真实内参重新解算。
APPROX_K = np.array([[609.3, 0, 316.1], [0, 609.7, 247.6], [0, 0, 1]], dtype=np.float64)
APPROX_DIST = np.zeros(5)


def fetch_snapshot(camera_thread=None, snapshot_url=SNAPSHOT_URL):
    if camera_thread is not None:
        return camera_thread.get_latest_frames()[0]
    try:
        with urllib.request.urlopen(snapshot_url, timeout=3) as resp:
            data = resp.read()
        arr = np.frombuffer(data, dtype=np.uint8)
        return cv2.imdecode(arr, cv2.IMREAD_COLOR)
    except Exception as e:
        print(f"  [WARN] 取图失败({e})，确认 head_camera_control.py 是否还在跑")
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("arm_ip", nargs="?", default="169.254.128.19")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--out", default="collected_poses.json")
    parser.add_argument("--target", type=int, default=13)
    parser.add_argument("--corners", default="6,9", help="内角点 列,行")
    parser.add_argument("--square", type=float, default=0.024, help="方格边长(米)")
    parser.add_argument("--board-type", choices=["chessboard", "charuco"], default="chessboard")
    parser.add_argument("--camera-serial", help="直接打开指定RealSense；腕部标定时使用")
    parser.add_argument(
        "--snapshot-url", default=SNAPSHOT_URL,
        help="从无界面相机服务读取图像；用于在本地终端经SSH采集腕部姿态",
    )
    parser.add_argument("--width", type=int, default=640)
    parser.add_argument("--height", type=int, default=480)
    parser.add_argument("--fps", type=int, default=30)
    parser.add_argument("--display", action="store_true", help="在机器人桌面显示实时腕部画面")
    parser.add_argument("--squares-x", type=int, default=12, help="ChArUco横向方格数")
    parser.add_argument("--squares-y", type=int, default=9, help="ChArUco纵向方格数")
    parser.add_argument("--marker", type=float, default=0.0225, help="ChArUco marker边长(米)")
    parser.add_argument("--min-charuco-corners", type=int, default=12)
    args = parser.parse_args()

    cols, rows = (int(x) for x in args.corners.split(","))
    calibrator = HandEyeCalibrator(
        None, None, board_type=args.board_type,
        chessboard_corners=(cols, rows), chessboard_square_length=args.square,
        squares_x=args.squares_x, squares_y=args.squares_y,
        square_length=args.square, marker_length=args.marker,
        min_charuco_corners=args.min_charuco_corners,
        max_reprojection_error_px=2.0 if args.camera_serial else None,
    )

    camera_thread = None
    if args.camera_serial:
        from sensors.camera_thread import CameraThread, DisplayMode

        print(f"=== 严格启动RealSense {args.camera_serial} ===")
        camera_thread = CameraThread(
            serial=args.camera_serial,
            width=args.width,
            height=args.height,
            fps=args.fps,
            strict_serial=True,
        )
        if not camera_thread.initialization_successful:
            print("[FATAL] 指定相机初始化失败")
            sys.exit(1)
        camera_thread.start()
        time.sleep(3)
        calibrator.camera_matrix, calibrator.dist_coeffs = camera_thread.get_camera_intrinsics()
        if args.display:
            camera_thread.start_display(DisplayMode.COLOR)
    else:
        calibrator.camera_matrix = APPROX_K
        calibrator.dist_coeffs = APPROX_DIST

    print(f"=== 只读连接机械臂 {args.arm_ip}:{args.port}（不影响遥操/拖动示教）===")
    arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
    handle = arm.rm_create_robot_arm(args.arm_ip, args.port)
    if handle.id == -1:
        print("[FATAL] 连接失败")
        if camera_thread is not None:
            camera_thread.stop()
            camera_thread.join(timeout=3)
        sys.exit(1)

    poses = []
    if os.path.exists(args.out):
        with open(args.out) as f:
            poses = json.load(f)
        print(f"已从 {args.out} 加载 {len(poses)} 组已有姿态，继续累加")

    print(f"\n目标采集 {args.target} 组。拖到合适姿态后回车确认，输入 q 结束。\n")

    try:
        while len(poses) < args.target:
            raw = input(f"[{len(poses)}/{args.target}] 按Enter采集，q结束: ").strip().lower()
            if raw == "q":
                break

            code, joints_deg = arm.rm_get_joint_degree()
            if code != 0:
                print(f"  读关节角失败，错误码 {code}，重试")
                continue
            joints_deg = [round(float(j), 2) for j in joints_deg[:7]]

            img = fetch_snapshot(camera_thread, args.snapshot_url)
            if img is None:
                continue

            T = calibrator._find_pattern_in_image(img)
            if T is None:
                print(f"  ✗ 标定板未检测到（当前关节角 {joints_deg}），调整后重试")
                continue

            poses.append(joints_deg)
            with open(args.out, "w") as f:
                json.dump(poses, f, indent=2, ensure_ascii=False)
            print(f"  ✓ 采集成功 [{len(poses)}/{args.target}]: {joints_deg}")

    finally:
        arm.rm_delete_robot_arm()
        if camera_thread is not None:
            camera_thread.stop()
            camera_thread.join(timeout=3)

    print(f"\n=== 共采集 {len(poses)} 组，已保存到 {args.out} ===")
    print("姿态JSON可直接传给对应的 run_eye_in_hand_calibration_*.py --poses：")
    for p in poses:
        print(f"    {p},")


if __name__ == "__main__":
    main()
