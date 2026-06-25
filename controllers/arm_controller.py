"""
双臂 Realman 机械臂控制器
通过 JSON TCP socket 与机械臂通信，不依赖 RM_API2 Python SDK。
支持 7-DOF；夹爪通过 Realman Plus JSON 指令控制（不再走 Modbus RTU RS485）。
"""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from typing import Optional

import numpy as np
from scipy.spatial.transform import Rotation

from utils.config import ArmConfig, ConnectionsConfig, GripperConfig


class ArmController:
    """
    连接单只机械臂（由 ConnectionsConfig.active_arm 决定左臂还是右臂）。
    对外接口与旧版保持兼容，内部改为 JSON TCP 通信。
    """

    MOVE_TIMEOUT = 30.0   # 规划运动等待超时（秒）
    RECV_TIMEOUT = 10.0   # TCP 接收超时（秒）

    def __init__(
        self,
        conn_config: ConnectionsConfig,
        arm_config: ArmConfig,
        gripper_config: GripperConfig,
    ):
        self.lock = threading.Lock()
        self.config = arm_config
        self.gripper_config = gripper_config

        ip = (
            conn_config.right_arm_ip
            if conn_config.active_arm == "right"
            else conn_config.left_arm_ip
        )
        self._endpoint = (ip, conn_config.arm_port)
        self._sock: Optional[socket.socket] = None

        self._connect()
        self.openness = self._init_gripper()
        print(f"[ArmController] 已连接到 {conn_config.active_arm} 臂 ({ip}:{conn_config.arm_port})")

    # ------------------------------------------------------------------
    # 连接管理
    # ------------------------------------------------------------------

    def _connect(self) -> None:
        self._sock = socket.create_connection(self._endpoint, timeout=5.0)
        self._sock.settimeout(self.RECV_TIMEOUT)
        # 初始化 Realman Plus 夹爪通信模式
        self._send_raw({"command": "set_rm_plus_mode", "mode": 115200})
        try:
            self._sock.recv(256)  # 丢弃握手响应
        except socket.timeout:
            pass
        time.sleep(0.3)

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None

    # ------------------------------------------------------------------
    # 底层 JSON 收发
    # ------------------------------------------------------------------

    def _send_raw(self, payload: dict) -> None:
        wire = json.dumps(payload).encode("utf-8") + b"\r\n"
        self._sock.sendall(wire)

    def _recv_until(self, expected_key: str, timeout: float | None = None) -> dict:
        """阻塞读取直到响应 dict 中出现 expected_key，返回该 dict。"""
        deadline = time.monotonic() + (timeout or self.RECV_TIMEOUT)
        buf = bytearray()
        last_obj: dict | None = None
        orig_timeout = self._sock.gettimeout()
        try:
            while time.monotonic() < deadline:
                newline = buf.find(b"\n")
                if newline != -1:
                    line = bytes(buf[:newline]).strip()
                    del buf[: newline + 1]
                    if not line:
                        continue
                    try:
                        obj = json.loads(line.decode("utf-8"))
                    except Exception:
                        continue
                    if not isinstance(obj, dict):
                        continue
                    last_obj = obj
                    if expected_key in obj:
                        return obj
                    continue
                remaining = deadline - time.monotonic()
                self._sock.settimeout(min(0.1, max(0.001, remaining)))
                try:
                    chunk = self._sock.recv(4096)
                except socket.timeout:
                    continue
                if not chunk:
                    break
                buf.extend(chunk)
        finally:
            self._sock.settimeout(orig_timeout)
        if last_obj is None:
            raise RuntimeError(f"Realman: 未收到任何响应（等待 key='{expected_key}'）")
        raise RuntimeError(
            f"Realman: 超时等待 '{expected_key}'，最后收到 keys={list(last_obj.keys())}"
        )

    def _request(self, payload: dict, expected_key: str, timeout: float | None = None) -> dict:
        """带锁的请求-响应。"""
        with self.lock:
            self._send_raw(payload)
            return self._recv_until(expected_key, timeout=timeout)

    def _send_motion(self, payload: dict, result_key: str, timeout: float | None = None) -> int:
        """
        发送运动指令，等待 result_key 出现，返回错误码（0 = 成功）。
        block=0 时不等待响应，直接返回 0。
        """
        block = payload.get("block", 1)
        with self.lock:
            self._send_raw(payload)
            if not block:
                return 0
            try:
                resp = self._recv_until(result_key, timeout=timeout or self.MOVE_TIMEOUT)
                return int(resp.get(result_key, -1))
            except RuntimeError as e:
                print(f"[ArmController] 运动等待失败: {e}")
                return -1

    # ------------------------------------------------------------------
    # 运动接口（与旧版 ArmController 保持相同签名）
    # ------------------------------------------------------------------

    def move_to_joints(
        self, joint_angles_deg: list, speed: int = 30, radius: int = 0, wait: bool = True
    ) -> int:
        """关节空间规划运动，joint_angles_deg 为 7 个关节角度（单位：度）。"""
        payload = {
            "command": "movej",
            "joint": [float(a) for a in joint_angles_deg],
            "v": speed,
            "r": radius,
            "connect": 0,
            "block": 1 if wait else 0,
        }
        result = self._send_motion(payload, "movej_result")
        print(f"[DEBUG] movej result: {result}")
        return result

    def move_to_cartesian_pose(self, pose: list, speed: int = 30, wait: bool = True) -> int:
        """笛卡尔直线运动，pose = [x, y, z, rx, ry, rz]，单位 m 和 rad。"""
        payload = {
            "command": "movel",
            "pose": [float(v) for v in pose],
            "v": speed,
            "r": 0,
            "connect": 0,
            "block": 1 if wait else 0,
        }
        result = self._send_motion(payload, "movel_result")
        print(f"[DEBUG] movel result: {result}")
        return result

    def movej_to_cartesian_pose(self, pose: list, speed: int = 30, wait: bool = True) -> int:
        """关节插值运动到笛卡尔位姿，pose = [x, y, z, rx, ry, rz]，单位 m 和 rad。"""
        payload = {
            "command": "movej_p",
            "pose": [float(v) for v in pose],
            "v": speed,
            "r": 0,
            "connect": 0,
            "block": 1 if wait else 0,
        }
        result = self._send_motion(payload, "movej_p_result")
        print(f"[DEBUG] movej_p result: {result}")
        return result

    # ------------------------------------------------------------------
    # 状态读取
    # ------------------------------------------------------------------

    def get_current_joint_angles(self) -> Optional[list]:
        """返回当前 7 个关节角度（单位：弧度）。"""
        try:
            resp = self._request({"command": "get_joint_degree"}, "joint")
            # Realman JSON API 返回 0.001° 单位
            return [np.deg2rad(j / 1000.0) for j in resp["joint"]]
        except Exception as e:
            print(f"[ArmController] 获取关节角失败: {e}")
            return None

    def get_base_to_end_pose_matrix(self) -> Optional[np.ndarray]:
        """获取末端在基座坐标系下的 4×4 位姿矩阵（位置单位 m，姿态单位 rad）。"""
        try:
            resp = self._request({"command": "get_current_arm_state"}, "arm_state")
            pose_raw = resp["arm_state"].get("pose")
            if pose_raw is None:
                print("[ArmController] arm_state 响应中无 pose 字段")
                return None
            x, y, z = pose_raw[0], pose_raw[1], pose_raw[2]
            rx, ry, rz = pose_raw[3], pose_raw[4], pose_raw[5]
            T = np.eye(4)
            T[:3, :3] = Rotation.from_euler("ZYX", [rx, ry, rz], degrees=False).as_matrix()
            T[:3, 3] = [x, y, z]
            return T
        except Exception as e:
            print(f"[ArmController] 获取末端位姿失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 夹爪控制（Realman Plus，JSON 指令；不再走 Modbus RTU）
    # Realman Plus 语义：position 1000 = 全开，0 = 全闭
    # ------------------------------------------------------------------

    def _init_gripper(self) -> float:
        """初始化夹爪为全开，返回初始 openness=1.0。"""
        self._send_raw({"command": "set_gripper_position", "position": 1000, "block": False})
        time.sleep(self.gripper_config.open_time)
        return 1.0

    def set_gripper_openness(self, openness: float) -> int:
        """
        设置夹爪开度。
        openness: 0.0 = 全闭，1.0 = 全开（与旧版语义相同）
        """
        openness = float(np.clip(openness, 0.0, 1.0))
        raw_pos = int(round(openness * 1000.0))
        move_time = abs(openness - self.openness) * self.gripper_config.open_time
        with self.lock:
            self._send_raw(
                {"command": "set_gripper_position", "position": raw_pos, "block": False}
            )
        self.openness = openness
        print(f"[ArmController] 夹爪 openness={openness:.2f} raw={raw_pos} 等待 {move_time:.2f}s")
        time.sleep(move_time)
        return 0

    async def set_gripper_openness_async(self, openness: float) -> int:
        return await asyncio.to_thread(self.set_gripper_openness, openness)
