#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量采集标定姿态的交互式命令行工具 —— 现场直接操作，不用来回问答。

前提：
  - head_camera_control.py 正在跑（提供 http://127.0.0.1:8765/snapshot.jpg），
    这个脚本靠它取图，不会跟它抢相机设备。
  - 只读连接机械臂（不经过 ArmController），不碰遥操/头部舵机，可以放心跟
    拖动示教（长按末端绿色按钮）同时使用。

操作方式：
  1. 浏览器开 http://192.168.3.68:8765 实时看头部相机画面
  2. 长按末端绿色按钮，把手臂拖到一个棋盘格完整入镜的姿态，松开按钮停稳
  3. 回到这个终端，按 Enter：脚本自动读关节角 + 取一帧验证棋盘格能否被检测到
     - 检测成功：记录这组姿态，追加保存到 --out 文件
     - 检测失败：提示重新调整，再按一次 Enter 重试（不会自动跳过）
  4. 集够 --target 组后自动退出，或随时输入 q 提前结束
  5. 结束时打印可以直接粘贴进 CALIBRATION_POSES_DEG 的格式

用法:
  python3 scripts/collect_calibration_poses.py [ARM_IP] [--out collected_poses.json] [--target 13]
  默认 ARM_IP: 169.254.128.19（右臂）
"""

import argparse
import json
import os
import sys
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

# 近似内参，只用于采集阶段"能不能检测到棋盘格"的预检查，不影响最终标定精度
# ——真正的 run_eye_to_hand_calibration.py 会用 CameraThread 读到的真实内参重新解算。
APPROX_K = np.array([[609.3, 0, 316.1], [0, 609.7, 247.6], [0, 0, 1]], dtype=np.float64)
APPROX_DIST = np.zeros(5)


def fetch_snapshot():
    try:
        with urllib.request.urlopen(SNAPSHOT_URL, timeout=3) as resp:
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
    args = parser.parse_args()

    cols, rows = (int(x) for x in args.corners.split(","))
    calibrator = HandEyeCalibrator(
        None, None, board_type="chessboard",
        chessboard_corners=(cols, rows), chessboard_square_length=args.square,
    )
    calibrator.camera_matrix = APPROX_K
    calibrator.dist_coeffs = APPROX_DIST

    print(f"=== 只读连接机械臂 {args.arm_ip}:{args.port}（不影响遥操/拖动示教）===")
    arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
    handle = arm.rm_create_robot_arm(args.arm_ip, args.port)
    if handle.id == -1:
        print("[FATAL] 连接失败")
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

            img = fetch_snapshot()
            if img is None:
                continue

            T = calibrator._find_pattern_in_image(img)
            if T is None:
                print(f"  ✗ 棋盘格未检测到（当前关节角 {joints_deg}），调整后重试")
                continue

            poses.append(joints_deg)
            with open(args.out, "w") as f:
                json.dump(poses, f, indent=2, ensure_ascii=False)
            print(f"  ✓ 采集成功 [{len(poses)}/{args.target}]: {joints_deg}")

    finally:
        arm.rm_delete_robot_arm()

    print(f"\n=== 共采集 {len(poses)} 组，已保存到 {args.out} ===")
    print("可以直接粘贴进 CALIBRATION_POSES_DEG:")
    for p in poses:
        print(f"    {p},")


if __name__ == "__main__":
    main()
