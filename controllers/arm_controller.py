"""
双臂 Realman 机械臂控制器 — 新版官方 SDK 版本
依赖：pip install robotic-arm  (睿尔曼官方 PyPI 包，支持 7-DOF)

遥操共存架构（实测验证于 grasp_demo.py，勿改回 SIGSTOP 插队）：
机器人后台有两个遥控进程：
  atom            关节遥控（100Hz CANFD 透传，主从高跟随 follow_mode=1）
  zhixing_ctrl.py 夹爪遥控（10Hz）
SDK 会话期间必须彻底停掉这两个进程，而不是逐次 SIGSTOP/SIGCONT 插队——
SIGSTOP 期间若 SDK 移动了从臂，SIGCONT 后高跟随会让从臂瞬间跳回主臂位置，
危险且可能触发保护。正确做法：构造时 pkill 让出控制权，纯 SDK 运动，
close() 时用官方 upstart 脚本（带 calibrate_speed 慢速校准）重启遥操。

另有 head_servo_ctrl.py（头部俯仰/偏航舵机遥控，UDP通道，独立于上面两个）：
构造/运行期间**不**杀它——头部舵机走独立UDP广播通道，跟手臂SDK完全不冲突，
杀掉反而会让头部舵机失去持续位置指令而弹回默认角度（eye-to-hand手眼标定要求
头部全程固定不动，误杀会导致标定全程实际跑偏，真实踩过的坑）。只在 close()
真正要重启整套遥操前才需要连 head_servo 一起杀掉，避免 upstart 重启时新旧
进程抢占同一串口。
"""

from __future__ import annotations

import atexit
import subprocess
import threading
import time
from typing import Optional

import numpy as np
from scipy.spatial.transform import Rotation
from Robotic_Arm.rm_robot_interface import RoboticArm, rm_thread_mode_e

from utils.config import ArmConfig, ConnectionsConfig, GripperConfig

# 官方遥操启动脚本（见 grasp_demo.py 同一套架构）
UPSTART_SH = "/home/rm/rmc_aida_l_atom/upstart_all.sh"
SUDO_PASS = "rm"


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
        self._closed = False

        self._stop_teleop()
        atexit.register(self.close)

        ip = (conn_config.right_arm_ip if conn_config.active_arm == "right"
              else conn_config.left_arm_ip)
        port = conn_config.arm_port

        self.arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
        self.handle = self.arm.rm_create_robot_arm(ip, port)

        self.openness = self._init_gripper()
        print(f"[ArmController] {conn_config.active_arm} 臂 ({ip}:{port}), "
              f"DOF={self.arm.arm_dof}, 遥操已彻底停用（close()时官方重启）")

    # ------------------------------------------------------------------
    # 遥操停止 / 重启（彻底停用，而非 SIGSTOP 插队 —— 见模块 docstring）
    # ------------------------------------------------------------------

    @staticmethod
    def _find_pids(name: str, flag: str = "-x") -> list:
        r = subprocess.run(["pgrep", flag, name], capture_output=True, text=True)
        return [int(p) for p in r.stdout.split()] if r.returncode == 0 and r.stdout.strip() else []

    def _kill_arm_teleop_processes(self) -> None:
        """只杀跟手臂/夹爪SDK控制冲突的遥控进程：atom(关节) + zhixing_ctrl.py(夹爪)。
        不碰 head_servo_ctrl.py —— 头部舵机走独立UDP通道，跟手臂SDK不冲突，
        杀掉它会导致头部舵机失去持续位置指令而弹回默认角度（实测踩过的坑：
        eye-to-hand标定要求头部全程固定，误杀head_servo会让标定全程实际跑偏）。"""
        subprocess.run(["pkill", "-x", "atom"])
        subprocess.run(["pkill", "-f", "zhixing_ctrl.py"])

    def _kill_all_teleop_processes(self) -> None:
        """彻底清场：atom + 夹爪遥控 + 头部舵机遥控。三者都要杀，漏杀 head_servo
        会导致 upstart 重启时新旧进程抢占同一串口（实测过的陷阱，见模块 docstring）。
        只在真正要重启遥操前调用——平时用SDK控制手臂不需要碰head_servo。"""
        subprocess.run(["pkill", "-x", "atom"])
        subprocess.run(["pkill", "-f", "zhixing_ctrl.py"])
        subprocess.run(["pkill", "-f", "head_servo_ctrl.py"])

    def _stop_teleop(self) -> None:
        print("[ArmController] 停遥操（pkill atom + zhixing_ctrl.py，让出控制权；head_servo保持运行）...")
        self._kill_arm_teleop_processes()
        time.sleep(1.5)

    def _restart_teleop(self) -> bool:
        print("[ArmController] 恢复遥操（官方 upstart_all.sh，带慢速校准）...")
        self._kill_all_teleop_processes()
        time.sleep(1)
        subprocess.run(f"echo {SUDO_PASS} | sudo -S -v", shell=True)
        env = "DISPLAY=:0 XAUTHORITY=/home/rm/.Xauthority"
        subprocess.Popen(
            f"{env} setsid bash -c 'bash {UPSTART_SH}' "
            f"< /dev/null > /home/rm/upstart_arm_controller.log 2>&1 &",
            shell=True,
        )
        print("  等待 atom 启动（官方流程含 IP 检测+校准，约 20-40s）...")
        for i in range(15):
            time.sleep(4)
            if self._find_pids("atom"):
                print(f"  [{(i + 1) * 4}s] atom 已启动")
                return True
        print(f"  [WARN] atom 未在预期时间内启动，检查 /home/rm/upstart_arm_controller.log")
        return False

    # ------------------------------------------------------------------
    # 运动接口（与旧版 ArmController 保持相同签名）
    # ------------------------------------------------------------------

    def move_to_joints(
        self, joint_angles_deg: list, speed: int = 30, radius: int = 0, wait: bool = True
    ) -> int:
        """关节空间规划运动，joint_angles_deg 为 7 个关节角度（度）。"""
        block = 1 if wait else 0
        with self.lock:
            result = self.arm.rm_movej(joint_angles_deg, speed, radius, 0, block)
        print(f"[ArmController] movej → {result}")
        return result

    def movej_to_cartesian_pose(self, pose: list, speed: int = 30, wait: bool = True) -> int:
        """关节插值到笛卡尔位姿，pose = [x,y,z,rx,ry,rz]（m / rad）。"""
        block = 1 if wait else 0
        with self.lock:
            result = self.arm.rm_movej_p(pose, speed, 0, 0, block)
        print(f"[ArmController] movej_p → {result}")
        return result

    def move_to_cartesian_pose(self, pose: list, speed: int = 30, wait: bool = True) -> int:
        """直线运动到笛卡尔位姿，pose = [x,y,z,rx,ry,rz]（m / rad）。"""
        block = 1 if wait else 0
        with self.lock:
            result = self.arm.rm_movel(pose, speed, 0, 0, block)
        print(f"[ArmController] movel → {result}")
        return result

    # ------------------------------------------------------------------
    # 状态读取
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
        with self.lock:
            self.arm.rm_set_gripper_position(raw_pos, False, 5)
        self.openness = openness
        print(f"[ArmController] 夹爪 raw={raw_pos}, 等待 {move_time:.2f}s")
        time.sleep(move_time)
        return 0

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            if hasattr(self, "arm"):
                self.arm.rm_delete_robot_arm()
        except Exception as e:
            print(f"[ArmController] SDK断开失败: {e}")
        restored = self._restart_teleop()
        if not restored:
            print("[ArmController] 遥操恢复异常，手动恢复：")
            print("  在 Mac 运行: python3 \"/Users/siqi.cai/Embodied AI/teleop_restore.py\"")
            print("  或重启机器人")
