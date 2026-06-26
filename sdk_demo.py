#!/usr/bin/env python3
"""
Realman RM75 SDK 全功能测试 (dual-arm-sdk branch)
依赖: pip install robotic-arm

用法:
  python sdk_demo.py [ARM_IP [PORT]]
  默认 IP: 192.168.1.18  PORT: 8080

测试流程:
  1. SDK 连接
  2. 逐轴测试 J1-J7（atom 整段停住，与 tcp_demo 一致）
  3. 夹爪测试：上电 → 全开 → 半闭 → 全闭 → 全开
  4. 断开

关键说明:
  - SDK 关节角单位为度（不是毫度）
  - atom 整段 SIGSTOP，避免每次 SIGCONT 后 CANFD 抢控造成粘滞感
  - 序列结束后通过原生 TCP 发 set_arm_run_mode mode=1 恢复遥控
    （SDK 的 rm_set_arm_run_mode 含义不同：0=仿真/1=实体）
"""

import json
import os
import signal
import socket
import subprocess
import sys
import time
from typing import List, Optional

try:
    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e
except ImportError:
    print("[FATAL] 未找到 Robotic_Arm 模块，请先运行: pip install robotic-arm")
    sys.exit(1)


# ---------------------------------------------------------------------------
# 进程控制（支持同名多 PID）
# ---------------------------------------------------------------------------

def find_pids(name: str, flag: str = "-x") -> List[int]:
    try:
        r = subprocess.run(["pgrep", flag, name], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.strip():
            return [int(p) for p in r.stdout.strip().split()]
    except Exception:
        pass
    return []


def pause_all(pids: List[int], name: str = "") -> None:
    for pid in pids:
        os.kill(pid, signal.SIGSTOP)
    if pids:
        print(f"  [SIGSTOP] {name} PIDs={pids}")


def resume_all(pids: List[int], name: str = "") -> None:
    for pid in pids:
        os.kill(pid, signal.SIGCONT)
    if pids:
        print(f"  [SIGCONT] {name} PIDs={pids}")


# ---------------------------------------------------------------------------
# 原生 TCP 单次请求（用于发 set_arm_run_mode，SDK 无等效接口）
# ---------------------------------------------------------------------------

def _raw_req(ip: str, port: int, cmd: dict, timeout: float = 3.0) -> Optional[dict]:
    try:
        s = socket.socket()
        s.settimeout(timeout)
        s.connect((ip, port))
        s.sendall((json.dumps(cmd) + "\r\n").encode())
        buf = b""
        try:
            while True:
                c = s.recv(4096)
                if not c:
                    break
                buf += c
                if b"\r\n" in buf:
                    break
        except Exception:
            pass
        s.close()
        for line in buf.split(b"\r\n"):
            if line.strip():
                try:
                    return json.loads(line)
                except Exception:
                    pass
    except Exception as e:
        print(f"  [raw_req] {e}")
    return None


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    ip   = sys.argv[1] if len(sys.argv) > 1 else "192.168.1.18"
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
    print(f"\n=== Realman SDK 全功能 Demo  {ip}:{port} ===\n")

    atom_pids    = find_pids("atom",            "-x")
    gripper_pids = find_pids("zhixing_ctrl.py", "-f")
    print(f"atom PIDs        : {atom_pids    or '未找到'}")
    print(f"zhixing_ctrl PIDs: {gripper_pids or '未找到'}")

    # -----------------------------------------------------------------------
    # [1] SDK 连接
    # -----------------------------------------------------------------------
    print("\n[1] 建立 SDK 连接 ...")
    pause_all(atom_pids, "atom")
    arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
    handle = arm.rm_create_robot_arm(ip, port)
    resume_all(atom_pids, "atom")

    if handle.id == -1:
        print("[FATAL] SDK 连接失败")
        sys.exit(1)
    print(f"  连接成功  handle.id={handle.id}  DOF={arm.arm_dof}")

    # -----------------------------------------------------------------------
    # [2] 读基准关节角
    # -----------------------------------------------------------------------
    print("\n[2] 读基准关节角 ...")
    code, origin = arm.rm_get_joint_degree()
    if code != 0:
        print(f"  [ERROR] 读角失败，错误码: {code}")
        arm.rm_delete_robot_arm()
        sys.exit(1)
    print(f"  基准角 (deg): {[round(j, 2) for j in origin]}")

    # -----------------------------------------------------------------------
    # [3] 逐轴测试 J1-J7（atom 整段停住，速度与 tcp_demo 一致）
    # -----------------------------------------------------------------------
    SPEED = 35
    DELTA = 10.0
    # J2 已接近上限（~121°），用 -10°；其余 +10°
    deltas = [DELTA if i != 1 else -DELTA for i in range(len(origin))]

    print(f"\n[3] 逐轴测试（各±10°，speed={SPEED}%，atom 整段暂停）")
    pause_all(atom_pids, "atom")
    arm.rm_clear_system_err()

    try:
        for i in range(len(origin)):
            d = deltas[i]
            target = list(origin)
            target[i] += d
            print(f"\n  --- J{i+1} ---")
            print(f"  目标: J{i+1} {origin[i]:.2f}° → {target[i]:.2f}°  ({d:+.0f}°)")

            ret = arm.rm_movej(target, SPEED, 0, 0, 1)
            code, joints_now = arm.rm_get_joint_degree()
            if ret != 0:
                print(f"  [FAIL] rm_movej 返回 {ret}")
            elif code == 0:
                errs = [round(joints_now[k] - target[k], 2) for k in range(len(target))]
                max_e = max(abs(e) for e in errs)
                print(f"  到达: {[round(j, 2) for j in joints_now]}"
                      f"  误差={errs}  max={max_e:.2f}°  {'OK' if max_e < 2 else 'LARGE!'}")

            time.sleep(1)

            arm.rm_movej(list(origin), SPEED, 0, 0, 1)
            code2, joints_back = arm.rm_get_joint_degree()
            if code2 == 0:
                err0 = round(joints_back[i] - origin[i], 2)
                print(f"  归位: J{i+1}={joints_back[i]:.2f}°  误差={err0:+.2f}°")
            time.sleep(0.5)

    finally:
        resume_all(atom_pids, "atom")
        arm.rm_delete_robot_arm()
        time.sleep(0.3)
        _raw_req(ip, port, {"command": "set_arm_run_mode", "mode": 1})
        print("  set_arm_run_mode mode=1 (遥控模式已恢复)")

    # -----------------------------------------------------------------------
    # [4] 夹爪测试
    # -----------------------------------------------------------------------
    print("\n[4] 夹爪测试（Realman Plus）")
    pause_all(gripper_pids, "zhixing_ctrl")
    try:
        ret_v = arm.rm_set_tool_voltage(3)
        print(f"  rm_set_tool_voltage(3=24V) → {ret_v}")
        time.sleep(0.5)

        ret_m = arm.rm_set_rm_plus_mode(115200)
        print(f"  rm_set_rm_plus_mode(115200) → {ret_m}")
        time.sleep(0.3)

        for label, pos, t in [("全开", 1000, 5), ("半闭", 500, 5),
                               ("全闭", 0, 8),   ("全开", 1000, 5)]:
            ret = arm.rm_set_gripper_position(pos, True, t)
            print(f"  {label} (pos={pos}, timeout={t}s) → {ret}")
            time.sleep(2)
    finally:
        resume_all(gripper_pids, "zhixing_ctrl")

    print("  Done.\n")


if __name__ == "__main__":
    main()
