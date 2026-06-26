#!/usr/bin/env python3
"""
左臂单次抓取 Demo — 安全架构版（停遥操 → 纯 SDK → 官方重启遥操）

用法（在机器人上运行）:
  python3 grasp_demo_left.py [ARM_IP [PORT]]
  默认 IP: 169.254.128.18  PORT: 8080

重要:
  本文件是左臂专用版本。左臂和右臂的 HOME / 抓取位姿不能混用。
  第一次使用前，请先用:

    python3 pose_reader.py 169.254.128.18

  记录左臂 HOME_JOINTS 和 GRASP_POSE，然后把 LEFT_POSES_VERIFIED 改成 True。

流程:
  1. 检查左臂位姿是否已标定
  2. 停遥操（pkill atom + zhixing_ctrl.py）
  3. SDK 连接 + 夹爪通信初始化
  4. 抓取序列（纯 SDK，无 SIGSTOP）
  5. SDK 断开
  6. 官方重启 atom 遥操（带校准）+ 验证
"""

import json, socket, subprocess, sys, time

try:
    from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e
except ImportError:
    print("[FATAL] pip install robotic-arm")
    sys.exit(1)

# ── 左臂参数（根据 pose_reader 记录填入）──────────────────────────────
ARM_LABEL = "左臂"
IP       = sys.argv[1] if len(sys.argv) > 1 else "169.254.128.18"
PORT     = int(sys.argv[2]) if len(sys.argv) > 2 else 8080
RIGHT_IP = "169.254.128.19"

# 改成 True 前，必须确认下面两个位姿是左臂实测值。
LEFT_POSES_VERIFIED = False

# TODO: 用 pose_reader.py 169.254.128.18 记录左臂 HOME 关节角（度）。
HOME_JOINTS = []

# TODO: 用 pose_reader.py 169.254.128.18 记录左臂抓取目标末端位姿
#       [x, y, z, rx, ry, rz]，单位 m/rad。
GRASP_POSE = []
PRE_GRASP_Z_OFFSET = 0.10

SPEED_JOINT = 25
SPEED_CART  = 25
SPEED_PRESS = 10

GRIPPER_OPEN_POS = 1000
GRIPPER_CLOSE_POS = 0
GRIPPER_DEFAULT_SETTLE = 2.0

# 官方遥操启动脚本
UPSTART_SH = "/home/rm/rmc_aida_l_atom/upstart_all.sh"
SUDO_PASS  = "rm"


def pre_grasp_pose():
    return [GRASP_POSE[0], GRASP_POSE[1], GRASP_POSE[2] + PRE_GRASP_Z_OFFSET,
            GRASP_POSE[3], GRASP_POSE[4], GRASP_POSE[5]]


def validate_pose_config():
    if not LEFT_POSES_VERIFIED:
        print("[FATAL] 左臂 HOME_JOINTS / GRASP_POSE 还没有确认。")
        print("  请先在机器人上运行: python3 pose_reader.py 169.254.128.18")
        print("  记录左臂 HOME_JOINTS 和 GRASP_POSE 后，把 LEFT_POSES_VERIFIED 改成 True。")
        return False
    if len(HOME_JOINTS) != 7:
        print(f"[FATAL] HOME_JOINTS 需要 7 个关节角，当前 len={len(HOME_JOINTS)}")
        return False
    if len(GRASP_POSE) != 6:
        print(f"[FATAL] GRASP_POSE 需要 6 个末端位姿值，当前 len={len(GRASP_POSE)}")
        return False
    return True


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
        except Exception:
            pass
        s.close()
        for line in buf.split(b"\r\n"):
            if line.strip():
                try: return json.loads(line)
                except Exception: pass
    except Exception:
        pass
    return {}


def check(ret, label):
    if ret != 0:
        print(f"  [FAIL] {label} → {ret}")
        return False
    print(f"  [OK]   {label}")
    return True


def set_default_closed(arm, label, already_closed_ok=False):
    """下发默认闭合姿态；不用阻塞等待，避免已闭合时 SDK 等待状态超时。"""
    ret = arm.rm_set_gripper_position(GRIPPER_CLOSE_POS, False, 5)
    if ret == 0:
        print(f"  [OK]   {label}")
    elif already_closed_ok and ret in (1, -4):
        print(f"  [OK]   {label}（已是默认闭合态 ret={ret}）")
    else:
        print(f"  [FAIL] {label} → {ret}")
        return False
    time.sleep(GRIPPER_DEFAULT_SETTLE)
    return True


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
    sh("pkill -x atom"); sh("pkill -f zhixing_ctrl.py"); time.sleep(1)
    sh(f"echo {SUDO_PASS} | sudo -S -v")
    env = "DISPLAY=:0 XAUTHORITY=/home/rm/.Xauthority"
    subprocess.Popen(
        f"{env} setsid bash -c 'bash {UPSTART_SH}' "
        f"< /dev/null > /home/rm/upstart_grasp_left.log 2>&1 &",
        shell=True)

    print("  等待 atom 启动（官方流程含 IP 检测+校准，约 20-40s）...")
    for i in range(15):
        time.sleep(4)
        pid = find_pids("atom", "-x")
        if pid:
            print(f"  [{(i+1)*4}s] atom 已启动 PID={pid}")
            break
    else:
        print("  [WARN] atom 未在预期时间内启动，检查 /home/rm/upstart_grasp_left.log")
        return False

    time.sleep(3)
    ok = True
    for ip, lab in [(IP, ARM_LABEL), (RIGHT_IP, "右臂")]:
        r = raw_req({"command": "get_current_arm_state"}, ip=ip)
        err = r.get("arm_state", {}).get("err", "?")
        print(f"  {lab}: err={err}")
        if err != [0]: ok = False
    return ok


def main():
    if not validate_pose_config():
        sys.exit(1)

    pre_pose = pre_grasp_pose()

    print(f"\n=== Left Grasp Demo (安全架构)  {IP}:{PORT} ===")
    print(f"  HOME      : {HOME_JOINTS}")
    print(f"  PRE_GRASP : {pre_pose}")
    print(f"  GRASP     : {GRASP_POSE}")

    stop_teleop()

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
        print("\n[2] 夹爪通信初始化（上电 + 协议）...")
        arm.rm_set_tool_voltage(3); time.sleep(0.5)
        arm.rm_set_rm_plus_mode(115200); time.sleep(0.3)
        print("  夹爪通信已就绪")

        print("\n[3] 夹爪闭合（恢复默认）...")
        if not set_default_closed(arm, "gripper CLOSE (default)", already_closed_ok=True):
            return

        arm.rm_clear_system_err()

        print("\n[4] 回 HOME ...")
        if not check(arm.rm_movej(HOME_JOINTS, SPEED_JOINT, 0, 0, 1), "movej HOME"):
            return

        print(f"\n[5] movej_p → 预抓取 {pre_pose} ...")
        if not check(arm.rm_movej_p(pre_pose, SPEED_CART, 0, 0, 1), "movej_p PRE_GRASP"):
            return
        time.sleep(0.5)

        print("\n[6] 夹爪打开（抓取前）...")
        if not check(arm.rm_set_gripper_position(GRIPPER_OPEN_POS, True, 5), "gripper OPEN"):
            return
        time.sleep(0.3)

        print(f"\n[7] movel → 抓取位姿 {GRASP_POSE}（speed={SPEED_PRESS}%）...")
        if not check(arm.rm_movel(GRASP_POSE, SPEED_PRESS, 0, 0, 1), "movel GRASP"):
            return
        time.sleep(0.3)

        print("\n[8] 夹爪夹紧 ...")
        if not check(arm.rm_set_gripper_position(GRIPPER_CLOSE_POS, True, 8), "gripper CLOSE"):
            return
        time.sleep(0.5)

        print(f"\n[9] movel → 抬起 {pre_pose} ...")
        if not check(arm.rm_movel(pre_pose, SPEED_PRESS, 0, 0, 1), "movel LIFT"):
            return
        time.sleep(0.5)

        print("\n[10] 回 HOME ...")
        if not check(arm.rm_movej(HOME_JOINTS, SPEED_JOINT, 0, 0, 1), "movej HOME (final)"):
            return

        print("\n[11] 夹爪松开（释放物体）...")
        r = arm.rm_set_gripper_position(GRIPPER_OPEN_POS, True, 5)
        print(f"  夹爪已全开" if r == 0 else f"  [WARN] 夹爪松开失败 ret={r}")
        time.sleep(0.3)

        print("\n[12] 夹爪闭合（恢复默认）...")
        if not set_default_closed(arm, "gripper CLOSE (default final)"):
            return

        grasp_ok = True
        print("\n✓ 左臂抓取序列完成")

    except Exception as e:
        print(f"\n[ERROR] {e}")
    finally:
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
        print(f"\n左臂抓取结果: {'成功' if grasp_ok else '未完成'}")


if __name__ == "__main__":
    main()
