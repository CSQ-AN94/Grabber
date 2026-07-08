#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
标定选点辅助工具 —— 只读，不碰遥操。

用途：用拖动示教（长按末端绿色按钮）或遥操手柄把手臂移到一个候选标定姿态、
停稳后，跑这个脚本一次：读当前关节角 + 用头部相机拍一张照，方便确认棋盘格
是否入镜、姿态是否可用。不会构造 ArmController，不会碰 atom/zhixing/head_servo，
跟遥操/拖动示教完全不冲突。

用法:
  python3 scripts/capture_calibration_pose.py [ARM_IP] [--out snap.jpg]
  默认 ARM_IP: 169.254.128.19 (右臂)
"""

import argparse
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2

from utils.config import load_config

try:
    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e
except ImportError:
    print("[FATAL] pip install robotic-arm")
    sys.exit(1)

from sensors.camera_thread import CameraThread


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("arm_ip", nargs="?", default="169.254.128.19")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--out", default="/home/rm/calib_pose_snap.jpg")
    parser.add_argument("--no-camera", action="store_true", help="只读关节角，不拍照")
    args = parser.parse_args()

    print(f"=== 只读连接 {args.arm_ip}:{args.port}（不影响遥操/拖动示教）===")
    arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
    handle = arm.rm_create_robot_arm(args.arm_ip, args.port)
    if handle.id == -1:
        print("[FATAL] 连接失败")
        sys.exit(1)

    try:
        code, joints_deg = arm.rm_get_joint_degree()
        if code != 0:
            print(f"[FATAL] 读关节角失败，错误码: {code}")
            sys.exit(1)
        joints_deg = joints_deg[:7]
        print(f"当前关节角(deg): {[round(j, 2) for j in joints_deg]}")
        print(f"可直接粘贴进 CALIBRATION_POSES_DEG:\n  {[round(j, 2) for j in joints_deg]},")
    finally:
        arm.rm_delete_robot_arm()

    if args.no_camera:
        return

    app_config = load_config()
    print("=== 启动头部相机拍照 ===")
    cam = CameraThread(
        serial=app_config.camera.head_serial,
        width=app_config.camera.width,
        height=app_config.camera.height,
        fps=app_config.camera.fps,
    )
    cam.start()
    time.sleep(2)
    color, _ = cam.get_latest_frames()
    if color is not None:
        cv2.imwrite(args.out, color)
        print(f"已保存: {args.out}")
    else:
        print("[WARN] 相机取帧失败")
    cam.stop()
    cam.join(timeout=3)


if __name__ == "__main__":
    main()
