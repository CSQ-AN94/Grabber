"""
双臂 Realman 机械臂控制器
通信方式：每条指令建立独立 TCP 连接（与 tcp_demo.py 的 req() 一致）。
写指令前 SIGSTOP atom 进程以独占控制权，完成后 SIGCONT 恢复遥控。
"""

from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
from contextlib import contextmanager
from typing import Optional

import numpy as np
from scipy.spatial.transform import Rotation

from utils.config import ArmConfig, ConnectionsConfig, GripperConfig


class ArmController:
    MOVE_TIMEOUT = 30.0
    REQ_TIMEOUT  = 5.0

    def __init__(
        self,
        conn_config: ConnectionsConfig,
        arm_config: ArmConfig,
        gripper_config: GripperConfig,
    ):
        self.config = arm_config
        self.gripper_config = gripper_config
        self._ip   = (conn_config.right_arm_ip if conn_config.active_arm == "right"
                      else conn_config.left_arm_ip)
        self._port = conn_config.arm_port
        self._atom_pid = self._find_atom_pid()
        self.openness  = 1.0
        print(f"[ArmController] {conn_config.active_arm} 臂  {self._ip}:{self._port}  atom={self._atom_pid}")

    # ------------------------------------------------------------------
    # atom 进程管理
    # ------------------------------------------------------------------

    def _find_atom_pid(self) -> Optional[int]:
        """动态查找 atom 遥控进程（zhixing_ctrl.py）PID"""
        try:
            r = subprocess.run(
                ["pgrep", "-f", "zhixing_ctrl.py"],
                capture_output=True, text=True
            )
            if r.returncode == 0 and r.stdout.strip():
                return int(r.stdout.strip().split()[0])
        except Exception:
            pass
        return None

    @contextmanager
    def _atom_paused(self):
        """SIGSTOP atom → yield → SIGCONT atom"""
        if self._atom_pid:
            os.kill(self._atom_pid, signal.SIGSTOP)
        try:
            yield
        finally:
            if self._atom_pid:
                os.kill(self._atom_pid, signal.SIGCONT)

    @contextmanager
    def _arm_session(self):
        """
        SIGSTOP atom → 位置控制模式 → 清错 → 工具上电 → yield
        → SIGCONT atom → 恢复遥控模式
        与 tcp_demo.py 的完整控制序列一致。
        """
        if self._atom_pid:
            os.kill(self._atom_pid, signal.SIGSTOP)
        try:
            self._req({"command": "set_arm_run_mode", "mode": 0})
            self._req({"command": "clear_system_err"})
            self._req({"command": "set_tool_voltage", "tool_voltage": 3})
            yield
        finally:
            if self._atom_pid:
                os.kill(self._atom_pid, signal.SIGCONT)
            try:
                self._req({"command": "set_arm_run_mode", "mode": 1})
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 底层 JSON 单次请求（与 tcp_demo.py 的 req() 等价）
    # ------------------------------------------------------------------

    def _req(self, payload: dict, timeout: float | None = None) -> dict:
        """每次调用新建 TCP 连接，发送一条 JSON 指令，返回响应。"""
        t = timeout or self.REQ_TIMEOUT
        with socket.create_connection((self._ip, self._port), timeout=3.0) as s:
            s.settimeout(t)
            s.sendall(json.dumps(payload).encode("utf-8") + b"\r\n")
            buf = b""
            while True:
                try:
                    chunk = s.recv(4096)
                except socket.timeout:
                    break
                if not chunk:
                    break
                buf += chunk
                try:
                    return json.loads(buf.decode("utf-8").strip())
                except json.JSONDecodeError:
                    continue
        raise RuntimeError(f"Realman: 无响应 command='{payload.get('command')}'")

    # ------------------------------------------------------------------
    # 运动接口（与旧版 ArmController 保持相同签名）
    # ------------------------------------------------------------------

    def move_to_joints(
        self, joint_angles_deg: list, speed: int = 30, radius: int = 0, wait: bool = True
    ) -> int:
        """关节空间规划运动，joint_angles_deg 为 7 个关节角度（度）。"""
        # Realman JSON API 的 movej joint 字段单位为 0.001°（毫度）
        joint_mdeg = [float(a) * 1000 for a in joint_angles_deg]
        with self._arm_session():
            resp = self._req(
                {"command": "movej", "joint": joint_mdeg,
                 "v": speed, "r": radius, "connect": 0, "block": 1},
                timeout=self.MOVE_TIMEOUT,
            )
        code = int(resp.get("movej_result", -1))
        print(f"[ArmController] movej → {code}")
        return code

    def movej_to_cartesian_pose(self, pose: list, speed: int = 30, wait: bool = True) -> int:
        """关节插值到笛卡尔位姿，pose = [x,y,z,rx,ry,rz]（m / rad）。"""
        with self._arm_session():
            resp = self._req(
                {"command": "movej_p", "pose": [float(v) for v in pose],
                 "v": speed, "r": 0, "connect": 0, "block": 1},
                timeout=self.MOVE_TIMEOUT,
            )
        code = int(resp.get("movej_p_result", -1))
        print(f"[ArmController] movej_p → {code}")
        return code

    def move_to_cartesian_pose(self, pose: list, speed: int = 30, wait: bool = True) -> int:
        """直线运动到笛卡尔位姿，pose = [x,y,z,rx,ry,rz]（m / rad）。"""
        with self._arm_session():
            resp = self._req(
                {"command": "movel", "pose": [float(v) for v in pose],
                 "v": speed, "r": 0, "connect": 0, "block": 1},
                timeout=self.MOVE_TIMEOUT,
            )
        code = int(resp.get("movel_result", -1))
        print(f"[ArmController] movel → {code}")
        return code

    # ------------------------------------------------------------------
    # 状态读取（不需要 SIGSTOP：读操作不干扰 atom 的遥控，与 demo 一致）
    # ------------------------------------------------------------------

    def get_current_joint_angles(self) -> Optional[list]:
        """返回 7 个关节角度（弧度）。"""
        try:
            resp = self._req({"command": "get_current_arm_state"})
            joints_mdeg = resp["arm_state"]["joint"]  # 单位：0.001°
            return [np.deg2rad(j / 1000.0) for j in joints_mdeg]
        except Exception as e:
            print(f"[ArmController] 读关节角失败: {e}")
            return None

    def get_base_to_end_pose_matrix(self) -> Optional[np.ndarray]:
        """返回末端在基座坐标系下的 4×4 变换矩阵（m / rad）。"""
        try:
            resp = self._req({"command": "get_current_arm_state"})
            pose = resp["arm_state"]["pose"]  # [x,y,z,rx,ry,rz] m/rad
            x, y, z = pose[:3]
            rx, ry, rz = pose[3], pose[4], pose[5]
            T = np.eye(4)
            T[:3, :3] = Rotation.from_euler("ZYX", [rx, ry, rz], degrees=False).as_matrix()
            T[:3, 3] = [x, y, z]
            return T
        except Exception as e:
            print(f"[ArmController] 读末端位姿失败: {e}")
            return None

    # ------------------------------------------------------------------
    # 夹爪控制（Realman Plus，同一 JSON TCP 接口）
    # ------------------------------------------------------------------

    def set_gripper_openness(self, openness: float) -> int:
        """openness: 0.0=全闭，1.0=全开"""
        openness  = float(np.clip(openness, 0.0, 1.0))
        raw_pos   = int(round(openness * 1000.0))
        move_time = abs(openness - self.openness) * self.gripper_config.open_time
        with self._atom_paused():
            self._req({"command": "set_gripper_position", "position": raw_pos, "block": False})
        self.openness = openness
        print(f"[ArmController] 夹爪 raw={raw_pos}, 等待 {move_time:.2f}s")
        time.sleep(move_time)
        return 0

    def close(self) -> None:
        pass  # 无持久连接，无需释放
