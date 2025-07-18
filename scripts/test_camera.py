#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
相机和坐标变换测试
"""

import sys
import os
import time
import threading
import cv2
import numpy as np

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from utils.state import WorldState
from utils.calibration import Calibration
from sensors.camera_thread import CameraThread, DisplayThread
from controllers.arm_controller import ArmController
from controllers.rail_controller import RailController

def test_camera_capture(state: WorldState):
    """测试相机捕获"""
    print("\n--- [Test] Camera Capture ---")
    
    # 等待相机提供帧
    print("Waiting for camera frames...")
    timeout = 10
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        color, depth = state.get_latest_frames()
        if color is not None:
            print(f"Color frame received: {color.shape}")
            break
        time.sleep(0.1)
    else:
        print("Timeout: No color frame received")
        return False
    
    if depth is not None:
        print(f"Depth frame received: {depth.shape}")
    else:
        print("No depth frame available")
    
    print("--- Camera Capture Test PASSED ---")
    return True


def test_coordinate_transform(calibration: Calibration, state: WorldState, arm: ArmController, rail: RailController):
    """测试坐标变换"""
    print("\n--- [Test] Coordinate Transform ---")
    
    if not calibration:
        print("Calibration object not available")
        return False
    
    if not arm:
        print("Arm controller not available")
        return False
    
    if not rail:
        print("Rail controller not available")
        return False
    
    # 使用真实的实时数据进行变换
    joint_angles = arm.get_current_joint_angles()
    rail_position = rail.get_current_position()
    _, depth_map = state.get_latest_frames()
    
    if depth_map is None:
        print("No depth map available")
        return False
        
    h, w = depth_map.shape
    pixel_coords = (w // 2, h // 2)
    
    world_point = calibration.transform_pixel_to_world(pixel_coords, depth_map, joint_angles, rail_position)
    
    if world_point is not None:
        print(f"Pixel ({pixel_coords}) -> World ({np.round(world_point, 3)})")
        print("--- Coordinate Transform Test PASSED ---")
        return True
    else:
        print("Coordinate Transform Test FAILED (Invalid depth at pixel)")
        return False


def test_camera_properties(cam_thread: CameraThread):
    """测试相机属性"""
    print("\n--- [Test] Camera Properties ---")
    
    try:
        K, dist = cam_thread.get_camera_intrinsics()
        print(f"Camera intrinsics matrix K:\n{K}")
        print(f"Distortion coefficients: {dist}")
        print("--- Camera Properties Test PASSED ---")
        return True
    except Exception as e:
        print(f"Camera Properties Test FAILED: {e}")
        return False


def run_camera_tests():
    """运行所有相机测试"""
    print("=== 相机和坐标变换测试 ===")
    
    exit_event = threading.Event()
    cam_thread = None
    display_thread = None
    
    try:
        # 加载配置
        app_config = load_config("config.ini")
        state = WorldState()
        
        # 启动相机线程
        cam_thread = CameraThread(state, None)
        cam_thread.start()
        print("相机线程启动成功")
        
        # 启动显示线程
        display_thread = DisplayThread(state, exit_event)
        display_thread.start()
        print("显示线程启动成功")
        
        # 等待相机稳定
        print("等待相机初始化...")
        time.sleep(3)
        
        # 初始化其他组件（可选，用于坐标变换测试）
        arm = None
        rail = None
        calibration = None
        
        try:
            arm = ArmController(app_config.connections, app_config.arm, app_config.gripper)
            rail = RailController(app_config.rail)
            
            K, dist = cam_thread.get_camera_intrinsics()
            T_end_to_camera = app_config.calibration.T_end_to_camera
            dh_params = arm.arm.rm_get_DH_data()[1]
            calibration = Calibration(dh_params, T_end_to_camera, K, dist)
            print("所有组件初始化成功")
        except Exception as e:
            print(f"部分组件初始化失败，将跳过相关测试: {e}")
        
        # 运行测试菜单
        while not exit_event.is_set():
            print("\n" + "="*40)
            print("相机测试菜单")
            print("="*40)
            print("1. 测试相机捕获")
            print("2. 测试相机属性")
            print("3. 测试坐标变换 (需要机械臂和导轨)")
            print("4. 显示实时画面 (按'q'退出)")
            print("5. 运行所有测试")
            print("Q. 退出")
            
            choice = input("请选择: ").upper()
            
            if choice == '1':
                test_camera_capture(state)
            elif choice == '2':
                test_camera_properties(cam_thread)
            elif choice == '3':
                test_coordinate_transform(calibration, state, arm, rail)
            elif choice == '4':
                print("实时画面显示中，在OpenCV窗口按'q'退出")
                while not exit_event.is_set():
                    if cv2.waitKey(100) & 0xFF == ord('q'):
                        break
            elif choice == '5':
                test_camera_capture(state)
                test_camera_properties(cam_thread)
                if calibration and arm and rail:
                    test_coordinate_transform(calibration, state, arm, rail)
            elif choice == 'Q':
                exit_event.set()
                break
            else:
                print("无效选择，请重试")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"相机测试失败: {e}")
    finally:
        print("正在停止相机测试...")
        exit_event.set()
        
        if cam_thread and cam_thread.is_alive():
            cam_thread.join(timeout=2)
        if display_thread and display_thread.is_alive():
            display_thread.join(timeout=2)
        
        print("相机测试结束")


if __name__ == "__main__":
    run_camera_tests()