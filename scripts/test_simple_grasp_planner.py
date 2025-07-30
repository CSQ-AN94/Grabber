#!/usr/bin/env python3
"""
测试简单抓取规划器
验证基于2.5D几何约束的抓取点估计
"""

import sys
import numpy as np
import time

# 添加项目根目录到Python路径
sys.path.insert(0, '/app')

from intelligence.simple_grasp_planner import SimpleGraspPlanner
from sensors.camera_thread import CameraThread
from controllers.arm_controller import ArmController
from intelligence.vision import VisionAnalyzer
from utils.calibration import Calibration
from utils.config import load_config


def test_grasp_planner_with_real_data():
    """使用真实相机和机械臂数据测试抓取规划器"""
    print("=== 测试简单抓取规划器（真实数据） ===")
    
    try:
        # 1. 加载配置
        print("加载配置...")
        config = load_config()
        
        # 2. 初始化相机线程
        print("初始化相机...")
        camera_thread = CameraThread()
        if not camera_thread.initialization_successful:
            print("❌ 相机初始化失败")
            return False
        
        camera_thread.start()
        time.sleep(2)  # 等待相机稳定
        
        # 3. 初始化机械臂（如果可用）
        arm_controller = None
        arm_current_pose = None
        try:
            print("初始化机械臂...")
            conn_config = config.connections
            arm_config = config.arm
            gripper_config = config.gripper
            
            arm_controller = ArmController(conn_config, arm_config, gripper_config)
            arm_current_pose = arm_controller.get_base_to_end_pose_matrix()
            
            if arm_current_pose is not None:
                print("✅ 机械臂连接成功")
            else:
                print("⚠️  机械臂状态获取失败，使用模拟位姿")
                # 使用单位矩阵作为模拟位姿
                arm_current_pose = np.eye(4)
                
        except Exception as e:
            print(f"⚠️  机械臂初始化失败: {e}")
            print("使用模拟机械臂位姿进行测试")
            arm_current_pose = np.eye(4)
        
        # 4. 初始化依赖组件
        print("初始化视觉分析器...")
        vision_analyzer = VisionAnalyzer(config.vision.model_path)
        
        print("初始化标定模块...")
        calibration = Calibration(
            T_end_to_camera=config.calibration.T_end_to_camera,
            camera_matrix=None,  # 将从相机线程获取
            distortion_coeffs=None  # 将从相机线程获取
        )
        
        # 从相机线程获取内参
        K, dist = camera_thread.get_camera_intrinsics()
        if K is not None and dist is not None:
            calibration.K = K
            calibration.dist = dist
            print("✅ 标定模块获取到相机内参")
        else:
            print("⚠️  无法获取相机内参，使用默认值")
        
        print("初始化抓取规划器...")
        grasp_planner = SimpleGraspPlanner(
            items_config=config.items,
            calibration=calibration,
            vision_analyzer=vision_analyzer
        )
        
        print(f"支持的物品价格: {grasp_planner.get_all_item_prices()}")
        
        # 5. 获取相机数据
        print("获取相机数据...")
        color_image, depth_image = camera_thread.get_latest_frames()
        
        if color_image is None or depth_image is None:
            print("❌ 无法获取相机数据")
            return False
        
        print(f"图像尺寸: color={color_image.shape}, depth={depth_image.shape}")
        
        # 6. 测试抓取规划
        print("\n开始抓取规划...")
        
        # 测试不同的期望物体 - 使用中文名称
        test_items = ["可口可乐", "红牛", "纯牛奶", "薯片", None]  # None表示不指定期望物体
        
        for expected_item in test_items:
            print(f"\n--- 测试期望物体: {expected_item or '任意物体'} ---")
            
            start_time = time.time()
            result = grasp_planner.estimate_grasp(
                color_image=color_image,
                depth_image=depth_image,
                arm_current_pose=arm_current_pose,
                ugv_position=0.0,  # 假设UGV在原点
                expected_item_name=expected_item
            )
            processing_time = time.time() - start_time
            
            print(f"处理时间: {processing_time*1000:.1f}ms")
            
            if result["success"]:
                print("✅ 抓取规划成功!")
                print(f"目标物体: {result['target_object']}")
                print(f"检测置信度: {result['confidence']:.3f}")
                print(f"抓取位姿: {[f'{x:.3f}' for x in result['grasp_pose']]}")
                print(f"夹爪张开度: {result['gripper_openness']:.3f}")
                print(f"物品价格: ￥{result['price']}")
                
                # 显示调试信息
                debug_info = result['debug_info']
                print("调试信息:")
                print(f"  像素坐标: {debug_info['pixel_coords']}")
                print(f"  深度值: {debug_info['depth_m']:.3f}m")
                print(f"  世界坐标: {[f'{x:.3f}' for x in debug_info['world_point']]}")
                print(f"  检测到物体总数: {debug_info['all_detections']}")
                
                # 如果有机械臂，询问是否执行抓取
                if arm_controller is not None:
                    print(f"\n是否执行抓取? (y/n): ", end="")
                    try:
                        execute = input().strip().lower()
                        if execute in ['y', 'yes']:
                            print("执行抓取动作...")
                            # 这里可以调用实际的抓取执行逻辑
                            # execute_grasp(arm_controller, result)
                            print("⚠️  实际抓取执行已禁用（安全考虑）")
                    except (KeyboardInterrupt, EOFError):
                        print("\n跳过执行")
                
            else:
                print("❌ 抓取规划失败")
                print(f"原因: {result['message']}")
                if 'error' in result:
                    print(f"错误: {result['error']}")
            
            # 测试间隔
            time.sleep(1)
        
        # 清理资源
        camera_thread.stop()
        camera_thread.join()
        
        return True
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_grasp_planner_config():
    """测试抓取规划器的配置系统"""
    print("\n=== 测试抓取规划器配置系统 ===")
    
    try:
        # 加载配置
        config = load_config()
        
        # 测试配置解析
        print("物品配置测试:")
        print(f"支持的物品: {config.items.get_all_items()}")
        
        # 测试几个物品的配置
        test_items = ["可口可乐", "红牛", "纯牛奶"]
        for item_name in test_items:
            item_config = config.items.get_item_config(item_name)
            if item_config:
                print(f"  {item_name}: z_offset={item_config.z_offset:.3f}, "
                      f"gripper_openness={item_config.gripper_openness:.3f}, "
                      f"price=￥{item_config.price}")
            else:
                print(f"  {item_name}: 配置未找到")
        
        # 测试价格查询
        print(f"\n所有物品价格:")
        for item_name in config.items.get_all_items():
            price = config.items.get_item_price(item_name)
            print(f"  {item_name}: ￥{price}")
        
        return True
        
    except Exception as e:
        print(f"❌ 配置测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """主测试函数"""
    print("开始测试简单抓取规划器...")
    
    # 测试1: 配置系统测试
    success_config = test_grasp_planner_config()
    print(f"\n配置系统测试: {'✅ 通过' if success_config else '❌ 失败'}")
    
    # 测试2: 真实数据测试
    print("\n是否进行真实数据测试（需要相机和机械臂）? (y/n): ", end="")
    try:
        response = input().strip().lower()
        if response in ['y', 'yes']:
            success_real = test_grasp_planner_with_real_data()
            print(f"\n真实数据测试: {'✅ 通过' if success_real else '❌ 失败'}")
        else:
            print("跳过真实数据测试")
    except KeyboardInterrupt:
        print("\n用户中断测试")
    
    print("\n测试完成!")


if __name__ == "__main__":
    main()