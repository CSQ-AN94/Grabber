#!/usr/bin/env python3
"""
Realman RM75 SDK 全功能测试 (dual-arm-sdk branch)
依赖: pip install robotic-arm

用法:
  python sdk_demo.py [ARM_IP [PORT]]
  默认 IP: 192.168.1.18  PORT: 8080

测试流程:
  1. SDK 连接
  2. 逐轴测试 J1-J7，每轴 +10°，验证后回原位
  3. 夹爪测试：上电 → 全闭 → 全开
  4. 断开

注意:
  - SDK 关节角单位为度（不是毫度）
  - rm_set_arm_run_mode 在 SDK 里是 0=仿真/1=实体，不是 tcp_demo 里的模式切换
    → 不调用 rm_set_arm_run_mode，SIGSTOP atom 已足够
"""

import os
import signal
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
    """返回所有匹配的 PID 列表。"""
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
# 关节运动辅助
# ---------------------------------------------------------------------------

def movej_and_verify(arm: RoboticArm, target: list, atom_pids: list,
                     label: str, speed: int = 20) -> bool:
    """SIGSTOP atom → 清错 → movej → 验证 → SIGCONT。返回是否成功。"""
    pause_all(atom_pids, "atom")
    arm.rm_clear_system_err()
    ret = arm.rm_movej(target, speed, 0, 0, 1)   # block=1
    code, joints_now = arm.rm_get_joint_degree()
    resume_all(atom_pids, "atom")

    if ret != 0:
        print(f"  [FAIL] {label}: rm_movej 返回 {ret}")
        return False
    if code != 0:
        print(f"  [WARN] {label}: 读角失败，错误码 {code}")
        return True
    errs = [round(joints_now[i] - target[i], 2) for i in range(len(target))]
    max_err = max(abs(e) for e in errs)
    print(f"  {label}: 实际={[round(j, 2) for j in joints_now]}  "
          f"误差={errs}  max={max_err:.2f}°  {'OK' if max_err < 2 else 'LARGE!'}")
    return True


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
    # [2] 读当前关节角（基准）
    # -----------------------------------------------------------------------
    print("\n[2] 读基准关节角 ...")
    code, origin = arm.rm_get_joint_degree()
    if code != 0:
        print(f"  [ERROR] 读角失败，错误码: {code}")
        arm.rm_delete_robot_arm()
        sys.exit(1)
    print(f"  基准角 (deg): {[round(j, 2) for j in origin]}")

    # -----------------------------------------------------------------------
    # [3] 逐轴测试 J1-J7，每轴 +10°，验证后回原位
    # -----------------------------------------------------------------------
    print(f"\n[3] 逐轴测试（各 +10°，speed=20%）")
    # J2 已接近上限（~121°），其余轴 +10°，J2 用 -10°
    DELTA = 10.0
    deltas = [DELTA if i != 1 else -DELTA for i in range(len(origin))]

    for i in range(len(origin)):
        target = list(origin)
        target[i] += deltas[i]
        print(f"\n  --- J{i+1} ---")
        d = deltas[i]
        print(f"  目标: J{i+1} {origin[i]:.2f}° → {target[i]:.2f}°  (offset {d:+.0f}°)")
        ok = movej_and_verify(arm, target, atom_pids, f"J{i+1}{d:+.0f}°")
        if not ok:
            print(f"  [SKIP] J{i+1} 失败，跳过回原位")
            continue

        # 回原位
        time.sleep(1)
        movej_and_verify(arm, list(origin), atom_pids, f"J{i+1} 回原位")
        time.sleep(0.5)

    # -----------------------------------------------------------------------
    # [4] 夹爪测试
    # -----------------------------------------------------------------------
    print("\n[4] 夹爪测试（Realman Plus）")
    print("  上电 + 初始化协议 ...")
    pause_all(gripper_pids, "zhixing_ctrl")

    ret_v = arm.rm_set_tool_voltage(3)           # 24V
    print(f"  rm_set_tool_voltage(3=24V) → {ret_v}")
    time.sleep(0.5)

    ret_m = arm.rm_set_rm_plus_mode(115200)      # 启用 Realman Plus
    print(f"  rm_set_rm_plus_mode(115200) → {ret_m}")
    time.sleep(0.3)

    print("  全开 (position=1000) ...")
    ret_o1 = arm.rm_set_gripper_position(1000, True, 5)
    print(f"  rm_set_gripper_position(1000, block=True, timeout=5) → {ret_o1}")
    time.sleep(2)

    print("  半闭 (position=500) ...")
    ret_h = arm.rm_set_gripper_position(500, True, 5)
    print(f"  rm_set_gripper_position(500, block=True, timeout=5) → {ret_h}")
    time.sleep(2)

    print("  全闭 (position=0) ...")
    ret_c = arm.rm_set_gripper_position(0, True, 8)
    print(f"  rm_set_gripper_position(0, block=True, timeout=8) → {ret_c}")
    time.sleep(2)

    print("  全开 (position=1000) ...")
    ret_o2 = arm.rm_set_gripper_position(1000, True, 5)
    print(f"  rm_set_gripper_position(1000, block=True, timeout=5) → {ret_o2}")
    time.sleep(2)

    resume_all(gripper_pids, "zhixing_ctrl")

    # -----------------------------------------------------------------------
    # [5] 断开
    # -----------------------------------------------------------------------
    print("\n[5] 断开 SDK 连接 ...")
    arm.rm_delete_robot_arm()
    print("  Done.\n")


if __name__ == "__main__":
    main()
