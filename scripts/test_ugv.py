#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UGV控制测试
"""

import sys
import os
import time

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from controllers.ugv_controller import UGVController

def test_ugv_movement(ugv_ctrl: UGVController):
    """测试直线运动"""
    print("\n--- [Test] UGV Movement ---")
    print(f"Current position: {ugv_ctrl.get_current_position()}. \n\
          Current distance from home: {ugv_ctrl.max_dist * ugv_ctrl._position}.")
    target_position = float(input("Enter the target position (0.0 ~ 1.0): "))
    ugv_ctrl.move_to(target_position)
    print(f"Arrived position {target_position}")
    print("--- UGV Movement Test PASSED ---")

def run_ugv_tests():
    print("=== UGV控制测试 ===")
    
    try:
        # 加载配置
        app_config = load_config()
        
        # 初始化UGV控制器
        ugv_ctrl = UGVController(app_config.ugv)
        print("UGV控制器初始化成功")
        
        # 运行测试
        while True:
            print("\n" + "="*40)
            print("UGV测试菜单")
            print("="*40)
            print("1. 测试基本UGV运动")
            print("Q. 退出")
            
            choice = input("请选择: ").upper()
            
            if choice == '1':
                test_ugv_movement(ugv_ctrl)
            elif choice == 'Q':
                break
            else:
                print("无效选择，请重试")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"测试失败: {e}")
    except KeyboardInterrupt:
        print("\n用户中断测试")
    finally:
        if 'ugv_ctrl' in locals() and ugv_ctrl.is_connected():
            print("\n正在断开UGV连接...")
            ugv_ctrl.disconnect()
        print("测试结束")

if __name__ == "__main__":
    run_ugv_tests()