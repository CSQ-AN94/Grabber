#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
统一的机械臂与夹爪控制器 (V3 - 重构版)
"""
import time
import numpy as np
import threading
import math
from scipy.spatial.transform import Rotation

from external.RM_API2.Python.Robotic_Arm.rm_robot_interface import *

# --- 辅助函数: 6D位姿 <-> 4x4矩阵 ---
def pose6d_to_matrix(pose):
    mat = np.identity(4)
    r = Rotation.from_euler('xyz', [pose[3], pose[4], pose[5]], degrees=False)
    mat[:3, :3] = r.as_matrix()
    mat[:3, 3] = [pose[0], pose[1], pose[2]]
    return mat

def matrix_to_pose6d(matrix):
    R_mat = matrix[:3, :3]
    x, y, z = matrix[:3, 3]
    r = Rotation.from_matrix(R_mat)
    roll, pitch, yaw = r.as_euler('xyz', degrees=False)
    return [x, y, z, roll, pitch, yaw]

class RobotController:
    def __init__(self, robot_ip, robot_port):
        print("--- 正在初始化统一机器人控制器 ---")
        self.arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
        self.handle = self.arm.rm_create_robot_arm(robot_ip, robot_port)
        self.lock = threading.RLock()
        self.placement_poses = [
            [0.465, 0.066, 0.300, 3.079, 1.322, -3.069],    # 放置点1
            [0.468, 0.005, 0.292, 3.091, 1.269, 3.096],   # 放置点2
            [0.455, -0.096, 0.284, 3.103, 1.211, 2.89]    # 放置点3
        ]
        if self.handle.id == -1:
            raise ConnectionError(f"机械臂连接失败，请检查IP地址 {robot_ip}:{robot_port}")
        print(f"机械臂连接成功, 句柄: {self.handle.id}")
        self._init_gripper()

    # ... (保留 _init_gripper, _write_gripper_reg, set_gripper) ...
    def _init_gripper(self):
        print("--- 正在初始化夹爪 ---")
        self.arm.rm_set_tool_voltage(3); time.sleep(0.5)
        self.arm.rm_set_tool_rs485_mode(0, 9600); time.sleep(0.2)
        self._write_gripper_reg(36, 25600); time.sleep(0.2)
        self._write_gripper_reg(38, 51200); time.sleep(0.2)
        self._write_gripper_reg(40, 51200); time.sleep(0.2)
        self._write_gripper_reg(43, 256000); time.sleep(3)
        self.current_openness = 0.0
        print("--- 夹爪初始化完成 ---")

    def _write_gripper_reg(self, address, value):
        high = (value >> 16) & 0xFFFF
        low = value & 0xFFFF
        param = rm_modbus_rtu_write_params_t(device=1, address=address, type=1, num=2, data=[high, low])
        return self.arm.rm_write_modbus_rtu_registers(param)

    def set_gripper(self, openness, wait=True):
        with self.lock:
            openness = max(0.0, min(1.0, openness))
            pos = int((1 - openness) * 256000)
            result = self._write_gripper_reg(43, pos)
            if wait:
                sleep_time = abs(self.current_openness - openness) * 2.0
                print(f"设置夹爪开度: {openness:.2f}, 等待: {sleep_time:.1f}s")
                time.sleep(sleep_time)
            self.current_openness = openness
            return result

    # --- 新的核心方法 ---
    def calculate_target_poses(self, camera_coords):
        """第一步：只计算。根据相机坐标和当前姿态，计算抓取和预抓取位姿。"""
        with self.lock:
            print("--- 步骤A: 计算目标的绝对世界位姿 ---")
            yolo_Y, yolo_neg_X, yolo_Z = camera_coords
            cam_x, cam_y, cam_z = yolo_Y, yolo_neg_X, yolo_Z

            HAND_EYE_T_tool0_cam = np.array([
                [ 1.0,  0.0,  0.0, -0.1020577],
                [ 0.0,  1.0,  0.0,  0.0236675],
                [ 0.0,  0.0,  1.0, -0.08289],
                [ 0.0,  0.0,  0.0,  1.0]
            ])
            T_cam_grasp = np.identity(4)
            T_cam_grasp[:3, 3] = [cam_x, cam_y, cam_z]

            scan_pose_6d = self.get_current_pose()
            if not scan_pose_6d: return None, None
            
            T_base_tool0_scan = pose6d_to_matrix(scan_pose_6d)
            T_base_touch_target = T_base_tool0_scan @ HAND_EYE_T_tool0_cam @ T_cam_grasp

            PRE_GRASP_OFFSET_METERS = 0.2
            final_rotation_mat = T_base_touch_target[:3, :3]
            z_axis_vector = final_rotation_mat[:, 2]
            final_position = T_base_touch_target[:3, 3]
            pre_grasp_position = final_position - z_axis_vector * PRE_GRASP_OFFSET_METERS
            
            T_base_pre_grasp_target = np.identity(4)
            T_base_pre_grasp_target[:3, :3] = final_rotation_mat
            T_base_pre_grasp_target[:3, 3] = pre_grasp_position

            touch_pose_6d = matrix_to_pose6d(T_base_touch_target)
            pre_grasp_pose_6d = matrix_to_pose6d(T_base_pre_grasp_target)

            if touch_pose_6d and pre_grasp_pose_6d:
                print(f"--- 计算完成。抓取位姿: {np.round(touch_pose_6d, 3)} ---")
                print(f"---            预抓取位姿: {np.round(pre_grasp_pose_6d, 3)} ---")
                return touch_pose_6d, pre_grasp_pose_6d
            else:
                return None, None

    def orient_base_towards_world_coords(self, world_coords_xyz, auto_confirm=False):
        """第二步：只转身。旋转基座对准世界坐标。"""
        with self.lock:
            target_x, target_y, _ = world_coords_xyz
            print(f"\n--- 准备旋转基座以对准世界坐标 (X,Y): ({target_x:.3f}, {target_y:.3f}) ---")

            target_angle_rad = math.atan2(target_y, target_x)
            target_angle_deg = math.degrees(target_angle_rad)
            final_angle_deg = target_angle_deg #+ 180.0

            if final_angle_deg > 180: final_angle_deg -= 360
            elif final_angle_deg < -180: final_angle_deg += 360

            ret_code, state_dict = self.arm.rm_get_current_arm_state()
            if ret_code != 0 or 'joint' not in state_dict: return False
            
            current_joints_deg = state_dict['joint']
            target_joints_deg = current_joints_deg.copy()
            target_joints_deg[0] = final_angle_deg

            print(f"--- 目标基座绝对角度 (度): {final_angle_deg:.2f} ---")
            
            # 如果不是自动确认，则请求用户输入。API调用时应设为True。
            if auto_confirm or input("确认旋转基座? (回车执行): ").strip() == "":
                result = self.arm.rm_movej(target_joints_deg, 30, 0, 0, 1)
                if result != 0: return False
                print("--- 基座旋转完成 ---"); time.sleep(1)
                return True
            else:
                print("--- 操作取消 ---"); return False

    def move_to_pose(self, pose, speed=40, wait=True):
        """第三步：只移动。移动到指定的笛卡尔坐标位姿。"""
        with self.lock:
            block = 1 if wait else 0
            result = self.arm.rm_movej_p(pose, speed, 0, 0, block)
            if result != 0: print(f"!!! 运动指令失败，SDK错误码: {result}")
            return result

    def get_current_pose(self):
        with self.lock:
            ret_code, state_dict = self.arm.rm_get_current_arm_state()
            if ret_code == 0 and 'pose' in state_dict: return state_dict['pose']
            return None

    def go_home(self):
        print("--- 正在返回HOME位置 ---")
        home_pose = [-0.006, -0.135, 0.458, 3.129, 1.530, -1.633]
        self.move_to_pose(home_pose, speed=50)

    def place_object(self, placement_index):
        with self.lock:
            actual_index = placement_index % len(self.placement_poses)
            place_pose = self.placement_poses[actual_index]
            print(f"--- 准备移动到放置点 {actual_index + 1} ---")
            if self.move_to_pose(place_pose, speed=30) != 0: return False
            time.sleep(1)
            print("--- 已到达放置点，释放物体 ---")
            self.set_gripper(1.0, wait=True)
            time.sleep(1)
            print(f"--- 在放置点 {actual_index + 1} 放置完毕 ---")
            return True
