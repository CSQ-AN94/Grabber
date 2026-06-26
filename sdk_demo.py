#!/usr/bin/env python3
"""
Realman RM75 SDK 全功能测试 (dual-arm-sdk branch)
依赖: pip install robotic-arm  （系统 Python: /usr/bin/python3）

用法:
  python3 sdk_demo.py           # 默认：双臂都测
  python3 sdk_demo.py left      # 仅左臂
  python3 sdk_demo.py right     # 仅右臂

测试流程:
  1. atom 整段 SIGSTOP → 依次测左/右臂 J1-J7 → SIGCONT
  2. 夹爪测试（右臂，zhixing_ctrl 整段 SIGSTOP）

关键说明:
  - SDK 关节角单位为度（不是毫度）
  - J2 方向自适应：正值（右臂~121°）用 -10°，负值（左臂~-120°）用 +10°
  - 最外层 finally 统一断开 SDK + 恢复遥控模式
"""

import json, os, signal, socket, subprocess, sys, time
from typing import List, Optional

try:
    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e
except ImportError:
    print("[FATAL] 未找到 Robotic_Arm 模块，请先运行: pip install robotic-arm")
    sys.exit(1)

LEFT_IP    = "169.254.128.18"
RIGHT_IP   = "169.254.128.19"
PORT       = 8080
SPEED      = 35
DELTA      = 10.0
GRIPPER_IP = RIGHT_IP   # 夹爪在右臂


# ---------------------------------------------------------------------------
# 进程控制
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
# 原生 TCP（发 set_arm_run_mode，SDK 无等效接口）
# ---------------------------------------------------------------------------

def _raw_req(ip: str, cmd: dict, timeout: float = 3.0) -> Optional[dict]:
    try:
        s = socket.socket(); s.settimeout(timeout); s.connect((ip, PORT))
        s.sendall((json.dumps(cmd) + "\r\n").encode())
        buf = b""
        try:
            while True:
                c = s.recv(4096)
                if not c: break
                buf += c
                if b"\r\n" in buf: break
        except Exception:
            pass
        s.close()
        for line in buf.split(b"\r\n"):
            if line.strip():
                try: return json.loads(line)
                except Exception: pass
    except Exception as e:
        print(f"  [raw_req {ip}] {e}")
    return None


# ---------------------------------------------------------------------------
# 单臂关节测试（在 atom 已 SIGSTOP 的前提下调用）
# ---------------------------------------------------------------------------

def test_arm_joints(ip: str, label: str) -> bool:
    print(f"\n{'─'*50}")
    print(f"  {label}  ({ip})")
    print(f"{'─'*50}")

    arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
    handle = arm.rm_create_robot_arm(ip, PORT)
    if handle.id == -1:
        print(f"  [FAIL] SDK 连接失败 {ip}")
        return False

    print(f"  连接成功  DOF={arm.arm_dof}")
    code, origin = arm.rm_get_joint_degree()
    if code != 0:
        print(f"  [ERROR] 读角失败 code={code}")
        arm.rm_delete_robot_arm()
        return False

    print(f"  基准角 (deg): {[round(j, 2) for j in origin]}")
    arm.rm_clear_system_err()

    # J2 方向：正值接近上限 → -10°；负值接近下限 → +10°
    deltas = [DELTA if i != 1 else (-DELTA if origin[1] > 0 else DELTA)
              for i in range(len(origin))]

    ok = True
    for i in range(len(origin)):
        d = deltas[i]
        target = list(origin); target[i] += d
        print(f"\n  --- J{i+1} ---")
        print(f"  目标: J{i+1} {origin[i]:.2f}° → {target[i]:.2f}°  ({d:+.0f}°)")

        ret = arm.rm_movej(target, SPEED, 0, 0, 1)
        code2, joints_now = arm.rm_get_joint_degree()
        if ret != 0:
            print(f"  [FAIL] rm_movej 返回 {ret}")
            ok = False
        elif code2 == 0:
            errs = [round(joints_now[k] - target[k], 2) for k in range(len(target))]
            max_e = max(abs(e) for e in errs)
            status = "OK" if max_e < 2 else "LARGE!"
            print(f"  到达: {[round(j, 2) for j in joints_now]}  max_err={max_e:.2f}°  {status}")
            if max_e >= 2: ok = False

        time.sleep(1)

        arm.rm_movej(list(origin), SPEED, 0, 0, 1)
        code3, joints_back = arm.rm_get_joint_degree()
        if code3 == 0:
            err0 = round(joints_back[i] - origin[i], 2)
            print(f"  归位: J{i+1}={joints_back[i]:.2f}°  误差={err0:+.2f}°")
        time.sleep(0.5)

    arm.rm_delete_robot_arm()
    time.sleep(0.3)
    return ok


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main():
    arg = sys.argv[1].lower() if len(sys.argv) > 1 else "both"
    if arg == "left":
        arms_to_test = [(LEFT_IP,  "左臂")]
        do_gripper   = False
    elif arg == "right":
        arms_to_test = [(RIGHT_IP, "右臂")]
        do_gripper   = True
    else:
        arms_to_test = [(LEFT_IP, "左臂"), (RIGHT_IP, "右臂")]
        do_gripper   = True

    print(f"\n=== Realman SDK 双臂 Demo  目标={'&'.join(l for _,l in arms_to_test)} ===\n")

    atom_pids    = find_pids("atom",            "-x")
    gripper_pids = find_pids("zhixing_ctrl.py", "-f")
    print(f"atom PIDs        : {atom_pids    or '未找到'}")
    print(f"zhixing_ctrl PIDs: {gripper_pids or '未找到'}")

    # ── 关节测试（atom 整段 SIGSTOP，一次停住测完所有臂）─────────────────
    print("\n[关节测试] atom 整段暂停 →")
    pause_all(atom_pids, "atom")
    joint_results = {}
    try:
        for ip, label in arms_to_test:
            joint_results[label] = test_arm_joints(ip, label)
    finally:
        resume_all(atom_pids, "atom")
        # 恢复所有被测臂的遥控模式
        for ip, _ in arms_to_test:
            _raw_req(ip, {"command": "set_arm_run_mode", "mode": 1})
        print("  set_arm_run_mode mode=1 → 双臂遥控模式已恢复")

    # ── 夹爪测试（右臂，zhixing_ctrl 整段 SIGSTOP）──────────────────────
    if do_gripper:
        print(f"\n[夹爪测试] 右臂 {GRIPPER_IP}")
        arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
        handle = arm.rm_create_robot_arm(GRIPPER_IP, PORT)
        if handle.id == -1:
            print("  [FAIL] 夹爪臂 SDK 连接失败")
        else:
            pause_all(gripper_pids, "zhixing_ctrl")
            try:
                ret_v = arm.rm_set_tool_voltage(3)
                print(f"  rm_set_tool_voltage(3=24V)   → {ret_v}")
                time.sleep(0.5)
                ret_m = arm.rm_set_rm_plus_mode(115200)
                print(f"  rm_set_rm_plus_mode(115200)  → {ret_m}")
                time.sleep(0.3)
                for label, pos, t in [("全闭", 0, 8), ("半开", 500, 5),
                                       ("全闭",  0, 8), ("全开", 1000, 5),
                                       ("全闭",  0, 8)]:
                    ret = arm.rm_set_gripper_position(pos, True, t)
                    print(f"  {label} pos={pos:4d}  timeout={t}s  → {ret}")
                    time.sleep(2)
            finally:
                resume_all(gripper_pids, "zhixing_ctrl")
                arm.rm_delete_robot_arm()

    # ── 汇总 ─────────────────────────────────────────────────────────────
    print("\n" + "="*50)
    print("  汇总")
    print("="*50)
    for label, ok in joint_results.items():
        print(f"  {label} 关节测试: {'✓ OK' if ok else '✗ 有失败'}")
    if do_gripper:
        print(f"  夹爪测试: ✓ 完成（详见上方输出）")
    print()


if __name__ == "__main__":
    main()
