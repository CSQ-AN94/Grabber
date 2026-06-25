"""
双臂 Realman 机械臂控制器 — 新版官方 SDK 版本
依赖：pip install robotic-arm  (睿尔曼官方 PyPI 包，支持 7-DOF)
写指令前 SIGSTOP atom 进程以独占控制权，完成后 SIGCONT 恢复遥控。
"""

from __future__ import annotations

import os
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from typing import Optional

import numpy as np
from scipy.spatial.transform import Rotation
from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e

from utils.config import ArmConfig, ConnectionsConfig, GripperConfig


class ArmController:

    def __init__(
        self,
        conn_config: ConnectionsConfig,
        arm_config: ArmConfig,
        gripper_config: GripperConfig,
    ):
        self.lock = threading.Lock()
        self.config = arm_config
        self.gripper_config = gripper_config
        self._atom_pid = self._find_atom_pid()

        ip = (conn_config.right_arm_ip if conn_config.active_arm == "right"
              else conn_config.left_arm_ip)
        port = conn_config.arm_port

        # 先 SIGSTOP atom，再建 SDK 连接，避免 atom 占住端口
        if self._atom_pid:
            os.kill(self._atom_pid, signal.SIGSTOP)
        try:
            self.arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
            self.handle = self.arm.rm_create_robot_arm(ip, port)
        finally:
            if self._atom_pid:
                os.kill(self._atom_pid, signal.SIGCONT)

        self.openness = self._init_gripper()
        print(f"[ArmController] {conn_config.active_arm} 臂 ({ip}:{port}), "
              f"DOF={self.arm.arm_dof}, atom={self._atom_pid}")

    # ------------------------------------------------------------------
    # atom 进程管理
    # ------------------------------------------------------------------

    def _find_atom_pid(self) -> Optional[int]:
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
    def _arm_session(self):
        """SIGSTOP atom → yield → SIGCONT atom"""
        if self._atom_pid:
            os.kill(self._atom_pid, signal.SIGSTOP)
        try:
            yield
        finally:
            if self._atom_pid:
                os.kill(self._atom_pid, signal.SIGCONT)

    # ------------------------------------------------------------------
    # 运动接口（与旧版 ArmController 保持相同签名）
    # ------------------------------------------------------------------

    def move_to_joints(
        self, joint_angles_deg: list, speed: int = 30, radius: int = 0, wait: bool = True
    ) -> int:
        """关节空间规划运动，joint_angles_deg 为 7 个关节角度（度）。"""
        block = 1 if wait else 0
        with self._arm_session():
            with self.lock:
                result = self.arm.rm_movej(joint_angles_deg, speed, radius, 0, block)
        print(f"[ArmController] movej → {result}")
        return result

    def movej_to_cartesian_pose(self, pose: list, speed: int = 30, wait: bool = True) -> int:
        """关节插值到笛卡尔位姿，pose = [x,y,z,rx,ry,rz]（m / rad）。"""
        block = 1 if wait else 0
        with self._arm_session():
            with self.lock:
                result = self.arm.rm_movej_p(pose, speed, 0, 0, block)
        print(f"[ArmController] movej_p → {result}")
        return result

    def move_to_cartesian_pose(self, pose: list, speed: int = 30, wait: bool = True) -> int:
        """直线运动到笛卡尔位姿，pose = [x,y,z,rx,ry,rz]（m / rad）。"""
        block = 1 if wait else 0
        with self._arm_session():
            with self.lock:
                result = self.arm.rm_movel(pose, speed, 0, 0, block)
        print(f"[ArmController] movel → {result}")
        return result

    # ------------------------------------------------------------------
    # 状态读取（不需要 SIGSTOP：读操作不干扰 atom 的遥控）
    # ------------------------------------------------------------------

    def get_current_joint_angles(self) -> Optional[list]:
        """返回 7 个关节角度（弧度）。"""
        with self.lock:
            code, joints_deg = self.arm.rm_get_joint_degree()
        if code == 0:
            return [np.deg2rad(j) for j in joints_deg]
        print(f"[ArmController] 读关节角失败，错误码: {code}")
        return None

    def get_base_to_end_pose_matrix(self) -> Optional[np.ndarray]:
        """返回末端在基座坐标系下的 4×4 变换矩阵（m / rad）。"""
        with self.lock:
            code, state = self.arm.rm_get_current_arm_state()
        if code != 0:
            print(f"[ArmController] 读末端位姿失败，错误码: {code}")
            return None
        pose = state.get('pose')
        if pose is None:
            return None
        x, y, z = pose[:3]
        rx, ry, rz = pose[3], pose[4], pose[5]
        T = np.eye(4)
        T[:3, :3] = Rotation.from_euler('ZYX', [rx, ry, rz], degrees=False).as_matrix()
        T[:3, 3] = [x, y, z]
        return T

    # ------------------------------------------------------------------
    # 夹爪控制（Realman Plus，SDK 原生支持）
    # ------------------------------------------------------------------

    def _init_gripper(self) -> float:
        self.arm.rm_set_tool_voltage(3)         # 24V 上电
        time.sleep(0.5)
        self.arm.rm_set_rm_plus_mode(115200)    # 启用 Realman Plus 协议（115200 波特率）
        time.sleep(0.3)
        self.arm.rm_set_gripper_position(1000, True, 5)  # 全开，阻塞等待，超时 5s
        time.sleep(self.gripper_config.open_time)
        return 1.0

    def set_gripper_openness(self, openness: float) -> int:
        """openness: 0.0=全闭，1.0=全开"""
        openness  = float(np.clip(openness, 0.0, 1.0))
        raw_pos   = int(round(openness * 1000.0))
        move_time = abs(openness - self.openness) * self.gripper_config.open_time
        with self._arm_session():
            with self.lock:
                self.arm.rm_set_gripper_position(raw_pos, False, 5)
        self.openness = openness
        print(f"[ArmController] 夹爪 raw={raw_pos}, 等待 {move_time:.2f}s")
        time.sleep(move_time)
        return 0

    def close(self) -> None:
        self.arm.rm_delete_robot_arm()
