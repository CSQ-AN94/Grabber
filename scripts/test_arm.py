#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
机械臂和夹爪控制测试
"""

import sys
import os
import time

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from controllers.arm_controller import ArmController


def test_arm_movement(arm: ArmController, arm_config):
    """测试机械臂运动"""
    print("\n--- [Test] Arm Movement ---")
    print("Moving to scanning pose...")
    arm.move_to_joints(arm_config.scanning_pose) 
    time.sleep(1.5)
    print("Scanning pose in joint space:", arm.get_current_joint_angles())
    print("Scanning pose in cartesian space:", arm.get_base_to_end_pose_matrix())
    
    print("Moving to dropoff pose...")
    arm.move_to_joints(arm_config.dropoff_pose)
    time.sleep(1.5)
    print("Dropoff pose in joint space:", arm.get_current_joint_angles())
    print("Dropoff pose in cartesian space:", arm.get_base_to_end_pose_matrix())
    
    print("Moving to zero pose...")
    arm.move_to_joints(arm_config.zero_pose)
    time.sleep(1.5)
    print("Zero pose in joint space:", arm.get_current_joint_angles())
    print("Zero pose in cartesian space:", arm.get_base_to_end_pose_matrix())
    print("--- Arm Movement Test PASSED ---")


def test_gripper_control(arm: ArmController):
    """测试夹爪控制"""
    print("\n--- [Test] Gripper Control ---")
    print("Opening gripper...")
    arm.set_gripper_openness(1.0)
    print("Closing gripper...")
    arm.set_gripper_openness(0.0)
    print("--- Gripper Control Test PASSED ---")


def run_arm_tests():
    """运行所有机械臂测试"""
    print("=== 机械臂和夹爪测试 ===")
    
    try:
        # 加载配置
        app_config = load_config("config.ini")
        
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
            print("3. 运行所有测试")
            print("Q. 退出")
            
            choice = input("请选择: ").upper()
            
            if choice == '1':
                test_arm_movement(arm, app_config.arm)
            elif choice == '2':
                test_gripper_control(arm)
            elif choice == '3':
                test_arm_movement(arm, app_config.arm)
                test_gripper_control(arm)
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