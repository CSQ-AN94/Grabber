#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
导轨控制测试
"""

import sys
import os
import time

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from controllers.rail_controller import RailController


def test_rail_movement(rail: RailController, rail_config):
    """测试导轨运动"""
    print("\n--- [Test] Rail Movement ---")
    print(f"Current position: {rail.get_current_position()}. Moving to end...")
    rail.move_to(rail_config.scan_end)
    print(f"Position at end: {rail.get_current_position()}. Returning home...")
    rail.move_to(rail_config.home_position)
    print(f"Position at home: {rail.get_current_position()}.")
    print("--- Rail Movement Test PASSED ---")


def test_rail_positions(rail: RailController, rail_config):
    """测试导轨多个位置"""
    print("\n--- [Test] Rail Multiple Positions ---")
    
    # 测试序列
    test_positions = [
        ("Home Position", rail_config.home_position),
        ("Middle Position", (rail_config.home_position + rail_config.scan_end) / 2),
        ("Scan End", rail_config.scan_end),
        ("Back to Home", rail_config.home_position)
    ]
    
    for position_name, position in test_positions:
        print(f"Moving to {position_name} ({position})...")
        rail.move_to(position)
        time.sleep(2)
        current = rail.get_current_position()
        print(f"Current position: {current}")
        
    print("--- Rail Multiple Positions Test PASSED ---")


def run_rail_tests():
    """运行所有导轨测试"""
    print("=== 导轨控制测试 ===")
    
    try:
        # 加载配置
        app_config = load_config("config.ini")
        
        # 初始化导轨控制器
        rail = RailController(app_config.rail)
        print("导轨控制器初始化成功")
        
        # 运行测试
        while True:
            print("\n" + "="*40)
            print("导轨测试菜单")
            print("="*40)
            print("1. 测试基本导轨运动")
            print("2. 测试多位置运动")
            print("3. 运行所有测试")
            print("Q. 退出")
            
            choice = input("请选择: ").upper()
            
            if choice == '1':
                test_rail_movement(rail, app_config.rail)
            elif choice == '2':
                test_rail_positions(rail, app_config.rail)
            elif choice == '3':
                test_rail_movement(rail, app_config.rail)
                test_rail_positions(rail, app_config.rail)
            elif choice == 'Q':
                break
            else:
                print("无效选择，请重试")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"导轨测试失败: {e}")
    finally:
        print("导轨测试结束")


if __name__ == "__main__":
    run_rail_tests()