# utils/calibration.py - Pseudocode

import numpy as np
import cv2
from external.RM_API2.Demo.RMDemo_Python.RMDemo_Gripper.src.Robotic_Arm.rm_robot_interface import RoboticArm

class Calibration:
    def __init__(self, robot: RoboticArm, T_end_to_camera: np.ndarray):
        # 通过机械臂接口获取DH参数
        ret, dh_dict = robot.rm_get_DH_data()
        if ret != 0:
            raise RuntimeError(f"获取DH参数失败，错误码: {ret}")
        # dh_dict: {'d': [...], 'a': [...], 'alpha': [...], 'offset': [...]}
        self.dh_params = self._convert_dh_dict_to_list(dh_dict)
        self.T_end_to_camera = T_end_to_camera

    @staticmethod
    def _convert_dh_dict_to_list(dh_dict):
        # 转为[[a, alpha, d, theta_offset], ...]，单位转换: alpha/offset需从度转弧度
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
        """
        正运动学计算: 根据关节角度，计算末端相对于基座的变换矩阵。
        """
        T = np.eye(4)
        for i, angle in enumerate(joint_angles):
            a, alpha, d, theta_offset = self.dh_params[i]
            theta = angle + theta_offset
            T = T @ self.dh_transform(a, alpha, d, theta)
        return T # 返回一个 4x4 的 numpy 数组

    def solve_hand_eye_calibration(self, list_of_arm_poses, list_of_marker_poses):
        """
        (这是一个独立的工具脚本，而非主流程的一部分)
        执行手眼标定来求解 T_end_to_camera。
        """
        # 伪代码:
        # 1. 准备两个列表来存储数据:
        #    R_base_to_end, t_base_to_end
        #    R_camera_to_marker, t_camera_to_marker
        
        # 2. 循环N次（N > 10），每次都:
        #    a. 手动移动机械臂到一个新的、不同的姿态。
        #    b. 从arm_controller获取当前的末端姿态矩阵 T_base_to_end，并分解为R和t。
        #    c. 使用相机拍摄标定板，从vision模块获取标定板相对于相机的姿态矩阵 T_camera_to_marker，并分解为R和t。
        #    d. 将这些R和t分别存入上面的列表中。
            
        # 3. 调用OpenCV的标定函数
        #    R_end_to_camera, t_end_to_camera = cv2.calibrateHandEye(
        #        R_base_to_end, t_base_to_end, R_camera_to_marker, t_camera_to_marker, 
        #        method=cv2.CALIB_HAND_EYE_TSAI # 或者其他方法
        #    )
        
        # 4. 将求解出的 R 和 t 组合成一个4x4的 T_end_to_camera 矩阵。
        # 5. 将这个矩阵打印出来，手动保存到 config.ini 文件中。
        pass

    def transform_camera_to_world(self, camera_point, joint_angles, rail_position):
        """
        这是本模块对外的核心API，执行完整的坐标转换链。
        """
        # 伪代码:
        # 1. 计算 T_base_to_end
        #    T_base_to_end = self.calculate_fk(joint_angles)
        
        # 2. 计算 T_rail_to_base
        #    T_rail_to_base = create_translation_matrix_x(rail_position)
        
        # 3. 组合变换矩阵 (实现你的公式)
        #    T_world_to_camera = T_rail_to_base @ T_base_to_end @ self.T_end_to_camera
        
        # 4. 进行坐标点转换
        #    # 将相机坐标下的点 (numpy array, shape (3,)) 转换为齐次坐标 (shape (4,))
        #    camera_point_homogeneous = np.append(camera_point, 1)
        #    # 使用总的变换矩阵进行转换
        #    world_point_homogeneous = T_world_to_camera @ camera_point_homogeneous
        #    # 返回非齐次坐标 (前三个元素)
        #    return world_point_homogeneous[:3]
        # T_base_to_end
        T_base_to_end = self.calculate_fk(joint_angles)
        # T_rail_to_base: 仅X轴平移
        T_rail_to_base = np.eye(4)
        T_rail_to_base[0, 3] = rail_position
        # T_world_to_camera = T_rail_to_base @ T_base_to_end @ T_end_to_camera
        T_world_to_camera = T_rail_to_base @ T_base_to_end @ self.T_end_to_camera
        camera_point_h = np.append(camera_point, 1)
        world_point_h = T_world_to_camera @ camera_point_h
        return world_point_h[:3]