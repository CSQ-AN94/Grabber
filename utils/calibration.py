# utils/calibration.py

import numpy as np
import cv2

class Calibration:
    """
    负责坐标变换。T_end_to_camera由标定流程写入config.ini。
    此类不再负责运动学计算。
    """
    def __init__(self, T_end_to_camera, camera_matrix=None, distortion_coeffs=None):
        self.T_end_to_camera = T_end_to_camera
        self.K = camera_matrix
        self.dist = distortion_coeffs

    def transform_pixel_to_world(self, pixel_coords, depth_in_meters, T_base_to_end, rail_position=0.0):
        """
        像素到世界坐标转换流程
        
        Args:
            pixel_coords (tuple): (u, v) color像素坐标。
            depth_in_meters (float): 该像素点的深度值，单位为米。
            T_base_to_end (np.ndarray): 机械臂基座到末端的4x4变换矩阵。
            rail_position (float): 导轨的当前位置 (米)。

        Returns:
            np.ndarray: 在世界坐标系下的3D点 [x, y, z]，如果无效则返回None。
        """
        if self.K is None or self.dist is None:
            raise ValueError("Calibration object not initialized with camera intrinsics.")
        
        if depth_in_meters <= 0:
            return None

        u, v = int(pixel_coords[0]), int(pixel_coords[1])
        Z_camera = depth_in_meters
        
        # 1. 对像素点进行去畸变
        distorted_pixel = np.array([[[float(u), float(v)]]], dtype=np.float32)
        # P=self.K 确保了输出的坐标尺度与原始内参一致
        undistorted_pixel = cv2.undistortPoints(distorted_pixel, self.K, self.dist, P=self.K)
        u_undistorted, v_undistorted = undistorted_pixel[0, 0]

        # 2. 使用标准的相机反投影公式，计算在相机坐标系下的 (X, Y)
        fx = self.K[0, 0]
        fy = self.K[1, 1]
        cx = self.K[0, 2]
        cy = self.K[1, 2]
        
        X_camera = (u_undistorted - cx) * Z_camera / fx
        Y_camera = (v_undistorted - cy) * Z_camera / fy
        
        point_in_camera_homogeneous = np.array([X_camera, Y_camera, Z_camera, 1])

        # 3. 核心变换：
        T_base_to_camera = T_base_to_end @ self.T_end_to_camera
        T_world_to_base = np.eye(4)
        T_world_to_base[0, 3] = rail_position
        T_world_to_camera = T_world_to_base @ T_base_to_camera
        
        # 4. 将相机坐标系下的点变换到世界坐标系
        point_in_world_homogeneous = T_world_to_camera @ point_in_camera_homogeneous
        
        return point_in_world_homogeneous[:3]
