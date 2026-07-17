"""Force the head-camera servo (pitch/yaw) to its calibrated reference angle.

`config.yaml`'s `calibration.T_base_right_to_camera_head` was solved with the
head pinned at HEAD_REFERENCE (pitch lowest, yaw centered) — see the
eye-to-hand calibration session notes. Any drift off that angle silently
invalidates every 3-D point the head camera computes downstream. The head can
drift for reasons unrelated to this demo (manual `head_camera_control.py`
use, or an SDK side effect on `ArmController`/`RobotSession` init that has
been observed to nudge the servo — see project memory on teleop/SDK
coexistence), so it must be re-forced to the reference angle before anything
else runs, every run, rather than assumed correct.

Protocol lifted from `scripts/head_position_lock.py` (UDP broadcast IO frames
to `head_servo_ctrl.py` + an angle broadcast listener on a separate port),
kept import-safe here so `bottle_grasp/demo.py` can call it directly instead
of shelling out to a subprocess.
"""

from __future__ import annotations

import json
import logging
import select
import socket
import time
from typing import Optional

LOG = logging.getLogger("bottle_demo")

BROADCAST_IP = "169.254.128.255"
CONTROL_PORT = 19999
ANGLE_PORT = 9996

HEAD_CTRL_IO = 5
UP_IO, DOWN_IO, LEFT_IO, RIGHT_IO = 6, 7, 8, 9

# 2026-07-08 标定会话实测基准值：俯仰(angle1)最低、偏航(angle2)居中。
HEAD_REFERENCE = {"angle1": 398, "angle2": 516}
TOLERANCE = 5  # 舵机反馈本身有几个单位的抖动


def _make_io_frame(*pressed_ios: int) -> bytes:
    frame = bytearray(34)
    frame[0] = 0x01
    frame[1] = 0x04
    frame[2] = 0x20
    for io_num in pressed_ios:
        frame[2 + io_num * 2] = 1
    return bytes(frame)


def _open_angle_socket() -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind(("", ANGLE_PORT))
    sock.setblocking(False)
    return sock


def _read_latest_angle(sock: socket.socket, timeout: float = 1.5) -> Optional[dict]:
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


def _send_action(action: str, repeat: int = 4, interval: float = 0.05) -> None:
    actions = {"u": UP_IO, "d": DOWN_IO, "l": LEFT_IO, "r": RIGHT_IO}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    press = _make_io_frame(HEAD_CTRL_IO, actions[action])
    release = _make_io_frame()
    for _ in range(repeat):
        sock.sendto(press, (BROADCAST_IP, CONTROL_PORT))
        time.sleep(interval)
    sock.sendto(release, (BROADCAST_IP, CONTROL_PORT))
    sock.close()


def read_current_angle() -> Optional[dict]:
    sock = _open_angle_socket()
    try:
        return _read_latest_angle(sock)
    finally:
        sock.close()


def is_at_reference(current: Optional[dict]) -> bool:
    if not current:
        return False
    d1 = current["angle1"] - HEAD_REFERENCE["angle1"]
    d2 = current["angle2"] - HEAD_REFERENCE["angle2"]
    return abs(d1) <= TOLERANCE and abs(d2) <= TOLERANCE


def restore_reference(max_steps: int = 20) -> dict:
    """闭环把头部舵机调回 HEAD_REFERENCE，每个轴独立收敛。

    返回 {"ok": bool, "angle": 最后读到的角度或 None, "reason"/"steps": ...}，
    不抛异常——是否因此中止整个流程由调用方（demo.py）决定。
    """
    sock = _open_angle_socket()
    try:
        current = None
        for step in range(1, max_steps + 1):
            current = _read_latest_angle(sock)
            if current is None:
                return {
                    "ok": False,
                    "angle": None,
                    "reason": "没收到角度广播，head_servo_ctrl.py 是否在运行？",
                }
            if is_at_reference(current):
                return {"ok": True, "angle": current, "steps": step - 1}

            d1 = current["angle1"] - HEAD_REFERENCE["angle1"]
            d2 = current["angle2"] - HEAD_REFERENCE["angle2"]
            actions = []
            if d1 < -TOLERANCE:
                actions.append("u")
            elif d1 > TOLERANCE:
                actions.append("d")
            if d2 < -TOLERANCE:
                actions.append("l")
            elif d2 > TOLERANCE:
                actions.append("r")
            LOG.info(
                "头部回中 step %d: current=%s delta=(%+d,%+d) actions=%s",
                step,
                current,
                d1,
                d2,
                actions,
            )
            for action in actions:
                _send_action(action)
                time.sleep(0.4)
        return {
            "ok": False,
            "angle": current,
            "reason": f"达到 max_steps={max_steps} 仍未收敛",
        }
    finally:
        sock.close()
