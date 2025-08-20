# utils/calibration.py

import numpy as np
import cv2

class Calibration:
    """
    坐标变换核心类 - 简洁版本
    
    职责：像素坐标 → 基座坐标系3D点
    """
    def __init__(self, camera_matrix, distortion_coeffs):
        """
        Args:
            camera_matrix (np.ndarray): 相机内参矩阵 K
            distortion_coeffs (np.ndarray): 相机畸变系数
        """
        self.K = camera_matrix
        self.dist = distortion_coeffs
        self.T_cam_end = np.array([
            [ 0,  1,  0, -0.08289],
            [-1,  0,  0,  0.02375],
            [ 0,  0,  1, -0.12   ],
            [ 0,  0,  0,  1.     ]
        ])
    
    def get_point_base(self, u, v, d, T_end_base):
        """
        像素坐标转基座坐标
        
        Args:
            u (float): 像素坐标 x
            v (float): 像素坐标 y
            d (float): 深度值
            T_end_base (np.ndarray): end_effector到base的4x4变换矩阵
            
        Returns:
            np.ndarray: 基座坐标系中的3D点 [x, y, z]
        """
        if d <= 0:
            return None
            
        # 1. 像素去畸变
        undist = cv2.undistortPoints(
            np.array([[[u, v]]], dtype=np.float32), 
            self.K, self.dist, P=self.K
        )[0, 0]
        
        # 2. 反投影到相机坐标系
        fx, fy, cx, cy = self.K[0,0], self.K[1,1], self.K[0,2], self.K[1,2]
        cam_x = (undist[0] - cx) * d / fx
        cam_y = (undist[1] - cy) * d / fy
        cam_z = d
        
        # 3. 构造相机坐标系下目标点的变换矩阵（参考reference做法）
        T_cam_target = np.eye(4)
        T_cam_target[:3, 3] = [cam_x, cam_y, cam_z]
        
        # 4. 坐标变换链：base ← end_effector ← cam ← target
        T_base_target = T_end_base @ self.T_cam_end @ T_cam_target
        # 5. 提取基座坐标系中的3D位置
        return T_base_target[:3, 3]