#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
头部舵机位置锁定/校验工具 —— 配合头部相机(base_0) eye-to-hand 标定使用。

背景：eye-to-hand 标定要求头部俯仰(angle1)/偏航(angle2)舵机在整个标定过程
（含标右臂、标左臂两轮）中绝对不能变，否则标定结果失效。这个脚本记录了
本次标定开始前实测的基准角度，并提供读取当前角度、判断是否漂移、以及在
漂移时自动微调回基准值的功能（复用 /home/rm/test/test_head_udp.py 同一套
UDP 协议，但改成每个轴独立收敛到自己的目标值，而不是原脚本 center() 那样
两轴共用同一个目标）。

用法:
  python3 scripts/head_position_lock.py check     # 只读当前角度，对比基准值
  python3 scripts/head_position_lock.py restore    # 如果偏了，自动微调回基准值
"""

import argparse
import json
import select
import socket
import sys
import time

BROADCAST_IP = "169.254.128.255"
CONTROL_PORT = 19999
ANGLE_PORT = 9996

HEAD_CTRL_IO = 5
UP_IO, DOWN_IO, LEFT_IO, RIGHT_IO = 6, 7, 8, 9

# !! 本次标定会话实测基准值（2026-07-08，用户手动摆好：左右居中、俯仰最低）!!
# 后续每一轮标定前用 `check` 核对，如果漂移用 `restore` 校正回这个值。
HEAD_REFERENCE = {"angle1": 398, "angle2": 516}
TOLERANCE = 5  # 允许的读数误差（舵机反馈本身有几个单位的抖动）


def make_io_frame(*pressed_ios: int) -> bytes:
    frame = bytearray(34)
    frame[0] = 0x01
    frame[1] = 0x04
    frame[2] = 0x20
    for io_num in pressed_ios:
        frame[2 + io_num * 2] = 1
    return bytes(frame)


def open_angle_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", ANGLE_PORT))
    sock.setblocking(False)
    return sock


def read_latest_angle(sock: socket.socket, timeout: float = 1.5):
    deadline = time.time() + timeout
    latest = None
    while time.time() < deadline:
        remaining = max(0.0, deadline - time.time())
        ready, _, _ = select.select([sock], [], [], remaining)
        if not ready:
            break
        data, _ = sock.recvfrom(2048)
        try:
            latest = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
    return latest


def send_action(action: str, repeat: int = 4, interval: float = 0.05):
    actions = {"u": UP_IO, "d": DOWN_IO, "l": LEFT_IO, "r": RIGHT_IO}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    press = make_io_frame(HEAD_CTRL_IO, actions[action])
    release = make_io_frame()
    for _ in range(repeat):
        sock.sendto(press, (BROADCAST_IP, CONTROL_PORT))
        time.sleep(interval)
    sock.sendto(release, (BROADCAST_IP, CONTROL_PORT))
    sock.close()


def check(sock) -> bool:
    """读当前角度，跟基准值比较。返回 True 表示在容差内（没漂移）。"""
    current = read_latest_angle(sock)
    if not current:
        print("[FATAL] 没收到角度广播，head_servo_ctrl.py 是否在运行？")
        return False
    d1 = current["angle1"] - HEAD_REFERENCE["angle1"]
    d2 = current["angle2"] - HEAD_REFERENCE["angle2"]
    ok = abs(d1) <= TOLERANCE and abs(d2) <= TOLERANCE
    print(f"当前: {current}  基准: {HEAD_REFERENCE}  偏差: angle1={d1:+d} angle2={d2:+d}")
    print("状态: 未漂移，可以继续标定" if ok else "状态: 已漂移！标右臂/左臂之间不能有这个偏差，先 restore")
    return ok


def restore(sock, max_steps: int = 20):
    """闭环微调回 HEAD_REFERENCE（每个轴独立收敛，不是原版 center() 那种两轴共用同一目标）。"""
    for step in range(1, max_steps + 1):
        current = read_latest_angle(sock)
        if not current:
            print("[FATAL] 没收到角度广播，中止")
            return False

        d1 = current["angle1"] - HEAD_REFERENCE["angle1"]
        d2 = current["angle2"] - HEAD_REFERENCE["angle2"]
        if abs(d1) <= TOLERANCE and abs(d2) <= TOLERANCE:
            print(f"恢复完成 @ step {step - 1}: {current}")
            return True

        # 方向映射照抄 test_head_udp.py 里 choose_center_actions() 已验证的逻辑：
        # angle1 偏小(current<target) -> "u"；偏大 -> "d"。
        # angle2 偏小(current<target) -> "l"；偏大 -> "r"。
        acts = []
        if d1 < -TOLERANCE:
            acts.append("u")
        elif d1 > TOLERANCE:
            acts.append("d")
        if d2 < -TOLERANCE:
            acts.append("l")
        elif d2 > TOLERANCE:
            acts.append("r")

        print(f"step {step}: current={current} delta=({d1:+d},{d2:+d}) actions={acts}")
        for a in acts:
            send_action(a)
            time.sleep(0.4)

    print(f"[WARN] 达到 max_steps={max_steps} 仍未收敛，请人工检查头部位置")
    return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["check", "restore"])
    args = parser.parse_args()

    sock = open_angle_socket()
    try:
        if args.action == "check":
            ok = check(sock)
            sys.exit(0 if ok else 1)
        else:
            ok = restore(sock)
            check(sock)
            sys.exit(0 if ok else 1)
    finally:
        sock.close()


if __name__ == "__main__":
    main()
