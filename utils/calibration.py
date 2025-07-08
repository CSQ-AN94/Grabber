# utils/calibration.py - Pseudocode

import numpy as np
import cv2
from external.RM_API2.Demo.RMDemo_Python.RMDemo_Gripper.src.Robotic_Arm.rm_robot_interface import RoboticArm

class Calibration:
    """
    负责运动学与坐标变换。DH参数通过RoboticArm获取，T_end_to_camera由标定流程写入config.ini。
    """
    def __init__(self, dh_dict, T_end_to_camera, camera_matrix=None, distortion_coeffs=None):
        self.dh_params = self._convert_dh_dict_to_list(dh_dict)
        self.T_end_to_camera = T_end_to_camera
        self.camera_matrix = camera_matrix
        self.distortion_coeffs = distortion_coeffs

    @staticmethod
    def _convert_dh_dict_to_list(dh_dict):
        a = dh_dict['a']
        alpha = [np.deg2rad(x) for x in dh_dict['alpha']]
        d = dh_dict['d']
        offset = [np.deg2rad(x) for x in dh_dict['offset']]
        return [[a[i], alpha[i], d[i], offset[i]] for i in range(len(a))]

    @staticmethod
    def dh_transform(a, alpha, d, theta):
        ca, sa = np.cos(alpha), np.sin(alpha)
        ct, st = np.cos(theta), np.sin(theta)
        return np.array([
            [ct, -st*ca,  st*sa, a*ct],
            [st,  ct*ca, -ct*sa, a*st],
            [0,     sa,     ca,    d],
            [0,      0,      0,    1]
        ])

    def calculate_fk(self, joint_angles):
        T = np.eye(4)
        for i, angle in enumerate(joint_angles):
            a, alpha, d, theta_offset = self.dh_params[i]
            theta = angle + theta_offset
            T = T @ self.dh_transform(a, alpha, d, theta)
        return T

    def transform_pixel_to_world(self, pixel_coords, depth_map_in_meters, joint_angles, rail_position):
        """
        像素到世界坐标转换流程
        
        Args:
            pixel_coords (tuple): (u, v) color像素坐标。
            depth_map_in_meters (np.ndarray): 硬件对齐后的、单位为米的深度图。
            joint_angles (list): 机械臂6个关节的角度 (弧度)。
            rail_position (float): 导轨的当前位置 (米)。

        Returns:
            np.ndarray: 在世界坐标系下的3D点 [x, y, z]，如果无效则返回None。
        """
        # 检查相机参数是否已初始化
        if self.camera_matrix is None or self.distortion_coeffs is None:
            raise ValueError("Calibration object not initialized with camera intrinsics.")
        # 从深度图中获取像素对应的深度值 (单位：米)
        u, v = int(pixel_coords[0]), int(pixel_coords[1])
        Z_camera = depth_map_in_meters[v, u]
        if Z_camera <= 0:  # 深度值为0或负数是无效值
            return None
        # 输入需要是 (N, 1, 2) 的浮点数数组
        distorted_pixel = np.array([[[float(u), float(v)]]], dtype=np.float32)
        # OpenCV计算去畸变后的像素坐标
        # P=self.camera_matrix 确保了输出的坐标尺度与原始内参一致
        undistorted_pixel = cv2.undistortPoints(distorted_pixel, self.camera_matrix, self.distortion_coeffs, P=self.camera_matrix)
        u_undistorted, v_undistorted = undistorted_pixel[0, 0]
        # 使用标准的相机反投影公式，计算在相机坐标系下的 (X, Y)
        # 因为我们使用了对齐后的深度图，所以这里可以直接使用彩色相机的内参
        fx = self.camera_matrix[0, 0]
        fy = self.camera_matrix[1, 1]
        cx = self.camera_matrix[0, 2]
        cy = self.camera_matrix[1, 2]
        
        X_camera = (u_undistorted - cx) * Z_camera / fx
        Y_camera = (v_undistorted - cy) * Z_camera / fy
        
        # 现在有在相机坐标系下的完整3D点
        point_in_camera_homogeneous = np.array([X_camera, Y_camera, Z_camera, 1])

        # 使用运动学和手眼标定矩阵，将其转换到世界坐标系
        # 正运动学计算基座到末端的变换 T_base_to_end
        T_base_to_end = self.calculate_fk(joint_angles)
        # 结合手眼矩阵得到基座到相机坐标系的变换 T_base_to_camera
        T_base_to_camera = T_base_to_end @ self.T_end_to_camera
        # 考虑导轨的平移，得到世界到相机的变换 T_world_to_camera
        T_world_to_base = np.eye(4)
        T_world_to_base[0, 3] = rail_position # 假设导轨沿X轴移动
        T_world_to_camera = T_world_to_base @ T_base_to_camera
        
        # 最终的坐标变换
        point_in_world_homogeneous = T_world_to_camera @ point_in_camera_homogeneous
        return point_in_world_homogeneous[:3]