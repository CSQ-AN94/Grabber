#!/usr/bin/env python3
"""
Realman RM75 SDK 连接测试 (dual-arm-sdk branch)
依赖: pip install robotic-arm

用法:
  python sdk_demo.py [ARM_IP [PORT]]
  默认 IP: 192.168.1.18  PORT: 8080

测试流程:
  1. SIGSTOP atom（关节遥控进程）
  2. SDK 连接
  3. SIGCONT atom
  4. 读当前关节角
  5. SIGSTOP atom → 清错误 → J1 +20° → SIGCONT atom
  6. 等待 3s → 读关节角验证
  7. SIGSTOP atom → 回原位 → SIGCONT atom
  8. 断开 SDK

注意:
  - SDK 关节角单位为 度 (不是毫度)
  - rm_set_arm_run_mode 在 SDK 中含义是 0=仿真/1=实体，与 tcp_demo 的模式切换不同
    → 本 demo 不调用 rm_set_arm_run_mode，SIGSTOP atom 本身就够了
"""

import os
import signal
import subprocess
import sys
import time
from typing import Optional

try:
    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e
except ImportError:
    print("[FATAL] 未找到 Robotic_Arm 模块，请先运行: pip install robotic-arm")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 进程控制
# ---------------------------------------------------------------------------

def find_pid(name: str, flag: str = "-x") -> Optional[int]:
    """用 pgrep 查找进程 PID，找不到返回 None。"""
    try:
        r = subprocess.run(["pgrep", flag, name], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return int(r.stdout.strip().split()[0])
    except Exception:
        pass
    return None


def pause(pid: Optional[int], name: str = "") -> None:
    if pid:
        os.kill(pid, signal.SIGSTOP)
        print(f"  [SIGSTOP] {name or pid}")


def resume(pid: Optional[int], name: str = "") -> None:
    if pid:
        os.kill(pid, signal.SIGCONT)
        print(f"  [SIGCONT] {name or pid}")


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ip   = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.18"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    print(f"\n=== Realman SDK Demo  {ip}:{port} ===\n")

    # --- 找后台进程 ---
    atom_pid    = find_pid("atom",         "-x")   # 关节遥控（CANFD 100Hz）
    gripper_pid = find_pid("zhixing_ctrl.py", "-f") # 夹爪遥控
    print(f"atom PID        : {atom_pid   or '未找到（手动遥控可能未启动）'}")
    print(f"zhixing_ctrl PID: {gripper_pid or '未找到'}")

    # --- 建立 SDK 连接（SIGSTOP atom 避免连接被占用）---
    print("\n[1] 建立 SDK 连接 ...")
    pause(atom_pid, "atom")
    arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
    handle = arm.rm_create_robot_arm(ip, port)
    resume(atom_pid, "atom")

    if handle.id == -1:
        print("[FATAL] SDK 连接失败，请检查 IP / PORT 和网络。")
        sys.exit(1)

    print(f"  连接成功  handle.id={handle.id}  DOF={arm.arm_dof}")

    # --- 读当前关节角 ---
    print("\n[2] 读当前关节角 ...")
    code, joints_deg = arm.rm_get_joint_degree()
    if code != 0:
        print(f"  [ERROR] rm_get_joint_degree 失败，错误码: {code}")
        arm.rm_delete_robot_arm()
        sys.exit(1)
    print(f"  当前关节角 (deg): {[round(j, 3) for j in joints_deg]}")
    origin = list(joints_deg)

    # --- 运动：J1 +20° ---
    target = list(origin)
    target[0] += 20.0
    print(f"\n[3] SIGSTOP atom → 清错误 → movej J1+20° → SIGCONT atom")
    print(f"  目标关节角 (deg): {[round(j, 3) for j in target]}")

    pause(atom_pid, "atom")
    arm.rm_clear_system_err()
    ret = arm.rm_movej(target, 20, 0, 0, 1)   # speed=20%, block=1
    resume(atom_pid, "atom")
    print(f"  rm_movej 返回: {ret}")

    # --- 验证 ---
    time.sleep(0.5)
    code, joints_now = arm.rm_get_joint_degree()
    if code == 0:
        print(f"  运动后关节角 (deg): {[round(j, 3) for j in joints_now]}")
        delta = joints_now[0] - origin[0]
        print(f"  J1 实际偏移: {delta:+.2f}°  (期望 +20°)")
    else:
        print(f"  [WARN] 验证读角失败，错误码: {code}")

    # --- 等待 ---
    print("\n[4] 等待 3 秒后回原位 ...")
    time.sleep(3)

    # --- 回原位 ---
    print(f"\n[5] SIGSTOP atom → 回原位 → SIGCONT atom")
    print(f"  原始关节角 (deg): {[round(j, 3) for j in origin]}")

    pause(atom_pid, "atom")
    arm.rm_clear_system_err()
    ret2 = arm.rm_movej(origin, 20, 0, 0, 1)
    resume(atom_pid, "atom")
    print(f"  rm_movej 返回: {ret2}")

    # --- 断开 ---
    time.sleep(0.5)
    print("\n[6] 断开 SDK 连接 ...")
    arm.rm_delete_robot_arm()
    print("  Done.\n")


if __name__ == "__main__":
    main()
