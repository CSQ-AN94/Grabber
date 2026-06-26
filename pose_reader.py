#!/usr/bin/env python3
"""
实时位姿读取工具 — 用遥控手柄移动机械臂时查看当前坐标

用法:
  python3 pose_reader.py [ARM_IP [PORT]]
  默认 IP: 169.254.128.19  PORT: 8080

操作方式:
  - 用遥控手柄正常操作机械臂
  - 本脚本持续打印末端位姿（不停 atom，不干扰遥控）
  - 把臂移到目标位置后，记下 Cartesian 坐标，用于 grasp_demo.py
  - 按 Ctrl+C 退出

坐标系说明（Realman 基座坐标系）:
  X  →  机器人正前方
  Y  →  机器人左侧
  Z  →  正上方
  rx/ry/rz → ZYX 欧拉角（弧度），末端姿态
"""

import sys
import time

try:
    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e
except ImportError:
    print("[FATAL] pip install robotic-arm")
    sys.exit(1)

IP   = sys.argv[1] if len(sys.argv) > 1 else "169.254.128.19"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8080

print(f"\n=== 实时位姿读取  {IP}:{PORT} ===")
print("atom 保持运行，正常遥控机械臂即可\n")
print(f"{'关节角 (deg)':^70}  {'末端位姿 [x,y,z,rx,ry,rz] (m/rad)':^60}")
print("-" * 140)

arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
handle = arm.rm_create_robot_arm(IP, PORT)
if handle.id == -1:
    print("[FATAL] 连接失败，请检查 IP/PORT")
    sys.exit(1)

try:
    while True:
        # 读关节角
        c1, joints = arm.rm_get_joint_degree()
        # 读末端位姿
        c2, state  = arm.rm_get_current_arm_state()

        j_str = "ERR" if c1 != 0 else str([round(j, 1) for j in joints])

        if c2 == 0 and isinstance(state, dict):
            pose = state.get("pose") or state.get("Pose") or state.get("arm_pose")
            if pose:
                p = [round(v, 4) for v in pose]
                p_str = f"[{p[0]:.4f}, {p[1]:.4f}, {p[2]:.4f},  {p[3]:.4f}, {p[4]:.4f}, {p[5]:.4f}]"
            else:
                p_str = f"keys={list(state.keys())}"
        else:
            p_str = f"ERR code={c2}  state={state}"

        print(f"\r{j_str:<70}  {p_str:<60}", end="", flush=True)
        time.sleep(0.3)

except KeyboardInterrupt:
    print("\n\n退出。记录的坐标可直接用于 grasp_demo.py")
finally:
    arm.rm_delete_robot_arm()
