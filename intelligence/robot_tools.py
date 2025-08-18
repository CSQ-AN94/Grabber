#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能零售机器人工具函数库
实现基于商品名称驱动的智能抓取逻辑，支持Gemini自动函数调用
支持真实硬件模式和Mock调试模式
"""

import cv2
from typing import Dict, Any
from utils.item_prices import get_item_price

# 全局变量 - 硬件系统组件（由main.py初始化）
vision_analyzer = None
camera_thread = None
calibration = None
arm_controller = None

# 全局状态管理
available_items = []  # 当前货架上可用商品名称列表
shopping_cart = []  # 购物车内商品列表，格式：[("商品名", 价格), ...]

def set_hardware_components(vision_analyzer_instance=None, camera_thread_instance=None, 
                          calibration_instance=None, arm_controller_instance=None):
    """设置硬件组件实例（由main.py调用）"""
    global vision_analyzer, camera_thread, calibration, arm_controller
    vision_analyzer = vision_analyzer_instance
    camera_thread = camera_thread_instance  
    calibration = calibration_instance
    arm_controller = arm_controller_instance

def init_mock_mode():
    """初始化Mock模式（由main.py调用）"""
    global available_items
    available_items = ["苹果", "橘子", "可口可乐", "薯片", "红牛"]
    print(f"[RobotTools] Mock模式初始化：预设货架商品 {available_items}")

def init_real_hardware_mode():
    """初始化真实硬件模式（由main.py调用）"""
    global available_items
    available_items = []
    print(f"[RobotTools] 真实硬件模式初始化：货架商品为空，等待扫描更新")

def get_available_items():
    """获取当前可用商品列表（供Agent系统调用）"""
    return available_items.copy()

def update_available_items(items: list):
    """更新可用商品列表（scan_shelf调用）"""
    global available_items
    available_items = items.copy()
    print(f"[RobotTools] 货架商品更新: {available_items}")

def remove_item_from_available(item_name: str):
    """从可用商品中移除指定商品（execute_grab调用）"""
    global available_items
    if item_name in available_items:
        available_items.remove(item_name)
        print(f"[RobotTools] 商品 '{item_name}' 已从货架移除，剩余: {available_items}")
        return True
    return False

def get_shopping_cart():
    """获取当前购物车状态（供Agent系统调用）"""
    return shopping_cart.copy()

def add_item_to_cart(item_name: str, price: float):
    """将商品添加到购物车"""
    global shopping_cart
    shopping_cart.append((item_name, price))
    print(f"[RobotTools] 商品 '{item_name}' 已添加到购物车，价格: {price}元")

def clear_shopping_cart():
    """清空购物车"""
    global shopping_cart
    shopping_cart = []
    print(f"[RobotTools] 购物车已清空")


# ========== 真实硬件版本的工具函数 ==========

def scan_shelf() -> Dict[str, Any]:
    """
    真实硬件模式：使用YOLO进行目标检测 + 3D坐标转换
    
    Returns:
        dict: {
            "success": bool,
            "objects": [
                {
                    "name": str,                    # 商品名称
                    "confidence": float,            # 检测置信度  
                    "box": [x1,y1,x2,y2],          # 边界框坐标
                    "center_3d_base": [x,y,z],     # 基座坐标系下的3D中心点
                    "pixel_coords": [u,v],         # 像素坐标
                    "depth": float                  # 深度值（米）
                }
            ],
            "message": str,
            "count": int
        }
    """
    print("[函数调用] scan_shelf() - 真实硬件扫描模式")
    
    try:
        if not all([vision_analyzer, camera_thread, calibration, arm_controller]):
            return {
                "success": False,
                "error": "硬件系统未完全初始化",
                "message": "请检查硬件系统初始化状态",
                "objects": [],
                "count": 0
            }
        
        # 获取最新的相机帧
        color_frame, depth_frame = camera_thread.get_latest_frames()
        
        if color_frame is None:
            return {
                "success": False,
                "error": "无法获取相机图像",
                "message": "相机系统未就绪或图像获取失败",
                "objects": [],
                "count": 0
            }
        
        # 转换颜色格式（相机输出BGR，YOLO需要RGB）
        color_rgb = cv2.cvtColor(color_frame, cv2.COLOR_BGR2RGB)
        
        # 使用视觉分析器检测物体
        detections = vision_analyzer.analyze_image(color_rgb, depth_frame)
        
        # 转换检测结果格式，添加3D坐标信息
        objects = []
        for det in detections:
            obj_info = {
                "name": det["name"],
                "confidence": det["confidence"], 
                "box": det["box"]
            }
            
            # 如果有深度信息，计算3D坐标（基座坐标系）
            if "center_depth_m" in det and det["center_depth_m"] > 0:
                obj_info["depth"] = det["center_depth_m"]
                
                # 计算边界框中心的像素坐标
                x1, y1, x2, y2 = det["box"]
                center_u = (x1 + x2) / 2
                center_v = (y1 + y2) / 2
                
                try:
                    # 获取当前机械臂位姿
                    T_base_to_end = arm_controller.get_base_to_end_pose_matrix()
                    
                    # 使用标定系统转换像素+深度到基座坐标系3D点
                    pixel_coords = (center_u, center_v)
                    base_3d_point = calibration.transform_pixel_to_world(
                        pixel_coords, det["center_depth_m"], T_base_to_end
                    )
                    
                    if base_3d_point is not None:
                        obj_info["center_3d_base"] = base_3d_point.tolist()
                        obj_info["pixel_coords"] = [center_u, center_v]
                    else:
                        print(f"[Vision] 警告: 物体 {det['name']} 坐标转换失败")
                        
                except Exception as e:
                    print(f"[Vision] 坐标转换错误: {e}")
                    obj_info["center_3d"] = [center_u, center_v, det["center_depth_m"]]
            
            objects.append(obj_info)
        
        # 更新available_items（真实硬件模式）
        detected_items = list(set([obj["name"] for obj in objects]))
        update_available_items(detected_items)
        
        # 构建返回结果
        if objects:
            message = f"扫描完成，检测到{len(objects)}个商品：{', '.join(detected_items)}"
        else:
            message = "扫描完成，未检测到任何商品"
        
        result = {
            "success": True,
            "objects": objects,
            "message": message,
            "count": len(objects)
        }
        
        print(f"[函数返回] {result['message']}")
        return result
        
    except Exception as e:
        error_result = {
            "success": False,
            "error": f"扫描过程中发生错误: {str(e)}",
            "message": "货架扫描失败，请检查相机和视觉系统",
            "objects": [],
            "count": 0
        }
        print(f"[函数错误] {error_result['error']}")
        return error_result

# ========== Mock调试版本的工具函数 ==========

def scan_shelf_mock() -> Dict[str, Any]:
    """
    Mock模式：返回当前available_items状态
    不更新available_items，只展示当前货架上剩余的商品
    """
    print("[函数调用] scan_shelf() - Mock调试模式")
    
    # Mock模式商品固定信息映射
    mock_item_data = {
        "苹果": {"confidence": 0.92, "center_3d_base": [0.45, -0.12, 0.78], "box": [150, 120, 320, 280]},
        "橘子": {"confidence": 0.89, "center_3d_base": [0.38, 0.15, 0.82], "box": [180, 150, 340, 300]},
        "可口可乐": {"confidence": 0.94, "center_3d_base": [0.52, -0.08, 0.75], "box": [200, 100, 380, 250]},
        "薯片": {"confidence": 0.87, "center_3d_base": [0.41, 0.22, 0.69], "box": [120, 180, 300, 320]},
        "红牛": {"confidence": 0.91, "center_3d_base": [0.47, -0.18, 0.73], "box": [250, 130, 420, 270]}
    }
    
    # 根据当前available_items生成objects
    objects = []
    for item_name in available_items:
        if item_name in mock_item_data:
            data = mock_item_data[item_name]
            obj_info = {
                "name": item_name,
                "confidence": data["confidence"],
                "box": data["box"],
                "center_3d_base": data["center_3d_base"],
                "pixel_coords": [(data["box"][0] + data["box"][2]) / 2, (data["box"][1] + data["box"][3]) / 2],
                "depth": 0.8  # 固定深度
            }
            objects.append(obj_info)
    
    message = f"Mock扫描完成，当前货架有{len(objects)}个商品：{', '.join(available_items)}"
    
    result = {
        "success": True,
        "objects": objects,
        "message": message,
        "count": len(objects)
    }
    
    print(f"[函数返回] {result['message']}")
    return result


def execute_grab(item_name: str) -> Dict[str, Any]:
    """
    真实硬件模式：完整的抓取流程
    
    流程：
    1. 实时扫描货架获取所有商品
    2. 定位目标商品
    3. 计算抓取坐标
    4. 执行抓取动作
    
    Args:
        item_name: 要抓取的商品名称（如"苹果"、"可口可乐"）
    
    Returns:
        dict: {
            "success": bool,
            "message": str,
            "item_name": str,
            "grasp_position": [x,y,z]  # 抓取位置（如果成功）
        }
    """
    print(f"[函数调用] execute_grab(item_name='{item_name}') - 真实硬件抓取模式")
    
    # TODO: 实现完整的抓取逻辑
    # 1. 调用scan_shelf()获取实时商品信息
    # 2. 在检测结果中查找目标商品
    # 3. 调用机械臂控制器执行抓取
    # 4. 返回抓取结果
    
    return {
        "success": False,
        "message": f"真实硬件模式下execute_grab('{item_name}')功能开发中",
        "error": "功能未实现",
        "item_name": item_name
    }

def execute_grab_mock(item_name: str) -> Dict[str, Any]:
    """
    Mock模式：基于available_items判断抓取结果
    成功抓取时会从available_items中移除该商品并添加到购物车
    """
    print(f"[函数调用] execute_grab(item_name='{item_name}') - Mock调试模式")
    
    if item_name in available_items:
        # 获取商品价格
        price = get_item_price(item_name)
        
        # 模拟成功抓取：从available_items移除，添加到购物车
        remove_item_from_available(item_name)
        add_item_to_cart(item_name, price)
        
        result = {
            "success": True,
            "message": f"Mock模式：成功抓取商品'{item_name}'，已添加到购物车",
            "item_name": item_name,
            "price": price,
            "grasp_position": [0.45, -0.12, 0.78]  # 固定坐标
        }
    else:
        # 模拟抓取失败 - 商品不在available_items中
        result = {
            "success": False,
            "message": f"Mock模式：未在货架上找到商品'{item_name}'，可能已被他人拿走或您看错了商品名称",
            "error": "商品未找到",
            "item_name": item_name
        }
    
    print(f"[函数返回] {result['message']}")
    return result

# 工具函数直接通过模块访问，无需额外的获取函数