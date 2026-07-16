"""RealMan RM75 connection, TCP setup, IK validation, and motion primitives."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import time
from typing import Sequence

import numpy as np

from .core import DemoParams, SafetyAbort, matrix_pose, pose_matrix

LOG = logging.getLogger("bottle_demo")


class ArmJointReader:
    """Read another arm in a subprocess to isolate SDK-global install angles."""

    def __init__(self, ip: str, port: int):
        self.ip = ip
        self.port = port

    def joints_deg(self) -> list[float]:
        code = (
            "import json\n"
            "from Robotic_Arm.rm_robot_interface import "
            "RoboticArm,rm_thread_mode_e\n"
            f"a=RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)\n"
            f"h=a.rm_create_robot_arm({self.ip!r},{self.port})\n"
            "rc,q=a.rm_get_joint_degree()\n"
            "a.rm_delete_robot_arm()\n"
            "print('BOTTLE_JOINTS_JSON='+json.dumps({'rc':rc,'q':q}))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=8,
        )
        marker = "BOTTLE_JOINTS_JSON="
        line = next(
            (
                item[len(marker) :]
                for item in result.stdout.splitlines()
                if item.startswith(marker)
            ),
            None,
        )
        if result.returncode != 0 or line is None:
            raise SafetyAbort(
                "另一机械臂关节读取子进程失败: "
                f"rc={result.returncode}, stderr={result.stderr.strip()}"
            )
        payload = json.loads(line)
        if payload["rc"] != 0:
            raise SafetyAbort(f"读取另一机械臂关节角失败: {payload['rc']}")
        return list(map(float, payload["q"]))

    def close(self):
        return


class RobotSession:
    def __init__(
        self,
        ip: str,
        port: int,
        stop_event: threading.Event,
        tcp_z_m: float,
        model_flange_offset_m: float = 0.0172,
        take_control: bool = True,
    ):
        from Robotic_Arm.rm_robot_interface import (
            Algo,
            RoboticArm,
            rm_force_type_e,
            rm_frame_t,
            rm_inverse_kinematics_params_t,
            rm_robot_arm_model_e,
            rm_thread_mode_e,
        )

        self.rm_frame_t = rm_frame_t
        self.ik_params = rm_inverse_kinematics_params_t
        self.stop_event = stop_event
        self.tcp_z_m = tcp_z_m
        self.model_flange_offset_m = model_flange_offset_m
        self.take_control = take_control
        self.closed = False
        if self.take_control:
            self._stop_teleop()
        self.arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
        self.handle = self.arm.rm_create_robot_arm(ip, port)
        if self.handle.id == -1:
            raise SafetyAbort("机械臂 SDK 连接失败")
        self.algo = Algo(
            rm_robot_arm_model_e.RM_MODEL_RM_75_E,
            rm_force_type_e.RM_MODEL_RM_B_E,
        )
        install = self.arm.rm_get_install_pose()
        if install.get("return_code") != 0:
            raise SafetyAbort(f"读取机械臂安装角失败: {install}")
        install_angles = [
            float(install[key]) for key in ("x", "y", "z")
        ]
        self.algo.rm_algo_set_angle(*install_angles)
        LOG.info("加载机械臂安装角: %s", install_angles)
        self.algo.rm_algo_set_redundant_parameter_traversal_mode(True)
        if self.take_control:
            self.arm.rm_set_tool_voltage(3)
            time.sleep(0.5)
            self.arm.rm_set_rm_plus_mode(115200)
            time.sleep(0.3)
            self.set_tcp()
        self.monitor = None
        if self.take_control:
            self.monitor = threading.Thread(target=self._monitor_stop, daemon=True)
            self.monitor.start()

    @staticmethod
    def _stop_teleop():
        subprocess.run(["pkill", "-x", "atom"], check=False)
        subprocess.run(["pkill", "-f", "zhixing_ctrl.py"], check=False)
        time.sleep(1.5)

    def set_tcp(self):
        frame = self.rm_frame_t(
            "bottleTCP", [0, 0, self.tcp_z_m, 0, 0, 0], 0, 0, 0, 0
        )
        rc = self.arm.rm_set_manual_tool_frame(frame)
        if rc != 0:
            get_rc, existing = self.arm.rm_get_given_tool_frame("bottleTCP")
            if get_rc != 0:
                raise SafetyAbort(
                    f"设置真实 TCP 失败且无法读取已有坐标系: {rc}/{get_rc}"
                )
            pose = existing.get("pose", [])
            if len(pose) != 6 or abs(float(pose[2]) - self.tcp_z_m) > 1e-5:
                update_rc = self.arm.rm_update_tool_frame(frame)
                if update_rc != 0:
                    raise SafetyAbort(
                        f"更新已有真实 TCP 失败: {update_rc}"
                    )
            LOG.info("复用已有工具坐标 bottleTCP")
        rc = self.arm.rm_change_tool_frame("bottleTCP")
        if rc != 0:
            raise SafetyAbort(f"切换真实 TCP 失败: {rc}")
        self._set_algo_tool_z(
            self.model_flange_offset_m + self.tcp_z_m
        )

    def _set_algo_tool_z(self, z_m: float):
        frame = self.rm_frame_t(
            "algoTool", [0, 0, float(z_m), 0, 0, 0], 0, 0, 0, 0
        )
        self.algo.rm_algo_set_toolframe(frame)

    def controller_flange_from_joints(
        self, joints_deg: Sequence[float]
    ) -> np.ndarray:
        self._set_algo_tool_z(self.model_flange_offset_m)
        pose = self.algo.rm_algo_forward_kinematics(
            list(map(float, joints_deg)), 1
        )
        if not pose or len(pose) != 6:
            raise SafetyAbort("SDK 正解未返回有效控制器法兰位姿")
        return pose_matrix(pose)

    def _monitor_stop(self):
        self.stop_event.wait()
        if not self.closed:
            try:
                self.arm.rm_set_arm_slow_stop()
            except Exception:
                LOG.exception("缓停命令失败；请使用硬件急停")

    def current_tcp(self) -> np.ndarray:
        if not self.take_control:
            raise SafetyAbort("只规划会话未设置 TCP，禁止读取 TCP 位姿")
        code, state = self.arm.rm_get_current_arm_state()
        if code != 0 or not state.get("pose"):
            raise SafetyAbort(f"读取 TCP 位姿失败: {code}")
        for key in ("arm_err", "sys_err"):
            value = state.get(key, 0)
            if value not in (0, None, [0]):
                raise SafetyAbort(f"控制器报告 {key}={value}")
        nested = state.get("err")
        if isinstance(nested, dict):
            values = nested.get("err", [])
            if any(str(value) != "0" for value in values):
                raise SafetyAbort(f"控制器报告 err={nested}")
        return pose_matrix(state["pose"])

    def current_flange(self) -> np.ndarray:
        T_tcp = self.current_tcp()
        T_flange_tcp = np.eye(4)
        T_flange_tcp[2, 3] = self.tcp_z_m
        return T_tcp @ np.linalg.inv(T_flange_tcp)

    def joints_deg(self) -> list[float]:
        rc, joints = self.arm.rm_get_joint_degree()
        if rc != 0:
            raise SafetyAbort(f"读取关节角失败: {rc}")
        return list(map(float, joints))

    def plan_ik(
        self,
        poses: Sequence[Sequence[float]],
        params: DemoParams,
        *,
        allow_first_jump: bool = False,
    ) -> list[list[float]]:
        self._set_algo_tool_z(
            self.model_flange_offset_m + self.tcp_z_m
        )
        q = self.joints_deg()
        rc_min, qmin = self.arm.rm_get_joint_min_pos()
        rc_max, qmax = self.arm.rm_get_joint_max_pos()
        if rc_min != 0 or rc_max != 0:
            raise SafetyAbort("无法读取控制器关节限位")
        self.algo.rm_algo_set_joint_min_limit(list(qmin))
        self.algo.rm_algo_set_joint_max_limit(list(qmax))
        planned = []
        for idx, pose in enumerate(poses):
            rc, solution = self.algo.rm_algo_inverse_kinematics(
                self.ik_params(q, list(pose), 1)
            )
            if rc != 0:
                raise SafetyAbort(f"路径点 {idx + 1}/{len(poses)} 逆解失败: {rc}")
            solution = list(map(float, solution))
            for joint, (angle, lo, hi) in enumerate(
                zip(solution, qmin, qmax), 1
            ):
                if not (
                    lo + params.joint_limit_margin_deg
                    <= angle
                    <= hi - params.joint_limit_margin_deg
                ):
                    raise SafetyAbort(
                        f"路径点 {idx + 1} 关节 J{joint} 距限位过近: {angle:.1f}°"
                    )
            if abs(solution[3]) < params.j4_singularity_deg:
                raise SafetyAbort(
                    f"路径点 {idx + 1} J4={solution[3]:.1f}°，进入奇异区"
                )
            if (
                not (allow_first_jump and idx == 0)
                and max(abs(a - b) for a, b in zip(solution, q)) > 28
            ):
                raise SafetyAbort(f"路径点 {idx + 1} 逆解关节跳变超过 28°")
            planned.append(solution)
            q = solution
        return planned

    def solve_flange_ik(
        self,
        target_controller_flange: np.ndarray,
        params: DemoParams,
    ) -> list[float]:
        self._set_algo_tool_z(self.model_flange_offset_m)
        seed = self.joints_deg()
        rc, solution = self.algo.rm_algo_inverse_kinematics(
            self.ik_params(
                seed,
                matrix_pose(np.asarray(target_controller_flange, dtype=float)),
                1,
            )
        )
        if rc != 0:
            raise SafetyAbort(f"控制器同源法兰逆解失败: {rc}")
        solution = list(map(float, solution))
        rc_min, qmin = self.arm.rm_get_joint_min_pos()
        rc_max, qmax = self.arm.rm_get_joint_max_pos()
        if rc_min != 0 or rc_max != 0:
            raise SafetyAbort("无法读取控制器关节限位")
        for joint, (angle, lo, hi) in enumerate(
            zip(solution, qmin, qmax), 1
        ):
            if not (
                lo + params.joint_limit_margin_deg
                <= angle
                <= hi - params.joint_limit_margin_deg
            ):
                raise SafetyAbort(
                    f"目标逆解 J{joint} 距限位过近: {angle:.1f}°"
                )
        if abs(solution[3]) < params.j4_singularity_deg:
            raise SafetyAbort(
                f"目标逆解 J4={solution[3]:.1f}°，进入奇异区"
            )
        return solution

    @staticmethod
    def _dense_joint_path(
        start_joints_deg: Sequence[float],
        points_deg: Sequence[Sequence[float]],
        max_step_deg: float,
    ) -> list[list[float]]:
        current = np.asarray(start_joints_deg, dtype=float)
        dense: list[list[float]] = []
        for target_values in points_deg:
            target = np.asarray(target_values, dtype=float)
            count = max(
                1,
                int(np.ceil(np.max(np.abs(target - current)) / max_step_deg)),
            )
            for index in range(1, count + 1):
                alpha = index / count
                dense.append(((1 - alpha) * current + alpha * target).tolist())
            current = target
        return dense

    def tcp_from_joints(self, joints_deg: Sequence[float]) -> np.ndarray:
        self._set_algo_tool_z(
            self.model_flange_offset_m + self.tcp_z_m
        )
        tcp_pose = self.algo.rm_algo_forward_kinematics(
            list(map(float, joints_deg)), 1
        )
        if not tcp_pose or len(tcp_pose) != 6:
            raise SafetyAbort("SDK 正解未返回有效 TCP 位姿")
        return pose_matrix(tcp_pose)

    def validate_planned_joints(
        self,
        points_deg: Sequence[Sequence[float]],
        max_step_deg: float,
        safety_profile,
        start_joints_deg: Sequence[float] | None = None,
    ) -> int:
        if not points_deg:
            raise SafetyAbort("规划轨迹为空")
        dense = self._dense_joint_path(
            (
                self.joints_deg()
                if start_joints_deg is None
                else start_joints_deg
            ),
            points_deg,
            max_step_deg,
        )
        tcp_points = [self.tcp_from_joints(joints)[:3, 3] for joints in dense]
        return safety_profile.assert_tcp_path(tcp_points)

    def move_linear(self, pose: Sequence[float], speed: int):
        if self.stop_event.is_set():
            raise SafetyAbort("用户停止")
        rc = self.arm.rm_movel(list(pose), speed, 0, 0, 1)
        if rc != 0:
            raise SafetyAbort(f"movel 失败: {rc}")

    def execute_planned_joints(
        self,
        points_deg: Sequence[Sequence[float]],
        speed: int,
        max_step_deg: float,
        max_dense_points: int | None = None,
    ) -> bool:
        """Execute a dense, collision-checked MoveIt path through SDK movej.

        MoveIt remains planning-only. Dense waypoint interpolation bounds the
        difference between the planned joint path and each SDK joint segment.
        """
        if not self.take_control:
            raise SafetyAbort("只规划会话禁止执行运动")
        if not points_deg:
            raise SafetyAbort("规划轨迹为空")
        dense = self._dense_joint_path(
            self.joints_deg(), points_deg, max_step_deg
        )
        LOG.info("SDK 执行 MoveIt 轨迹: %d 个密集关节点", len(dense))
        selected = dense
        if max_dense_points is not None:
            selected = dense[:max_dense_points]
        for index, joints in enumerate(selected, 1):
            if self.stop_event.is_set():
                raise SafetyAbort("用户停止")
            rc = self.arm.rm_movej(joints, speed, 0, 0, 1)
            if rc != 0:
                raise SafetyAbort(
                    f"MoveIt 轨迹点 {index}/{len(selected)} 执行失败: {rc}"
                )
            self.current_tcp()
        return len(selected) == len(dense)

    def gripper_state(self) -> dict:
        """Read the installed RM Plus end-effector, not the legacy gripper API."""
        rc, state = self.arm.rm_get_rm_plus_state_info()
        if rc != 0:
            raise SafetyAbort(f"读取 RM Plus 夹爪状态失败: {rc}")
        if int(state.get("sys_state", 0)) != 0:
            raise SafetyAbort(f"RM Plus 系统状态异常: {state}")
        dof_err = state.get("dof_err", [0])
        if dof_err and int(dof_err[0]) != 0:
            raise SafetyAbort(f"RM Plus 夹爪故障: {state}")
        return state

    def _command_gripper_position(
        self,
        target: int,
        *,
        speed: int,
        force: int | None,
        timeout_s: float = 5.0,
    ) -> dict:
        """Command RM Plus and wait for a fresh, settled state sample."""
        before = self.gripper_state()
        start_pos = int(before["pos"][0])
        if force is not None and self.arm.rm_set_hand_force(int(force)) != 0:
            raise SafetyAbort("设置 RM Plus 夹爪内部力限幅失败")
        if self.arm.rm_set_hand_speed(int(speed)) != 0:
            raise SafetyAbort("设置 RM Plus 夹爪速度失败")
        command = [int(target), -1, -1, -1, -1, -1]
        if self.arm.rm_set_hand_follow_pos(command, False) != 0:
            raise SafetyAbort("RM Plus 夹爪位置命令发送失败")

        deadline = time.monotonic() + timeout_s
        movement_seen = abs(start_pos - target) <= 8
        settled_samples = 0
        latest = before
        while time.monotonic() < deadline:
            if self.stop_event.is_set():
                raise SafetyAbort("用户停止")
            latest = self.gripper_state()
            state = int(latest["dof_state"][0])
            pos = int(latest["pos"][0])
            speed_now = int(latest["speed"][0])
            if abs(pos - start_pos) >= 8 or state == 0:
                movement_seen = True
            if state in (5, 6):
                raise SafetyAbort(f"RM Plus 夹爪保护或故障: {latest}")
            if movement_seen and state in (2, 3) and speed_now == 0:
                settled_samples += 1
                if settled_samples >= 3:
                    return latest
            else:
                settled_samples = 0
            time.sleep(0.05)
        raise SafetyAbort(
            "RM Plus 夹爪动作超时: "
            f"target={target}, pos={latest.get('pos')}, "
            f"state={latest.get('dof_state')}"
        )

    def open_gripper(self, params: DemoParams | None = None) -> dict:
        if not self.take_control:
            raise SafetyAbort("只规划会话禁止控制夹爪")
        params = params or DemoParams()
        state = self._command_gripper_position(
            params.gripper_open_position,
            speed=params.gripper_speed,
            force=None,
        )
        pos = int(state["pos"][0])
        dof_state = int(state["dof_state"][0])
        if dof_state != 2 or pos < params.gripper_open_position - 50:
            raise SafetyAbort(
                f"夹爪未可靠打开: state={dof_state}, pos={pos}"
            )
        LOG.info("RM Plus 夹爪已打开: state=%d pos=%d", dof_state, pos)
        return state

    def close_gripper(self, params: DemoParams | None = None) -> dict:
        if not self.take_control:
            raise SafetyAbort("只规划会话禁止控制夹爪")
        params = params or DemoParams()
        state = self._command_gripper_position(
            params.gripper_close_position,
            speed=params.gripper_speed,
            force=params.gripper_force,
        )
        dof_state = int(state["dof_state"][0])
        pos = int(state["pos"][0])
        current = int(state["current"][0])
        minimum_object_pos = (
            params.gripper_empty_closed_position
            + params.gripper_object_margin
        )
        LOG.info(
            "RM Plus 闭合反馈: state=%d pos=%d current=%d; 抓取阈值 pos>%d",
            dof_state,
            pos,
            current,
            minimum_object_pos,
        )
        if dof_state != 3:
            raise SafetyAbort(
                "夹爪未达到内部夹持力，禁止抬升: "
                f"state={dof_state}, pos={pos}, current={current}"
            )
        if pos <= minimum_object_pos:
            raise SafetyAbort(
                "夹爪闭合位置等同空夹，判定未抓到水瓶，禁止抬升: "
                f"pos={pos}, 空夹基线={params.gripper_empty_closed_position}"
            )
        return state

    def hold(self):
        if not self.take_control:
            return
        try:
            self.arm.rm_set_arm_slow_stop()
        except Exception:
            pass

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.arm.rm_delete_robot_arm()
        finally:
            if self.take_control:
                LOG.warning(
                    "SDK 已断开；未自动恢复遥操。检查现场后手动运行官方 upstart_all.sh"
                )
