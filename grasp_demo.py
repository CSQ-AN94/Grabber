#!/usr/bin/env python3
"""
单次抓取 Demo — 给定坐标测试完整抓取流程

用法:
  python3 grasp_demo.py [ARM_IP [PORT]]
  默认 IP: 169.254.128.19  PORT: 8080

流程:
  1. 连接 SDK，初始化夹爪
  2. 回 HOME（关节角）
  3. 张开夹爪
  4. movej_p → 预抓取位姿（目标上方 10cm）
  5. movel   → 抓取位姿（慢速直线下压）
  6. 夹爪收紧
  7. movel   → 抬起（回预抓取高度）
  8. movej   → 回 HOME
"""

import os, signal, subprocess, sys, time
from typing import List, Optional
import json, socket

try:
    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e
except ImportError:
    print("[FATAL] pip install robotic-arm")
    sys.exit(1)

# ── 参数（根据 pose_reader 记录填入）────────────────────────────────────
IP   = sys.argv[1] if len(sys.argv) > 1 else "169.254.128.19"
PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 8080

# HOME 位置（关节角，度）
HOME_JOINTS = [-5.6, 121.6, 50.4, 8.2, 165.8, -6.1, 51.0]

# 抓取目标位姿（末端，[x,y,z,rx,ry,rz]，单位 m/rad）
GRASP_POSE     = [0.086, 0.124, -0.310, 2.179, 1.197, -1.720]

# 预抓取：与抓取位姿相同，但 Z 抬高 10cm（从正上方接近）
PRE_GRASP_POSE = [GRASP_POSE[0], GRASP_POSE[1], GRASP_POSE[2] + 0.10,
                  GRASP_POSE[3], GRASP_POSE[4], GRASP_POSE[5]]

SPEED_JOINT  = 25   # 关节运动速度 %
SPEED_CART   = 25   # 笛卡尔运动速度 %（到预抓取）
SPEED_PRESS  = 10   # 下压速度 %（慢，安全）

# ────────────────────────────────────────────────────────────────────
def find_pids(name, flag="-x"):
    try:
        r = subprocess.run(["pgrep", flag, name], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return [int(p) for p in r.stdout.strip().split()]
    except Exception:
        pass
    return []

def pause_all(pids, name=""):
    for pid in pids: os.kill(pid, signal.SIGSTOP)
    if pids: print(f"  [SIGSTOP] {name} {pids}")

def resume_all(pids, name=""):
    for pid in pids: os.kill(pid, signal.SIGCONT)
    if pids: print(f"  [SIGCONT] {name} {pids}")

def raw_req(cmd, timeout=3.0):
    try:
        s = socket.socket(); s.settimeout(timeout)
        s.connect((IP, PORT))
        s.sendall((json.dumps(cmd) + "\r\n").encode())
        buf = b""
        try:
            while True:
                c = s.recv(4096)
                if not c: break
                buf += c
                if b"\r\n" in buf: break
        except: pass
        s.close()
        for line in buf.split(b"\r\n"):
            if line.strip():
                try: return json.loads(line)
                except: pass
    except: pass
    return None

def check(ret, label):
    if ret != 0:
        print(f"  [FAIL] {label} → {ret}")
        return False
    print(f"  [OK]   {label}")
    return True

# ────────────────────────────────────────────────────────────────────
def main():
    print(f"\n=== Grasp Demo  {IP}:{PORT} ===")
    print(f"  HOME        : {HOME_JOINTS}")
    print(f"  PRE_GRASP   : {PRE_GRASP_POSE}")
    print(f"  GRASP       : {GRASP_POSE}\n")

    atom_pids    = find_pids("atom",            "-x")
    gripper_pids = find_pids("zhixing_ctrl.py", "-f")
    print(f"atom PIDs: {atom_pids}  gripper PIDs: {gripper_pids}")

    # ── 连接 ──
    print("\n[1] SDK 连接 ...")
    pause_all(atom_pids, "atom")
    arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
    handle = arm.rm_create_robot_arm(IP, PORT)
    resume_all(atom_pids, "atom")
    if handle.id == -1:
        print("[FATAL] 连接失败"); sys.exit(1)
    print(f"  连接成功 DOF={arm.arm_dof}")

    # ── 夹爪初始化 ──
    print("\n[2] 夹爪初始化（上电 + 全开）...")
    pause_all(gripper_pids, "zhixing_ctrl")
    arm.rm_set_tool_voltage(3)
    time.sleep(0.5)
    arm.rm_set_rm_plus_mode(115200)
    time.sleep(0.3)
    arm.rm_set_gripper_position(1000, True, 5)
    resume_all(gripper_pids, "zhixing_ctrl")
    print("  夹爪已全开")

    # ── 整段运动：atom 停住 ──
    pause_all(atom_pids, "atom")
    arm.rm_clear_system_err()

    try:
        # 步骤3：回 HOME
        print("\n[3] 回 HOME（关节角）...")
        if not check(arm.rm_movej(HOME_JOINTS, SPEED_JOINT, 0, 0, 1), "movej HOME"):
            return

        # 步骤4：夹爪张开（确保全开）
        print("\n[4] 夹爪张开 ...")
        pause_all(gripper_pids, "zhixing_ctrl")
        arm.rm_set_gripper_position(1000, True, 5)
        resume_all(gripper_pids, "zhixing_ctrl")

        # 步骤5：移到预抓取位姿
        print(f"\n[5] movej_p → 预抓取位姿 {PRE_GRASP_POSE} ...")
        if not check(arm.rm_movej_p(PRE_GRASP_POSE, SPEED_CART, 0, 0, 1), "movej_p PRE_GRASP"):
            return
        time.sleep(0.5)

        # 步骤6：直线下压到抓取位姿
        print(f"\n[6] movel → 抓取位姿 {GRASP_POSE}（speed={SPEED_PRESS}%）...")
        if not check(arm.rm_movel(GRASP_POSE, SPEED_PRESS, 0, 0, 1), "movel GRASP"):
            return
        time.sleep(0.3)

        # 步骤7：夹紧
        print("\n[7] 夹爪夹紧 ...")
        pause_all(gripper_pids, "zhixing_ctrl")
        arm.rm_set_gripper_position(0, True, 8)
        resume_all(gripper_pids, "zhixing_ctrl")
        time.sleep(0.5)

        # 步骤8：直线抬起
        print(f"\n[8] movel → 抬起 {PRE_GRASP_POSE} ...")
        if not check(arm.rm_movel(PRE_GRASP_POSE, SPEED_PRESS, 0, 0, 1), "movel LIFT"):
            return
        time.sleep(0.5)

        # 步骤9：回 HOME
        print("\n[9] 回 HOME ...")
        check(arm.rm_movej(HOME_JOINTS, SPEED_JOINT, 0, 0, 1), "movej HOME (final)")

        print("\n✓ 抓取序列完成")

    except Exception as e:
        print(f"\n[ERROR] {e}")
    finally:
        resume_all(atom_pids, "atom")
        arm.rm_delete_robot_arm()          # 先断 SDK 连接
        time.sleep(0.3)                    # 等端口完全释放
        raw_req({"command": "set_arm_run_mode", "mode": 1})  # 再恢复遥控模式
        print("  SDK 断开，遥控已恢复")

if __name__ == "__main__":
    main()
