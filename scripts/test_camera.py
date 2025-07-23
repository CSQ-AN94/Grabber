#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本 - 用于验证CameraThread及其相关功能的正确性
"""

import sys
import os
import time
import threading
import cv2
import numpy as np

# 将项目根目录添加到Python路径，以便导入自定义模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from utils.calibration import Calibration
from sensors.camera_thread import CameraThread, DisplayMode
from controllers.arm_controller import ArmController
from controllers.ugv_controller import UGVController
from intelligence.vision import VisionAnalyzer

def test_camera_capture(cam_thread: CameraThread):
    """测试基本的摄像头帧捕获功能"""
    print("\n--- [测试] 摄像头帧捕获 ---")
    
    if not cam_thread.initialization_successful:
        print("摄像头未初始化，跳过测试")
        return False
    
    print("正在等待摄像头帧...")
    timeout = 10
    start_time = time.time()
    
    while time.time() - start_time < timeout:
        color, depth = cam_thread.get_latest_frames()
        if color is not None:
            print(f" 彩色帧已接收: {color.shape}")
            break
        time.sleep(0.1)
    else:
        print(" 超时：未接收到彩色帧")
        return False
    
    if depth is not None:
        print(f" 深度帧已接收: {depth.shape}")
        depth_stats = f"范围: {depth.min():.3f}-{depth.max():.3f}米"
        print(f"  深度统计: {depth_stats}")
    else:
        print(" 无可用深度帧")
        return False
    
    print("--- 摄像头帧捕获测试通过 ---")
    return True

def test_point_cloud_generation(cam_thread: CameraThread):
    """测试点云生成和导出功能"""
    print("\n--- [测试] 点云生成与导出 ---")
    
    if not cam_thread.initialization_successful:
        print("摄像头未初始化，跳过测试")
        return False
    
    try:
        # 1. 生成点云
        pointcloud = cam_thread.generate_pointcloud(max_depth=2.0)
        
        if pointcloud is not None:
            print(f" 点云已生成: {len(pointcloud)} 个点")
            print(f"  点云形状: {pointcloud.shape}")
            print(f"  XYZ 范围: X[{pointcloud[:, 0].min():.3f}, {pointcloud[:, 0].max():.3f}]")
            print(f"             Y[{pointcloud[:, 1].min():.3f}, {pointcloud[:, 1].max():.3f}]") 
            print(f"             Z[{pointcloud[:, 2].min():.3f}, {pointcloud[:, 2].max():.3f}]")
        else:
            print(" 点云生成失败")
            return False
            
        # 2. 导出为PLY文件
        print("  正在测试PLY导出...")
        ply_filepath = cam_thread.export_scene_data(output_dir="./test_exports", max_depth=2.0)
        
        if ply_filepath and os.path.exists(ply_filepath):
            file_size = os.path.getsize(ply_filepath)
            print(f" PLY文件已导出: {ply_filepath} ({file_size} 字节)")
        else:
            print(" PLY导出失败")
            return False
            
        # 3. 测试数据API
        print("  正在测试点云数据API...")
        pointcloud_data = cam_thread.get_pointcloud_data(max_depth=2.0)
        
        if pointcloud_data:
            print(f" 点云数据已准备好传输")
            print(f"  时间戳: {pointcloud_data['timestamp']:.3f}")
            print(f"  相机fx: {pointcloud_data['camera_intrinsics']['fx']:.1f}")
            print(f"  点数量: {pointcloud_data['point_count']}")
            print(f"  深度范围: {pointcloud_data['depth_range']['min']:.3f}-{pointcloud_data['depth_range']['max']:.3f}m")
        else:
            print(" 点云数据API测试失败")
            return False
            
        print("--- 点云生成与导出测试通过 ---")
        return True
            
    except Exception as e:
        print(f" 点云测试出错: {e}")
        return False

def test_display_modes(cam_thread: CameraThread, vision_analyzer=None):
    """测试不同的显示模式"""
    print("\n--- [测试] 显示模式 ---")
    
    if not cam_thread.initialization_successful:
        print("摄像头未初始化，跳过测试")
        return False
    
    modes = [
        (DisplayMode.COLOR, "仅彩色图像"),
        (DisplayMode.DEPTH, "仅深度图像"),
        (DisplayMode.COLOR_DEPTH, "彩色+深度"),
    ]
    
    if vision_analyzer:
        modes.append((DisplayMode.COLOR_VISION, "彩色+视觉分析"))
        modes.append((DisplayMode.ALL, "所有视图"))
    
    for mode, description in modes:
        print(f"\n即将测试: {description}")
        print("  按任意键继续下一个模式，按 'q' 退出显示测试...")
        
        cam_thread.start_display(mode, vision_analyzer)
        time.sleep(2)  # 显示2秒
        
        # 等待用户输入
        key = input().strip().lower()
        cam_thread.stop_display()
        
        if key == 'q':
            print("用户选择退出")
            break
        
        time.sleep(1)  # 等待窗口关闭
    
    print("--- 显示模式测试完成 ---")
    return True

def test_coordinate_transform(calibration: Calibration, cam_thread: CameraThread, arm: ArmController, ugv: UGVController):
    """测试像素坐标到世界坐标的转换"""
    print("\n--- [测试] 坐标转换 ---")
    
    if not calibration:
        print("标定对象不可用")
        return False
    
    if not arm:
        print("机械臂控制器不可用")
        return False
    
    if not ugv:
        print("UGV控制器不可用")
        return False
    
    # 获取当前状态
    joint_angles = arm.get_current_joint_angles()
    ugv_position = ugv.get_current_position()
    _, depth_map = cam_thread.get_latest_frames()
    
    if depth_map is None:
        print("无可用深度图")
        return False
        
    h, w = depth_map.shape
    pixel_coords = (w // 2, h // 2)
    
    world_point = calibration.transform_pixel_to_world(pixel_coords, depth_map, joint_angles, ugv_position)
    
    if world_point is not None:
        print(f" 像素 ({pixel_coords}) -> 世界坐标 ({np.round(world_point, 3)})")
        print("--- 坐标转换测试通过 ---")
        return True
    else:
        print(" 坐标转换测试失败 (像素点深度无效)")
        return False

def test_camera_properties(cam_thread: CameraThread):
    """测试获取相机属性（内参、时间戳等）"""
    print("\n--- [测试] 相机属性 ---")
    
    try:
        K, dist = cam_thread.get_camera_intrinsics()
        if K is not None and dist is not None:
            print(f" 相机内参矩阵 K:\n{K}")
            print(f" 畸变系数: {dist}")
            print(f" 帧时间戳: {cam_thread.get_frame_timestamp():.3f}")
            print("--- 相机属性测试通过 ---")
            return True
        else:
            print(" 获取相机内参失败")
            return False
    except Exception as e:
        print(f" 相机属性测试失败: {e}")
        return False

def init_vision_analyzer():
    """初始化视觉分析器"""
    try:
        config = load_config("config.ini")
        vision_analyzer = VisionAnalyzer(config.vision.model_path)
        print("视觉分析器初始化成功")
        return vision_analyzer
    except Exception as e:
        print(f"视觉分析器初始化失败: {e}")
        return None

def init_arm_system():
    """初始化机械臂和UGV系统"""
    try:
        config = load_config("config.ini")
        arm = ArmController(config.connections, config.arm, config.gripper)
        ugv = UGVController(config.ugv)
        print("机械臂和UGV系统初始化成功")
        return arm, ugv
    except Exception as e:
        print(f"机械臂和UGV系统初始化失败: {e}")
        return None, None

def init_calibration_system(cam_thread: CameraThread, arm: ArmController):
    """初始化标定系统"""
    if not arm:
        return None
        
    try:
        config = load_config("config.ini")
        K, dist = cam_thread.get_camera_intrinsics()
        
        if K is not None and dist is not None:
            T_end_to_camera = config.calibration.T_end_to_camera
            calibration = Calibration(T_end_to_camera, K, dist)
            print("标定系统初始化成功")
            return calibration
        else:
            print("无法获取相机内参，标定系统初始化失败")
            return None
    except Exception as e:
        print(f"标定系统初始化失败: {e}")
        return None

def run_camera_tests():
    """运行相机相关的所有测试"""
    print("=" * 60)
    print(" CameraThread 功能测试菜单")
    print("=" * 60)
    
    cam_thread = None
    
    try:
        # 启动相机线程
        cam_thread = CameraThread()
        cam_thread.start()
        print("相机线程已启动")
        
        # 等待相机初始化
        print("⏳ 等待相机稳定...")
        time.sleep(3)
        
        # 测试菜单循环
        while True:
            print("\n" + "=" * 50)
            print("测试选项")
            print("=" * 50)
            print("1. 测试帧捕获")
            print("2. 测试相机属性")
            print("3. 测试点云生成与导出")
            print("4. 测试显示模式 (手动)")
            print("5. 测试坐标转换 (需要机械臂)")
            print("6. 运行所有自动化测试")
            print("7. 启动实时演示")
            print("8. 查看导出信息")
            print("Q. 退出")
            
            choice = input("请选择一个测试: ").strip().upper()
            
            if choice == '1':
                test_camera_capture(cam_thread)
            elif choice == '2':
                test_camera_properties(cam_thread)
            elif choice == '3':
                test_point_cloud_generation(cam_thread)
            elif choice == '4':
                print("正在初始化视觉分析器...")
                vision_analyzer = init_vision_analyzer()
                test_display_modes(cam_thread, vision_analyzer)
            elif choice == '5':
                print("正在初始化机械臂和标定系统...")
                arm, ugv = init_arm_system()
                calibration = init_calibration_system(cam_thread, arm)
                test_coordinate_transform(calibration, cam_thread, arm, ugv)
            elif choice == '6':
                print("\n开始运行所有自动化测试...")
                tests = [
                    test_camera_capture(cam_thread),
                    test_camera_properties(cam_thread),
                    test_point_cloud_generation(cam_thread),
                ]
                
                # 尝试运行依赖硬件的测试
                print("正在初始化机械臂和标定系统...")
                arm, ugv = init_arm_system()
                calibration = init_calibration_system(cam_thread, arm)
                
                if calibration and arm and ugv:
                    tests.append(test_coordinate_transform(calibration, cam_thread, arm, ugv))
                
                passed = sum(tests)
                total = len(tests)
                print(f"\n测试结果: {passed}/{total} 项通过")
                
            elif choice == '7':
                print("\n进入实时演示模式")
                print("请选择一个模式:")
                print("1. 彩色图像")
                print("2. 深度图像")
                print("3. 彩色+深度")
                print("4. 彩色+视觉分析")
                print("5. 所有视图")
                
                # 初始化视觉分析器（如果需要）
                vision_analyzer = None
                
                demo_choice = input("请输入选项: ").strip()
                
                # 如果选择的模式需要视觉分析，则初始化它
                if demo_choice in ['4', '5']:
                    print("正在初始化视觉分析器...")
                    vision_analyzer = init_vision_analyzer()
                
                mode_map = {
                    '1': DisplayMode.COLOR,
                    '2': DisplayMode.DEPTH,
                    '3': DisplayMode.COLOR_DEPTH,
                    '4': DisplayMode.COLOR_VISION,
                    '5': DisplayMode.ALL
                }
                
                selected_mode = mode_map.get(demo_choice, DisplayMode.COLOR)
                
                # 如果视觉分析器初始化失败，则回退到不带视觉的模式
                if selected_mode in [DisplayMode.COLOR_VISION, DisplayMode.ALL] and not vision_analyzer:
                    print("视觉分析器不可用，将以纯色模式显示。")
                    selected_mode = DisplayMode.COLOR
                
                print(f"启动演示，模式: {selected_mode.value}")
                print("在OpenCV窗口中按 'q' 键退出演示")
                
                cam_thread.start_display(selected_mode, vision_analyzer)
                
                # 等待显示线程结束（显示线程内部处理按键）
                while cam_thread.is_display_running():
                    time.sleep(0.1)
                
                print("演示已停止")
                
            elif choice == '8':
                print("\n获取导出信息...")
                export_info = cam_thread.get_export_info()
                print(f"  相机就绪: {'yes' if export_info['camera_ready'] else 'no'}")
                print(f"  有可用帧: {'yes' if export_info['has_frames'] else 'no'}")
                print(f"  最新帧时间戳: {export_info['frame_timestamp']:.3f}")
                print(f"  支持的导出格式: {', '.join(export_info['supported_formats'])}")
                print(f"  最大点数 (估计): {export_info['max_points']}")
                print(f"  默认导出目录: {export_info['export_directory']}")
                
            elif choice == 'Q':
                break
            else:
                print("无效输入，请重新选择。")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"发生严重错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("\n正在清理和退出...")
        
        if cam_thread:
            cam_thread.stop()
            if cam_thread.is_alive():
                cam_thread.join(timeout=3)
        
        print("测试程序已结束。")

if __name__ == "__main__":
    run_camera_tests()