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

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from utils.state import WorldState
from utils.calibration import Calibration
from sensors.camera_thread import CameraThread, DisplayMode
from controllers.arm_controller import ArmController


def test_simple_reach(arm: ArmController, camera_thread: CameraThread, calibration: Calibration, exit_event: threading.Event):
    """
    一个简单的测试，用于大致验证手眼标定的方向是否正确。
    """
    print("\n" + "*"*60)
    print("Simple Reach Test")
    print("1. The camera feed will be shown.")
    print("2. Press 't' to command the arm to reach for the point in the center of the screen, 10cm in front of the camera.")
    print("3. Press 'q' to exit.")
    print("*"*60)

    window_name = "Simple Reach Test"
    cv2.namedWindow(window_name)

    # 图像中心点
    center_pixel = (320, 240)
    # 目标深度
    target_depth_m = 0.2 # 20cm

    while not exit_event.is_set():
        color_image, _ = camera_thread.get_latest_frames()
        if color_image is None:
            time.sleep(0.01)
            continue
        
        # 在图像中心画一个十字进行提示
        cv2.drawMarker(color_image, center_pixel, (0, 0, 255), cv2.MARKER_CROSS, 20, 2)
        cv2.imshow(window_name, color_image)
        
        key = cv2.waitKey(30) & 0xFF

        if key == ord('q'):
            break
        
        if key == ord('t'):
            print("\n--- Calculating and moving ---")
            
            # 1. 获取当前的机械臂位姿
            T_base_to_end = arm.get_base_to_end_pose_matrix()
            if T_base_to_end is None:
                print("ERROR: Could not get current arm pose.")
                continue

            # 2. 将像素点转换为世界坐标
            # 注意：我们没有真实的深度图，所以直接使用给定的深度值
            world_coords = calibration.transform_pixel_to_world(
                pixel_coords=center_pixel,
                depth_in_meters=target_depth_m,
                T_base_to_end=T_base_to_end,
                rail_position=0.0 # 假设导轨在原点
            )

            if world_coords is None:
                print("ERROR: Could not transform pixel to world coordinates.")
                continue
            
            print(f"Calculated target world coordinates: {np.round(world_coords, 3)}")

            # 3. 命令机械臂移动
            # 我们保持机械臂末端的姿态不变，只移动位置
            current_orientation_rad = Rotation.from_matrix(T_base_to_end[:3, :3]).as_euler('xyz')
            
            target_pose = [
                world_coords[0],
                world_coords[1],
                world_coords[2],
                current_orientation_rad[0],
                current_orientation_rad[1],
                current_orientation_rad[2]
            ]
            
            print(f"Commanding arm to move to: {np.round(target_pose, 3)}")
            arm.move_to_cartesian_pose(target_pose, speed=50)
            print("Move command sent.")

    cv2.destroyWindow(window_name)
    print("--- Simple Reach Test Finished ---")


def run_test():
    """主运行函数"""
    exit_event = threading.Event()
    cam_thread = None
    
    try:
        # 加载配置
        app_config = load_config("config.ini")
        state = WorldState()
        
        # 启动相机线程
        cam_thread = CameraThread()
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
        if K is None:
            raise RuntimeError("Failed to get camera intrinsics. Cannot proceed.")
        T_end_to_camera = app_config.calibration.T_end_to_camera
        calibration = Calibration(T_end_to_camera, K, dist)
        print("标定对象初始化成功")
        
        # 运行测试
        test_simple_reach(arm, cam_thread, calibration, exit_event)

    except Exception as e:
        print(f"测试失败: {e}")
    finally:
        print("正在停止测试...")
        exit_event.set()
        if cam_thread and cam_thread.is_alive():
            cam_thread.join(timeout=2)
        cv2.destroyAllWindows()
        print("测试结束")


if __name__ == "__main__":
    # 为了避免与旧的测试脚本混淆，我们重命名主函数
    from scipy.spatial.transform import Rotation # 确保导入
    run_test()
