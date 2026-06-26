#!/usr/bin/env python3
"""
单次抓取 Demo — 安全架构版（停遥操 → 纯 SDK → 官方重启遥操）

用法（在机器人上运行）:
  python3 grasp_demo.py [ARM_IP [PORT]]
  默认 IP: 169.254.128.19  PORT: 8080

为什么是这个架构:
  atom 是双臂主从遥操（100Hz CANFD 透传）。之前用 SIGSTOP atom 插队做 SDK
  运动，会导致主从位置错位 —— SIGCONT 后高跟随(follow_mode=1)会让从臂瞬间
  跳回主臂位置，危险且可能触发保护。
  正确做法：彻底停 atom 让出控制权 → 纯 SDK 抓取 → 用官方 upstart 重启 atom
  （启动带 calibrate_speed 慢速校准，安全对齐主从）恢复遥操。

流程:
  1. 停遥操（pkill atom + zhixing_ctrl.py）
  2. SDK 连接 + 夹爪初始化
  3. 抓取序列（纯 SDK，无 SIGSTOP）
  4. SDK 断开
  5. 官方重启 atom 遥操（带校准）+ 验证
"""

import json, os, socket, subprocess, sys, time

try:
    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e
except ImportError:
    print("[FATAL] pip install robotic-arm")
    sys.exit(1)

# ── 参数（根据 pose_reader 记录填入）────────────────────────────────────
IP      = sys.argv[1] if len(sys.argv) > 1 else "169.254.128.19"
PORT    = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
LEFT_IP = "169.254.128.18"

# HOME 位置（关节角，度）
HOME_JOINTS = [-5.6, 121.6, 50.4, 8.2, 165.8, -6.1, 51.0]

# 抓取目标位姿（末端，[x,y,z,rx,ry,rz]，m/rad）
GRASP_POSE     = [0.086, 0.124, -0.310, 2.179, 1.197, -1.720]
PRE_GRASP_POSE = [GRASP_POSE[0], GRASP_POSE[1], GRASP_POSE[2] + 0.10,
                  GRASP_POSE[3], GRASP_POSE[4], GRASP_POSE[5]]

SPEED_JOINT = 25
SPEED_CART  = 25
SPEED_PRESS = 10

# 官方遥操启动脚本
UPSTART_SH  = "/home/rm/rmc_aida_l_atom/upstart_all.sh"
SUDO_PASS   = "rm"

# ────────────────────────────────────────────────────────────────────
def sh(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout.strip()

def find_pids(name, flag="-x"):
    out = sh(f"pgrep {flag} {name}")
    return [int(p) for p in out.split()] if out else []

def raw_req(cmd, ip=None, timeout=3.0):
    try:
        s = socket.socket(); s.settimeout(timeout)
        s.connect((ip or IP, PORT))
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
    return {}

def check(ret, label):
    if ret != 0:
        print(f"  [FAIL] {label} → {ret}")
        return False
    print(f"  [OK]   {label}")
    return True

# ── 遥操停止 / 重启 ──────────────────────────────────────────────────
def stop_teleop():
    """彻底停掉 atom + zhixing_ctrl，让出 CANFD 控制权给 SDK。"""
    print("\n[停遥操] pkill atom + zhixing_ctrl.py ...")
    atom = find_pids("atom", "-x")
    grip = find_pids("zhixing_ctrl.py", "-f")
    print(f"  当前 atom={atom}  zhixing={grip}")
    sh("pkill -x atom"); time.sleep(0.5)
    sh("pkill -f zhixing_ctrl.py"); time.sleep(1.0)
    print(f"  停止后 atom={find_pids('atom','-x') or '无'}")

def restart_teleop():
    """用官方 upstart 重启遥操（带 calibrate 慢速校准，安全恢复）。"""
    print("\n[重启遥操] 触发官方 upstart_all.sh（带校准）...")
    # 清理任何残留
    sh("pkill -x atom"); sh("pkill -f zhixing_ctrl.py"); time.sleep(1)
    # 预存 sudo 凭证（脚本里 udevadm 需要）
    sh(f"echo {SUDO_PASS} | sudo -S -v")
    # 在图形会话 :0 上启动官方脚本（gnome-terminal 标签页）
    env = (f"DISPLAY=:0 XAUTHORITY=/home/rm/.Xauthority")
    subprocess.Popen(
        f"{env} setsid bash -c 'bash {UPSTART_SH}' "
        f"< /dev/null > /home/rm/upstart_grasp.log 2>&1 &",
        shell=True)
    # 等待 atom 起来
    print("  等待 atom 启动（官方流程含 IP 检测+校准，约 20-40s）...")
    for i in range(15):
        time.sleep(4)
        pid = find_pids("atom", "-x")
        if pid:
            print(f"  [{(i+1)*4}s] atom 已启动 PID={pid}")
            break
    else:
        print("  [WARN] atom 未在预期时间内启动，检查 /home/rm/upstart_grasp.log")
        return False
    # 验证双臂
    time.sleep(3)
    ok = True
    for ip, lab in [(LEFT_IP, "左臂"), (IP, "右臂")]:
        r = raw_req({"command": "get_current_arm_state"}, ip=ip)
        err = r.get("arm_state", {}).get("err", "?")
        print(f"  {lab}: err={err}")
        if err != [0]: ok = False
    return ok

# ────────────────────────────────────────────────────────────────────
def main():
    print(f"\n=== Grasp Demo (安全架构)  {IP}:{PORT} ===")
    print(f"  HOME      : {HOME_JOINTS}")
    print(f"  PRE_GRASP : {PRE_GRASP_POSE}")
    print(f"  GRASP     : {GRASP_POSE}")

    # [1] 停遥操
    stop_teleop()

    # [2] SDK 连接
    print("\n[1] SDK 连接 ...")
    arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
    handle = arm.rm_create_robot_arm(IP, PORT)
    if handle.id == -1:
        print("[FATAL] SDK 连接失败")
        restart_teleop()
        sys.exit(1)
    print(f"  连接成功 DOF={arm.arm_dof}")

    grasp_ok = False
    try:
        # [3] 夹爪初始化
        print("\n[2] 夹爪初始化（上电 + 全开）...")
        arm.rm_set_tool_voltage(3); time.sleep(0.5)
        arm.rm_set_rm_plus_mode(115200); time.sleep(0.3)
        arm.rm_set_gripper_position(1000, True, 5)
        print("  夹爪已全开")

        arm.rm_clear_system_err()

        # [4] 抓取序列（纯 SDK）
        print("\n[3] 回 HOME ...")
        if not check(arm.rm_movej(HOME_JOINTS, SPEED_JOINT, 0, 0, 1), "movej HOME"):
            return

        print(f"\n[4] movej_p → 预抓取 {PRE_GRASP_POSE} ...")
        if not check(arm.rm_movej_p(PRE_GRASP_POSE, SPEED_CART, 0, 0, 1), "movej_p PRE_GRASP"):
            return
        time.sleep(0.5)

        print(f"\n[5] movel → 抓取位姿 {GRASP_POSE}（speed={SPEED_PRESS}%）...")
        if not check(arm.rm_movel(GRASP_POSE, SPEED_PRESS, 0, 0, 1), "movel GRASP"):
            return
        time.sleep(0.3)

        print("\n[6] 夹爪夹紧 ...")
        arm.rm_set_gripper_position(0, True, 8)
        time.sleep(0.5)

        print(f"\n[7] movel → 抬起 {PRE_GRASP_POSE} ...")
        if not check(arm.rm_movel(PRE_GRASP_POSE, SPEED_PRESS, 0, 0, 1), "movel LIFT"):
            return
        time.sleep(0.5)

        print("\n[8] 回 HOME ...")
        check(arm.rm_movej(HOME_JOINTS, SPEED_JOINT, 0, 0, 1), "movej HOME (final)")
        grasp_ok = True
        print("\n✓ 抓取序列完成")

    except Exception as e:
        print(f"\n[ERROR] {e}")
    finally:
        # [5] 断 SDK → 官方重启遥操
        arm.rm_delete_robot_arm()
        time.sleep(0.5)
        restored = restart_teleop()
        print()
        if restored:
            print("✓ 遥操已恢复（官方校准启动），可以正常遥操了")
        else:
            print("✗ 遥操恢复异常，手动恢复：")
            print("  在 Mac 运行: python3 \"/Users/siqi.cai/Embodied AI/teleop_restore.py\"")
            print("  或重启机器人")
        print(f"\n抓取结果: {'成功' if grasp_ok else '未完成'}")

if __name__ == "__main__":
    main()
