import cv2
import numpy as np
import time
import configparser
from controllers.arm_controller import ArmController
from sensors.camera_thread import CameraThread
from utils.state import WorldState

class HandEyeCalibrator:
    """
    一键式自动化手眼标定工具
    参数硬编码以简化调用。如果换标定版，更换参数
    """
    def __init__(self, 
                 arm_controller: ArmController, 
                 camera_thread: CameraThread,
                 world_state: WorldState):
        
        self.arm_controller = arm_controller
        self.camera_thread = camera_thread
        self.world_state = world_state  # 用于获取最新图像和机械臂状态
        self.marker_length = 0.034  # 34mm
        self.marker_separation = 0.0085 # 8.5mm
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.board = cv2.aruco.GridBoard(
            (7, 3), # (列数, 行数)
            self.marker_length, 
            self.marker_separation, 
            self.aruco_dict
        )
        self.camera_matrix = None
        self.dist_coeffs = None

    def _find_pattern_in_image(self, image):
        # 在图像中定位标定板
        corners, ids, _ = cv2.aruco.detectMarkers(image, self.aruco_dict, parameters=self.aruco_params)
        if ids is not None and len(ids) > 4: # 至少看到4个标记才估计标定板位姿
            retval, rvec, tvec = cv2.aruco.estimatePoseBoard(corners, ids, self.board, self.camera_matrix, self.dist_coeffs, rvec=None, tvec=None)
            if retval > 0:
                R, _ = cv2.Rodrigues(rvec)
                T_camera_to_marker = np.eye(4)
                T_camera_to_marker[:3, :3] = R
                T_camera_to_marker[:3, 3] = tvec.flatten()
                return T_camera_to_marker
        return None
    
    def run_calibration_process(self):
        """
        执行完整的手眼标定流程
        """
        print("--- Starting Automated Hand-Eye Calibration ---")
        
        # 从相机线程获取精确的内参（已通过Matlab cameraCalibrator确认）
        self.camera_matrix, self.dist_coeffs = self.camera_thread.get_camera_intrinsics()
        if self.camera_matrix is None:
            print("Error: Could not get camera intrinsics. Aborting.")
            return

        # 硬编码一组标定姿态（单位：度）
        # 这些姿态来自于拖教
        calibration_poses_deg = [
            [86.07, 37.76, -129.4, -1.76, -1.58, -178.83],
            [50.44, 42.61, -120.4, 68.72, -49.23, -179.59],
            [49.75, 3.33, -19.68, 37.31, -106.43, -182.71],
            [56.23, 52.17, -115.78, 43.81, -41.45, -215.57],
            [139.38, 62.76, -114.68, -53.82, -65.86, -137.62],
            [92.92, 73.62, -128.36, -2.7, -46.37, -178.22],
            [142.34, -63.58, 67.98, -81.6, -99.39, -195.22],
            [29.45, -67.17, 74.48, 78.02, -104.48, -157.38],
            [18.55, -41.07, 41.49, 83.05, -117.11, -130.07],
            [17.05, -20.55, -49.04, 96.64, -108.42, -164.48],
            [-56.56, -14.48, 94.95, 106.97, -56.71, -108.64],
            [-84.03, -19.96, 125.28, 44.45, -27.95, -108.67],
            [7.8, -15.82, -56.08, 92.68, -108.5, -108.66],
            
        ]
        
        base_to_end_transforms = []
        camera_to_marker_transforms = []
        for i, pose in enumerate(calibration_poses_deg):
            print(f"\nMoving to calibration pose {i+1}/{len(calibration_poses_deg)}...")
            self.arm_controller.move_to_joints(pose)
            time.sleep(3.5) # 确保机械臂完全静止再拍照
            
            color_image, _ = self.camera_thread.get_latest_frames()
            if color_image is None:
                print(f"Pose {i+1}: Could not get image. Skipping.")
                continue
            T_base_to_end = self.arm_controller.get_base_to_end_pose_matrix()
            print(f"T_base_to_end:{T_base_to_end}")
            T_camera_to_marker = self._find_pattern_in_image(color_image)
            
            if T_camera_to_marker is not None:
                print(f"Pose {i+1}: Pattern found\nT_camera_to_marker:{T_camera_to_marker}\n")
                base_to_end_transforms.append(T_base_to_end)
                camera_to_marker_transforms.append(T_camera_to_marker)
            else: 
                print(f"Pose {i+1}: Pattern NOT found. Skipping.")
        
        # 确保收集到足够的有效位姿
        if len(base_to_end_transforms) < 5:
            print("Error: Not enough valid poses collected. Need at least 5. Aborting.")
            return

        print(f"\nCollected {len(base_to_end_transforms)} valid data pairs. Solving AX=XB equation...")
    
        R_base_to_end = [T[:3, :3] for T in base_to_end_transforms]
        t_base_to_end = [T[:3, 3] for T in base_to_end_transforms]
        R_marker_to_camera = [np.linalg.inv(T[:3, :3]) for T in camera_to_marker_transforms]
        t_marker_to_camera = [-np.linalg.inv(T[:3, :3]) @ T[:3, 3] for T in camera_to_marker_transforms]

        # 调用OpenCV的核心函数
        R_end_to_camera, t_end_to_camera = cv2.calibrateHandEye(
            R_base_to_end, t_base_to_end,
            R_marker_to_camera, t_marker_to_camera,
            method=cv2.CALIB_HAND_EYE_TSAI
        )
        
        # 组合成最终的4x4变换矩阵
        T_end_to_camera = np.eye(4)
        T_end_to_camera[:3, :3] = R_end_to_camera
        T_end_to_camera[:3, 3] = t_end_to_camera.squeeze()
        
        print("\nHand-Eye Calibration successful!")
        print("Resulting T_end_to_camera (4x4 Transformation Matrix):\n", T_end_to_camera)
        return T_end_to_camera