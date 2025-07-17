#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
齐次变换矩阵转换为6DOF位姿工具
从4x4齐次变换矩阵(弧度,米)提取move_to_cartesian_pose()需要的pose[x,y,z,roll,pitch,yaw]
"""

import numpy as np
from scipy.spatial.transform import Rotation

def matrix_to_pose(matrix):
    """
    将4x4齐次变换矩阵转换为6DOF位姿
    输入: 4x4 numpy array (旋转矩阵 + 位置向量, 单位: 弧度, 米)
    输出: [x, y, z, roll, pitch, yaw] (单位: 米, 弧度)
    """
    # 提取位置 (米)
    x, y, z = matrix[:3, 3]
    
    # 提取旋转矩阵并转换为欧拉角 (弧度)
    rotation_matrix = matrix[:3, :3]
    rotation = Rotation.from_matrix(rotation_matrix)
    roll, pitch, yaw = rotation.as_euler('xyz')  # XYZ欧拉角顺序
    
    return [x, y, z, roll, pitch, yaw]

def print_pose(pose, name):
    """打印格式化的位姿信息"""
    print(f"{name} = [{pose[0]:.6f}, {pose[1]:.6f}, {pose[2]:.6f}, {pose[3]:.6f}, {pose[4]:.6f}, {pose[5]:.6f}]")

if __name__ == "__main__":
    print("齐次变换矩阵转6DOF位姿工具")
    print("请将下面的矩阵替换为你的实际矩阵（无逗号格式）")
    print("="*50)
    
    # 请将下面的矩阵替换为你的实际矩阵
    matrix = np.array([[ 1.82900436e-01, -7.07810213e-01, -6.82313809e-01, -2.63103000e-01],
 [-1.83120721e-01, -7.06402641e-01,  6.83712008e-01,  2.63116000e-01],
 [-9.65926619e-01, -1.05427802e-04, -2.58816067e-01,  2.43065000e-01],
 [ 0.00000000e+00,  0.00000000e+00,  0.00000000e+00,  1.00000000e+00]])
    
    pose = matrix_to_pose(matrix)
    print_pose(pose, "pose")