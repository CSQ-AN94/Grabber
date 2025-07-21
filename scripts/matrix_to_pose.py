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
    matrix = np.array([[0.0086592, -0.99987, 0.013909, -0.013926],
 [-0.46063,   0.0083571,     0.88755,     0.10503],
 [   -0.88755,   -0.014092,     -0.4605,     0.42608],
 [          0,           0,           0,           1]])
    
    pose = matrix_to_pose(matrix)
    print_pose(pose, "pose")