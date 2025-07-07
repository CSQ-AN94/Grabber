# utils/calibration.py - Pseudocode

import numpy as np
import cv2
from external.RM_API2.Demo.RMDemo_Python.RMDemo_Gripper.src.Robotic_Arm.rm_robot_interface import RoboticArm

class Calibration:
    """
    只负责运动学与坐标变换。DH参数通过RoboticArm动态获取，T_end_to_camera由标定流程写入config.ini。
    """
    def __init__(self, dh_dict, T_end_to_camera: np.ndarray):
        self.dh_params = self._convert_dh_dict_to_list(dh_dict)
        self.T_end_to_camera = T_end_to_camera

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

    def transform_camera_to_world(self, camera_point, joint_angles, rail_position):
        T_base_to_end = self.calculate_fk(joint_angles)
        T_rail_to_base = np.eye(4)
        T_rail_to_base[0, 3] = rail_position
        T_world_to_camera = T_rail_to_base @ T_base_to_end @ self.T_end_to_camera
        camera_point_h = np.append(camera_point, 1)
        world_point_h = T_world_to_camera @ camera_point_h
        return world_point_h[:3]