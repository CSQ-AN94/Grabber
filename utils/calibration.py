# utils/calibration.py

import numpy as np
import cv2

class Calibration:
    """
    坐标变换核心类
    
    职责：将相机坐标系下发现的物体坐标精确转换到基座坐标系
    手眼标定：T_end_to_camera 表示 end_effector到相机光心的变换关系
    输出坐标：直接是end_effector应到达的位置，无需额外offset
    """
    def __init__(self, T_end_to_camera, camera_matrix=None, distortion_coeffs=None):
        """
        Args:
            T_end_to_camera (np.ndarray): end_effector到相机光心的4x4变换矩阵
            camera_matrix (np.ndarray): 相机内参矩阵 K
            distortion_coeffs (np.ndarray): 相机畸变系数
        """
        self.T_end_to_camera = T_end_to_camera
        self.K = camera_matrix
        self.dist = distortion_coeffs

    def transform_pixel_to_world(self, pixel_coords, depth_in_meters, T_base_to_end_effector):
        """
        像素坐标到基座坐标系转换
        
        变换链：基座 ← end_effector ← 相机 ← 目标点
        手眼标定：T_end_to_camera 表示 end_effector到相机的变换矩阵
        
        Args:
            pixel_coords (tuple): (u, v) color像素坐标
            depth_in_meters (float): 该像素点的深度值，单位为米  
            T_base_to_end_effector (np.ndarray): 基座到end_effector的4x4变换矩阵

        Returns:
            np.ndarray: 基座坐标系下的3D点 [x, y, z]，end_effector应到达的位置
        """
        if self.K is None or self.dist is None:
            raise ValueError("Camera intrinsics not initialized")
        
        if depth_in_meters <= 0:
            return None

        # 1. 像素坐标去畸变
        u, v = float(pixel_coords[0]), float(pixel_coords[1])
        distorted_pixel = np.array([[[u, v]]], dtype=np.float32)
        undistorted_pixel = cv2.undistortPoints(distorted_pixel, self.K, self.dist, P=self.K)
        u_undist, v_undist = undistorted_pixel[0, 0]

        # 2. 反投影到相机坐标系（构建目标点）
        fx, fy = self.K[0, 0], self.K[1, 1] 
        cx, cy = self.K[0, 2], self.K[1, 2]
        
        X_cam = (u_undist - cx) * depth_in_meters / fx
        Y_cam = (v_undist - cy) * depth_in_meters / fy
        Z_cam = depth_in_meters
        
        # 构建相机坐标系下目标点的变换矩阵
        T_cam_target = np.eye(4)
        T_cam_target[:3, 3] = [X_cam, Y_cam, Z_cam]

        # 3. 坐标变换链
        # 参考：T_base_touch_target = T_base_tool0_scan @ HAND_EYE_T_tool0_cam @ T_cam_grasp
        # 
        # T_base_to_end_effector: 基座到end_effector的变换（相当于T_base_tool0_scan）
        # self.T_end_to_camera: end_effector到相机的变换（相当于HAND_EYE_T_tool0_cam）  
        # T_cam_target: 相机坐标系下的目标变换（相当于T_cam_grasp）
        T_base_target = T_base_to_end_effector @ self.T_end_to_camera @ T_cam_target
        
        # 4. 提取目标位置（基座坐标系）
        target_position = T_base_target[:3, 3]
        
        return target_position
