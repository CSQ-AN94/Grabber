#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
手眼标定测试
"""

import sys
import os
import time
import threading
import cv2
import numpy as np
from scipy.spatial.transform import Rotation

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from utils.state import WorldState
from utils.calibration import Calibration
from utils.handeye_calibrator import HandEyeCalibrator
from sensors.camera_thread import CameraThread
from controllers.arm_controller import ArmController


def run_handeye_calibration(arm: ArmController, cam_thread: CameraThread, state: WorldState):
    """运行完整的手眼标定过程"""
    print("\n" + "*"*60)
    print("WARNING: Starting Hand-Eye Calibration Process.")
    print("Please ensure:")
    print("1. The calibration board is rigidly fixed in the workspace.")
    print("2. Lighting is uniform and without glare.")
    print("3. The calibration poses in `handeye_calibrator.py` are safe and provide diverse views.")
    print("*"*60)
    
    if input("Proceed? (y/n): ").lower() != 'y':
        print("Calibration cancelled.")
        return
        
    try:
        calibrator = HandEyeCalibrator(arm, cam_thread, state)
        calibrator.run_calibration_process()
        print("\n--- Hand-Eye Calibration Process Finished ---")
        print("Please check `config.ini` for the updated `T_end_to_camera` matrix.")
        return True
    except Exception as e:
        print(f"手眼标定失败: {e}")
        return False


def collect_calibration_poses_interactively(arm: ArmController, exit_event: threading.Event):
    """交互式采集标定姿态"""
    print("\n" + "*"*60)
    print("Interactive Pose Collection Tool")
    print("1. Manually move the arm to a desired pose (using teach mode or another script).")
    print("2. Ensure the calibration board is fully visible in the 'Color Feed' window.")
    print("3. Press 'c' in the OpenCV window to capture and print the pose.")
    print("4. Press 'q' in the OpenCV window to quit this mode.")
    print("*"*60)

    # 确保显示窗口在前台
    cv2.imshow('Color Feed', np.zeros((480, 640, 3), dtype=np.uint8)) 

    captured_poses = []
    while not exit_event.is_set():
        key = cv2.waitKey(100) & 0xFF
        
        if key == ord('q'):
            print("Quitting pose collection mode.")
            break
        elif key == ord('c'):
            print("\n--- Capturing Pose ---")
            # 获取关节角度
            joint_angles = arm.get_current_joint_angles()
            if joint_angles is None:
                print("ERROR: Could not get joint angles.")
                continue
            
            # 计算笛卡尔空间坐标 (需要FK)
            try:
                temp_dh = arm.arm.rm_get_DH_data()[1]
                fk_solver = Calibration(temp_dh, np.eye(4))
                pose_matrix = fk_solver.calculate_fk(joint_angles)
                
                # 提取位置(m)和欧拉角(rad)
                position_m = pose_matrix[:3, 3]
                euler_rad = Rotation.from_matrix(pose_matrix[:3, :3]).as_euler('xyz')
                
                # 转换为对人类友好的格式
                joint_angles_deg = [round(np.rad2deg(j), 2) for j in joint_angles]
                position_mm = [round(p * 1000, 2) for p in position_m]
                
                print(f"Joints (deg): {joint_angles_deg},")
                print(f"Pose (mm, rad): pos=({position_mm[0]}, {position_mm[1]}, {position_mm[2]}) rot=({round(euler_rad[0],2)}, {round(euler_rad[1],2)}, {round(euler_rad[2],2)})")
                
                captured_poses.append(joint_angles_deg)
                
            except Exception as e:
                print(f"ERROR: Failed to calculate pose: {e}")

    print("\n--- Captured Poses for Calibration ---")
    print("Please copy the following list into `handeye_calibrator.py`:")
    for pose in captured_poses:
        print(f"    {pose},")
    
    cv2.destroyAllWindows()
    return captured_poses


def test_calibration_matrix(calibration: Calibration):
    """测试当前标定矩阵"""
    print("\n--- [Test] Current Calibration Matrix ---")
    
    if not calibration:
        print("No calibration object available")
        return False
    
    try:
        # 显示当前标定参数
        print("Current calibration parameters:")
        print(f"DH Parameters: {len(calibration.dh_params)} joints")
        print(f"T_end_to_camera matrix:\n{calibration.T_end_to_camera}")
        
        if hasattr(calibration, 'K') and calibration.K is not None:
            print(f"Camera intrinsics K:\n{calibration.K}")
        
        if hasattr(calibration, 'dist') and calibration.dist is not None:
            print(f"Distortion coefficients: {calibration.dist}")
        
        print("--- Calibration Matrix Test PASSED ---")
        return True
        
    except Exception as e:
        print(f"Calibration Matrix Test FAILED: {e}")
        return False


def run_calibration_tests():
    """运行所有标定测试"""
    print("=== 手眼标定测试 ===")
    
    exit_event = threading.Event()
    cam_thread = None
    
    try:
        # 加载配置
        app_config = load_config("config.ini")
        state = WorldState()
        
        # 启动相机线程
        cam_thread = CameraThread(state, None)
        cam_thread.start()
        print("相机线程启动成功")
        
        # 等待相机稳定
        print("等待相机初始化...")
        time.sleep(3)
        
        # 初始化机械臂
        arm = ArmController(app_config.connections, app_config.arm, app_config.gripper)
        print("机械臂控制器初始化成功")
        
        # 初始化标定对象
        K, dist = cam_thread.get_camera_intrinsics()
        T_end_to_camera = app_config.calibration.T_end_to_camera
        dh_params = arm.arm.rm_get_DH_data()[1]
        calibration = Calibration(dh_params, T_end_to_camera, K, dist)
        print("标定对象初始化成功")
        
        # 运行测试菜单
        while not exit_event.is_set():
            print("\n" + "="*50)
            print("手眼标定测试菜单")
            print("="*50)
            print("1. 测试当前标定矩阵")
            print("2. 交互式采集标定姿态")
            print("3. 运行完整手眼标定")
            print("4. 运行所有测试")
            print("Q. 退出")
            
            choice = input("请选择: ").upper()
            
            if choice == '1':
                test_calibration_matrix(calibration)
            elif choice == '2':
                collect_calibration_poses_interactively(arm, exit_event)
            elif choice == '3':
                run_handeye_calibration(arm, cam_thread, state)
                # 重新加载配置以获取更新的标定矩阵
                try:
                    app_config = load_config("config.ini")
                    T_end_to_camera = app_config.calibration.T_end_to_camera
                    calibration = Calibration(dh_params, T_end_to_camera, K, dist)
                    print("标定矩阵已更新")
                except Exception as e:
                    print(f"标定矩阵更新失败: {e}")
            elif choice == '4':
                test_calibration_matrix(calibration)
                print("\n进入交互式姿态采集模式...")
                collect_calibration_poses_interactively(arm, exit_event)
            elif choice == 'Q':
                exit_event.set()
                break
            else:
                print("无效选择，请重试")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"标定测试失败: {e}")
    finally:
        print("正在停止标定测试...")
        exit_event.set()
        
        if cam_thread and cam_thread.is_alive():
            cam_thread.join(timeout=2)
        
        cv2.destroyAllWindows()
        print("标定测试结束")


if __name__ == "__main__":
    run_calibration_tests()