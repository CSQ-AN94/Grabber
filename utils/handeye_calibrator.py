import cv2
import numpy as np
import time
import configparser
from scipy.spatial.transform import Rotation

# ANNOTATION: 确保这些导入路径在你的项目结构中是正确的
from controllers.arm_controller import ArmController
# from utils.state import RobotState  # 移除，避免循环依赖
from sensors.camera_thread import CameraThread

class HandEyeCalibrator:
    """
    一键式自动化手眼标定工具 (更新版)。
    参数已根据实际情况硬编码，以简化调用。
    """
    def __init__(self, arm_controller: ArmController, robot_state, camera_thread: CameraThread, config_path='config.ini'):
        self.arm = arm_controller
        self.state = robot_state
        self.camera_thread = camera_thread
        self.config_path = config_path
        self.marker_length = 0.034  # 34mm
        self.marker_separation = 0.0085 # 8.5mm
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_6X6_250)
        self.aruco_params = cv2.aruco.DetectorParameters()
        self.board = cv2.aruco.GridBoard(
            (7, 5), # (列数, 行数)
            self.marker_length, 
            self.marker_separation, 
            self.aruco_dict
        )
        
        self.camera_matrix = None
        self.dist_coeffs = None

    def _get_arm_pose_matrix(self):
        # ANNOTATION: 此函数逻辑不变，它负责获取机械臂末端位姿。
        pose = self.arm.get_current_end_effector_pose()
        position = np.array(pose[:3])
        rotation = Rotation.from_euler('xyz', pose[3:], degrees=False).as_matrix()
        T = np.eye(4)
        T[:3, :3] = rotation
        T[:3, 3] = position
        return T

    def _find_pattern_in_image(self, image):
        # ANNOTATION: 此函数逻辑不变，它负责在图像中定位标定板。
        corners, ids, _ = cv2.aruco.detectMarkers(image, self.aruco_dict, parameters=self.aruco_params)
        if ids is not None and len(ids) > 4: # CHANGED: 增加一个健壮性检查，要求至少看到4个标记
            retval, rvec, tvec = cv2.aruco.estimatePoseBoard(corners, ids, self.board, self.camera_matrix, self.dist_coeffs, rvec=None, tvec=None)
            if retval > 0:
                R, _ = cv2.Rodrigues(rvec)
                T = np.eye(4)
                T[:3, :3] = R
                T[:3, 3] = tvec.flatten()
                return T
        return None

    def run_calibration_process(self):
        """
        执行完整的手眼标定流程。标定姿态已硬编码。
        """
        print("--- Starting Automated Hand-Eye Calibration ---")
        
        # ANNOTATION: 从相机线程获取精确的内参，这是所有计算的基础。
        self.camera_matrix, self.dist_coeffs = self.camera_thread.get_camera_intrinsics()
        if self.camera_matrix is None:
            print("Error: Could not get camera intrinsics. Aborting.")
            return

        # CHANGED: 硬编码一组可靠的标定姿态 (关节角度，单位：弧度)
        # 这些姿态旨在从不同角度和距离观察标定板，同时确保视野良好。
        calibration_poses = [
            [0, 0.2, 1.2, 0, 1.57, 0],       # 姿态1: 靠近，俯视
            [0.3, 0.2, 1.2, 0, 1.57, 0],     # 姿态2: 向右平移
            [-0.3, 0.2, 1.2, 0, 1.57, 0],    # 姿态3: 向左平移
            [0, 0.4, 1.0, 0, 1.57, 0],       # 姿态4: 向上平移，稍远
            [0, 0.1, 1.4, 0, 1.57, 0],       # 姿态5: 向下平移，稍近
            [0.2, 0.2, 1.2, 0.3, 1.57, 0],   # 姿态6: 带一点旋转
            [-0.2, 0.2, 1.2, -0.3, 1.57, 0],  # 姿态7: 带一点反向旋转
            [0, 0.3, 1.1, 0, 1.3, 0],        # 姿态8: 从一个斜角观察
            [0, 0.3, 1.1, 0, 1.8, 0],        # 姿态9: 从另一个斜角观察
            [0, 0, 0, 0, 0, 0],              # 姿态10: 回到零位附近（如果能看到板）
        ]

        arm_poses = []
        marker_poses = []
        for i, pose in enumerate(calibration_poses):
            print(f"\nMoving to calibration pose {i+1}/{len(calibration_poses)}...")
            self.arm.move_to_joints(pose)
            time.sleep(3.5) # ANNOTATION: 稍微增加等待时间，确保机械臂完全静止
            
            T_base_gripper = self._get_arm_pose_matrix()
            color, _ = self.state.get_latest_frames()
            
            if color is None:
                print(f"Pose {i+1}: Could not get image. Skipping.")
                continue

            T_cam_marker = self._find_pattern_in_image(color)
            
            if T_cam_marker is not None:
                print(f"Pose {i+1}: Pattern found!")
                arm_poses.append(T_base_gripper)
                marker_poses.append(T_cam_marker)
            else:
                print(f"Pose {i+1}: Pattern NOT found. Skipping.")
        
        # ANNOTATION: 逻辑不变，但现在更健壮
        if len(arm_poses) < 5:
            print("Error: Not enough valid poses collected. Need at least 5. Aborting.")
            return

        print(f"\nCollected {len(arm_poses)} valid data pairs. Solving AX=XB equation...")
        R_gripper2base = [T[:3, :3] for T in arm_poses]
        t_gripper2base = [T[:3, 3] for T in arm_poses]
        R_target2cam = [T[:3, :3] for T in marker_poses]
        t_target2cam = [T[:3, 3] for T in marker_poses]

        R_end2cam, t_end2cam = cv2.calibrateHandEye(
            R_gripper2base, t_gripper2base,
            R_target2cam, t_target2cam,
            method=cv2.CALIB_HAND_EYE_TSAI
        )
        
        T_end2cam = np.eye(4)
        T_end2cam[:3, :3] = R_end2cam
        T_end2cam[:3, 3] = t_end2cam.squeeze()
        
        print("\nHand-Eye Calibration successful!")
        print("Resulting T_end_to_camera (4x4):\n", T_end2cam)
        
        self._save_matrix_to_config(T_end2cam)
        return T_end2cam

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