"""
头部舵机测试脚本
运行环境：机器人本机（需要 /dev/ttyUSB0 或 /dev/rmUSB3）
协议：舵机总线 0x55 0x55 帧格式

注意：本脚本不执行 init_head_pose，不会自动回中。
     先读当前角度，再交互式让你选择是否移动。

当前工程代码里的假设：
  ID=1  俯仰（Pitch）：抬头/低头，范围 400~600，中位 500
  ID=2  偏航（Yaw） ：左转/右转，范围 200~800，中位 500

如果抬头/低头看不出来，本脚本可以用 1+/1-/2+/2- 直接测试
每个舵机 ID。重点看“实际变化”是否跟目标变化一致。
"""

import serial
import time
import sys

PORT = "/dev/rmUSB3"   # 机器人上这个别名通常指向头部舵机；也可改成 /dev/ttyUSB0
BAUDRATE = 9600
TIMEOUT = 2.0
STEP = 50

SERVO_LIMITS = {
    1: (400, 600),   # pitch
    2: (200, 800),   # yaw
}


def read_angles(ser: serial.Serial):
    """发送读角度指令，返回 ({id: angle}, raw_response_hex)"""
    cmd = bytes([0x55, 0x55, 0x05, 0x15, 0x02, 0x01, 0x02])
    ser.reset_input_buffer()
    ser.write(cmd)
    resp = ser.read(11)
    if len(resp) != 11 or resp[0] != 0x55 or resp[1] != 0x55:
        raise RuntimeError(f"读角度失败，收到: {resp.hex()}")

    id1 = resp[5]
    angle1 = (resp[7] << 8) | resp[6]
    id2 = resp[8]
    angle2 = (resp[10] << 8) | resp[9]
    return {id1: angle1, id2: angle2}, resp.hex(" ")


def read_one_angle(ser: serial.Serial, servo_id: int):
    """只读单个舵机 ID。返回 (angle, raw_hex)，无响应时 angle 为 None。"""
    cmd = bytes([0x55, 0x55, 0x04, 0x15, 0x01, servo_id])
    ser.reset_input_buffer()
    ser.write(cmd)
    time.sleep(0.04)
    resp = ser.read(16)
    if not resp:
        return None, ""
    if len(resp) >= 8 and resp[0] == 0x55 and resp[1] == 0x55 and resp[5] == servo_id:
        return (resp[7] << 8) | resp[6], resp.hex(" ")
    return None, resp.hex(" ")


def scan_servo_ids(ser: serial.Serial, max_id: int = 15):
    print(f"  扫描 ID 0~{max_id}（只读，不移动）")
    found = []
    for servo_id in range(max_id + 1):
        angle, raw = read_one_angle(ser, servo_id)
        if raw:
            if angle is None:
                print(f"  ID={servo_id}: raw={raw} angle=NA")
            else:
                print(f"  ID={servo_id}: raw={raw} angle={angle}")
                found.append(servo_id)
    print(f"  有效响应 ID: {found if found else '无'}")
    return found


def set_angle(ser: serial.Serial, servo_id: int, angle: int, duration_ms: int = 500):
    """发送目标角度（duration_ms 为运动时间）"""
    lo, hi = SERVO_LIMITS[servo_id]
    angle = max(lo, min(hi, angle))
    cmd = [0x55, 0x55, 0x08, 0x03, 0x01,
           duration_ms & 0xFF, (duration_ms >> 8) & 0xFF,
           servo_id,
           angle & 0xFF, (angle >> 8) & 0xFF]
    ser.write(bytes(cmd))
    return angle


def print_angles(angles: dict[int, int], raw: str | None = None):
    print(f"  ID=1(疑似 pitch): {angles.get(1, 'NA')}")
    print(f"  ID=2(疑似 yaw)  : {angles.get(2, 'NA')}")
    if raw:
        print(f"  raw: {raw}")


def move_servo_delta(ser: serial.Serial, servo_id: int, delta: int):
    before, _ = read_angles(ser)
    if servo_id not in before:
        print(f"  ERROR: 没有读到 ID={servo_id}")
        return before

    start = before[servo_id]
    target = set_angle(ser, servo_id, start + delta)
    print(f"  → ID={servo_id} 目标: {start} -> {target} (delta {target - start:+d})")

    time.sleep(0.8)
    after, raw = read_angles(ser)
    actual_delta = after.get(servo_id, start) - start
    print(f"  实际读回：")
    print_angles(after, raw)
    print(f"  ID={servo_id} 实际变化: {actual_delta:+d}")

    if abs(actual_delta) < 10 and target != start:
        print("  提示：目标变了但读数几乎没变，可能是该 ID 命令没生效、舵机卡住或串口被别的进程占用。")
    elif servo_id == 1 and abs(actual_delta) >= 10:
        print("  提示：ID=1 读数确实变化。如果视觉上没看出来，多半是 pitch 幅度太小、方向假设不对，或相机实际不在这根轴上。")
    return after


def main():
    print(f"打开串口 {PORT} @ {BAUDRATE} baud ...")
    try:
        ser = serial.Serial(PORT, BAUDRATE, timeout=TIMEOUT)
    except serial.SerialException as e:
        print(f"ERROR 无法打开串口: {e}")
        print("请确认：1) 在机器人本机运行  2) /dev/rmUSB3 -> ttyUSB0 别名是否存在")
        sys.exit(1)

    time.sleep(0.2)

    # 1. 读当前角度
    try:
        angles, raw = read_angles(ser)
    except RuntimeError as e:
        print(f"ERROR 读角度失败: {e}")
        ser.close()
        sys.exit(1)

    print(f"\n当前舵机角度:")
    print_angles(angles, raw)
    print("  ID=1 限制: 400~600；ID=2 限制: 200~800；中位均为 500")

    # 2. 交互式移动
    print("\n可选操作:")
    print("  c  →  回中 (500, 500)")
    print(f"  u  →  按工程假设抬头：ID=1 +{STEP}")
    print(f"  d  →  按工程假设低头：ID=1 -{STEP}")
    print(f"  l  →  按工程假设左转：ID=2 +{STEP}")
    print(f"  r  →  按工程假设右转：ID=2 -{STEP}")
    print(f"  1+ / 1-  →  直接测试 ID=1 正/负方向 {STEP}")
    print(f"  2+ / 2-  →  直接测试 ID=2 正/负方向 {STEP}")
    print("  read →  只读当前角度")
    print("  scan →  只读扫描 ID 0~15")
    print("  q  →  退出（不动）")

    while True:
        choice = input("\n输入指令> ").strip().lower()
        if choice == "q":
            break
        elif choice == "c":
            set_angle(ser, 1, 500)
            time.sleep(0.05)
            set_angle(ser, 2, 500)
            print("  → 回中指令已发送")
            time.sleep(0.8)
            angles, raw = read_angles(ser)
            print_angles(angles, raw)
        elif choice == "u":
            angles = move_servo_delta(ser, 1, STEP)
        elif choice == "d":
            angles = move_servo_delta(ser, 1, -STEP)
        elif choice == "l":
            angles = move_servo_delta(ser, 2, STEP)
        elif choice == "r":
            angles = move_servo_delta(ser, 2, -STEP)
        elif choice == "1+":
            angles = move_servo_delta(ser, 1, STEP)
        elif choice == "1-":
            angles = move_servo_delta(ser, 1, -STEP)
        elif choice == "2+":
            angles = move_servo_delta(ser, 2, STEP)
        elif choice == "2-":
            angles = move_servo_delta(ser, 2, -STEP)
        elif choice == "read":
            angles, raw = read_angles(ser)
            print_angles(angles, raw)
        elif choice == "scan":
            scan_servo_ids(ser)
        else:
            print("  未知指令")

    ser.close()
    print("串口已关闭，测试结束。")


if __name__ == "__main__":
    main()
