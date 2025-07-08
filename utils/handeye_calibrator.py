import cv2
import numpy as np
import time
import configparser
from scipy.spatial.transform import Rotation
from controllers.arm_controller import ArmController
from sensors.camera_thread import CameraThread
from utils.calibration import Calibration
from utils.state import RobotState

class HandEyeCalibrator:
    """
    一键式自动化手眼标定工具
    参数硬编码以简化调用。如果换标定版，更换参数
    """
    def __init__(self, 
                 arm_controller: ArmController, 
                 camera_thread: CameraThread,
                 robot_state: RobotState,
                 calibration: Calibration, 
                 config_path='config.ini'):
        
        self.arm_controller = arm_controller
        self.camera_thread = camera_thread
        self.robot_state = robot_state  # 用于获取最新图像和机械臂状态
        self.calibration = calibration
        self.config_path = config_path
        self.marker_length = 0.034  # 34mm
        self.marker_separation = 0.0085 # 8.5mm
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
        self.aruco_params = cv2.aruco.DetectorParameters_create()
        self.board = cv2.aruco.GridBoard_create(
            (7, 5), # (列数, 行数)
            self.marker_length, 
            self.marker_separation, 
            self.aruco_dict
        )
        self.camera_matrix = None
        self.dist_coeffs = None

    def _get_arm_pose_matrix(self):
        """
        获取当前机械臂末端在base frame下的位姿矩阵（通过关节角+FK）
        """
        joint_angles = self.arm_controller.get_current_joint_angles()
        if joint_angles is None:
            raise RuntimeError("无法获取机械臂关节角度")
        T_base_to_end = self.calibration.calculate_fk(joint_angles)
        return T_base_to_end

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

        # 硬编码一组可靠的标定姿态
        # 这些姿态来自于拖教
        calibration_poses = [
            [0, 0.2, 1.2, 0, 1.57, 0],     
            [0.3, 0.2, 1.2, 0, 1.57, 0],    
            [-0.3, 0.2, 1.2, 0, 1.57, 0],  
            [0, 0.4, 1.0, 0, 1.57, 0],    
            [0, 0.1, 1.4, 0, 1.57, 0],   
            [0.2, 0.2, 1.2, 0.3, 1.57, 0],
            [-0.2, 0.2, 1.2, -0.3, 1.57, 0],
            [0, 0.3, 1.1, 0, 1.3, 0],
            [0, 0.3, 1.1, 0, 1.8, 0],
            [0, 0, 0, 0, 0, 0],
        ]

        base_to_end_transforms = []
        camera_to_marker_transforms = []
        for i, pose in enumerate(calibration_poses):
            print(f"\nMoving to calibration pose {i+1}/{len(calibration_poses)}...")
            self.arm.move_to_joints(pose)
            time.sleep(3.5) # 确保机械臂完全静止再拍照
            
            color_image, _ = self.robot_state.get_latest_frames()
            if color_image is None:
                print(f"Pose {i+1}: Could not get image. Skipping.")
                continue
            T_base_to_end = self._get_arm_pose_matrix()
            T_camera_to_marker = self._find_pattern_in_image(color_image)
            
            if T_camera_to_marker is not None:
                print(f"Pose {i+1}: Pattern found!")
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
        
        # 将结果自动保存回配置文件
        self._save_matrix_to_config(T_end_to_camera)
        return T_end_to_camera

    def _save_matrix_to_config(self, matrix):
        # 将标定结果持久化
        parser = configparser.ConfigParser()
        parser.read(self.config_path)
        if not parser.has_section('calibration'):
            parser.add_section('calibration')
        matrix_str = str(matrix.tolist())
        parser.set('calibration', 't_end_to_camera', matrix_str)
        with open(self.config_path, 'w') as configfile:
            parser.write(configfile)
        print(f"Calibration matrix successfully saved to {self.config_path}")