#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机械臂和夹爪控制测试
"""

import sys
import os
import time
import numpy as np

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config, ArmConfig
from controllers.arm_controller import ArmController


def test_arm_movement(arm: ArmController, arm_config):
    """测试机械臂运动"""
    print("\n--- [Test] Arm Movement ---")
    print("Moving to scanning pose in joint space...")
    arm.move_to_joints(arm_config.scanning_pose) 
    time.sleep(1.5)
    joints_rad = arm.get_current_joint_angles()
    _, joints_deg = arm.arm.rm_get_joint_degree()
    cartesian_matrix = arm.get_base_to_end_pose_matrix()
    print("Scanning pose in joint space(radian):")
    print(np.array(joints_rad))
    print("Scanning pose in joint space(degree):")
    print(np.array(joints_deg))
    print("Scanning pose in cartesian space:")
    print(cartesian_matrix)
    
    print("Moving to dropoff pose in joint space...")
    arm.move_to_joints(arm_config.dropoff_pose)
    time.sleep(1.5)
    joints_rad = arm.get_current_joint_angles()
    _, joints_deg = arm.arm.rm_get_joint_degree()
    cartesian_matrix = arm.get_base_to_end_pose_matrix()
    print("Dropoff pose in joint space(radian):")
    print(np.array(joints_rad))
    print("Dropoff pose in joint space(degree):")
    print(np.array(joints_deg))
    print("Dropoff pose in cartesian space:")
    print(cartesian_matrix)
    
    print("Moving to zero pose in joint space...")
    arm.move_to_joints(arm_config.zero_pose)
    time.sleep(1.5)
    joints_rad = arm.get_current_joint_angles()
    _, joints_deg = arm.arm.rm_get_joint_degree()
    cartesian_matrix = arm.get_base_to_end_pose_matrix()
    print("Zero pose in joint space(radian):")
    print(np.array(joints_rad))
    print("Zero pose in joint space(degree):")
    print(np.array(joints_deg))
    print("Zero pose in cartesian space:")
    print(cartesian_matrix)

    print("Moving to scanning pose in cartesian space...")
    arm.move_to_cartesian_pose(arm_config.scanning_pose_cartesian)
    time.sleep(1.5)
    joints_rad = arm.get_current_joint_angles()
    _, joints_deg = arm.arm.rm_get_joint_degree()
    cartesian_matrix = arm.get_base_to_end_pose_matrix()
    print("Scanning pose in joint space(radian):")
    print(np.array(joints_rad))
    print("Scanning pose in joint space(degree):")
    print(np.array(joints_deg))
    print("Scanning pose in cartesian space:")
    print(cartesian_matrix)

    print("Moving to dropoff pose in cartesian space...")
    arm.move_to_cartesian_pose(arm_config.dropoff_pose_cartesian)
    time.sleep(1.5)
    joints_rad = arm.get_current_joint_angles()
    _, joints_deg = arm.arm.rm_get_joint_degree()
    cartesian_matrix = arm.get_base_to_end_pose_matrix()
    print("Dropoff pose in joint space(radian):")
    print(np.array(joints_rad))
    print("Dropoff pose in joint space(degree):")
    print(np.array(joints_deg))
    print("Dropoff pose in cartesian space:")
    print(cartesian_matrix)

    print("Moving to zero pose in cartesian space...")
    arm.move_to_cartesian_pose(arm_config.zero_pose_cartesian)
    time.sleep(1.5)
    joints_rad = arm.get_current_joint_angles()
    _, joints_deg = arm.arm.rm_get_joint_degree()
    cartesian_matrix = arm.get_base_to_end_pose_matrix()
    print("Zero pose in joint space(radian):")
    print(np.array(joints_rad))
    print("Zero pose in joint space(degree):")
    print(np.array(joints_deg))
    print("Zero pose in cartesian space:")
    print(cartesian_matrix)

    print("--- Arm Movement Test PASSED ---")


def test_gripper_control(arm: ArmController):
    """测试夹爪控制"""
    print("\n--- [Test] Gripper Control ---")
    print("Opening gripper...")
    arm.set_gripper_openness(1.0)
    print("Closing gripper...")
    arm.set_gripper_openness(0.0)
    print("--- Gripper Control Test PASSED ---")


def test_tcp_precision_movement(arm: ArmController, arm_config: ArmConfig):
    """测试TCP精细运动"""
    print("\n--- [Test] TCP Precision Movement ---")
    
    # 检查是否配置了TCP
    if all(abs(x) < 1e-6 for x in arm_config.tcp_pose):
        print("未配置TCP偏移，跳过TCP测试")
        return
    
    print(f"配置的TCP偏移: {arm_config.tcp_pose}")
    
    # 移动到扫描位置作为起点
    print("Moving to scanning pose as starting position...")
    arm.move_to_joints(arm_config.scanning_pose)
    time.sleep(2)
    
    # 获取当前笛卡尔位姿
    current_matrix = arm.get_base_to_end_pose_matrix()
    if current_matrix is None:
        print("无法获取当前位姿，跳过TCP测试")
        return
    
    # 提取当前位置和姿态
    from scipy.spatial.transform import Rotation
    current_pos = current_matrix[:3, 3]
    current_rot = Rotation.from_matrix(current_matrix[:3, :3]).as_euler('ZYX')
    
    print(f"当前TCP位置: [{current_pos[0]:.3f}, {current_pos[1]:.3f}, {current_pos[2]:.3f}] m")
    
    # 定义一系列安全的小幅度移动来测试TCP精度
    # 注意：这些是相对于当前位置的小偏移
    test_moves = [
        ("TCP上移5cm", [current_pos[0], current_pos[1], current_pos[2] + 0.05, 
                       current_rot[0], current_rot[1], current_rot[2]]),
        ("TCP右移3cm", [current_pos[0] + 0.03, current_pos[1], current_pos[2] + 0.05, 
                       current_rot[0], current_rot[1], current_rot[2]]),
        ("TCP前移2cm", [current_pos[0] + 0.03, current_pos[1] + 0.02, current_pos[2] + 0.05, 
                       current_rot[0], current_rot[1], current_rot[2]]),
        ("回到起始位置", [current_pos[0], current_pos[1], current_pos[2], 
                      current_rot[0], current_rot[1], current_rot[2]]),
    ]
    
    for move_name, target_pose in test_moves:
        print(f"\n{move_name}:")
        print(f"  目标位置: [{target_pose[0]:.3f}, {target_pose[1]:.3f}, {target_pose[2]:.3f}] m")
        
        # 使用较慢的速度进行精细运动
        result = arm.move_to_cartesian_pose(target_pose, speed=20, wait=True)
        
        if result == 0:
            print(f"  ✅ {move_name} 成功")
            time.sleep(1.5)
            
            # 验证实际到达位置
            actual_matrix = arm.get_base_to_end_pose_matrix()
            if actual_matrix is not None:
                actual_pos = actual_matrix[:3, 3]
                error = np.linalg.norm(actual_pos - np.array(target_pose[:3]))
                print(f"  实际位置: [{actual_pos[0]:.3f}, {actual_pos[1]:.3f}, {actual_pos[2]:.3f}] m")
                print(f"  位置误差: {error*1000:.1f} mm")
            else:
                print("  ⚠️ 无法获取实际位置验证")
        else:
            print(f"  ❌ {move_name} 失败，错误码: {result}")
            break
    
    print("--- TCP Precision Movement Test COMPLETED ---")


def run_arm_tests():
    """运行所有机械臂测试"""
    print("=== 机械臂和夹爪测试 ===")
    
    try:
        # 加载配置
        app_config = load_config()
        
        # 初始化机械臂控制器
        arm = ArmController(app_config.connections, app_config.arm, app_config.gripper)
        print("机械臂控制器初始化成功")
        
        # 运行测试
        while True:
            print("\n" + "="*40)
            print("机械臂测试菜单")
            print("="*40)
            print("1. 测试机械臂运动")
            print("2. 测试夹爪控制")
            print("3. 测试TCP精细运动")
            print("4. 运行所有测试")
            print("Q. 退出")
            
            choice = input("请选择: ").upper()
            
            if choice == '1':
                test_arm_movement(arm, app_config.arm)
            elif choice == '2':
                test_gripper_control(arm)
            elif choice == '3':
                test_tcp_precision_movement(arm, app_config.arm)
            elif choice == '4':
                test_arm_movement(arm, app_config.arm)
                test_gripper_control(arm)
                test_tcp_precision_movement(arm, app_config.arm)
            elif choice == 'Q':
                break
            else:
                print("无效选择，请重试")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"机械臂测试失败: {e}")
    finally:
        print("机械臂测试结束")


if __name__ == "__main__":
    run_arm_tests()