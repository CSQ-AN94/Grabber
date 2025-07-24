#!/usr/bin/env python3
"""
简化的UGV连接测试
基于更新后的ugv_controller.py进行测试
"""

import sys
import os
import time

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from controllers.ugv_controller import UGVController

def test_ugv_controller():
    """测试UGV控制器"""
    print("=== UGV控制器测试 ===")
    
    try:
        # 加载配置
        config = load_config('config.ini')
        ugv_config = config.ugv
        
        print(f"UGV配置:")
        print(f"  最大距离: {ugv_config.max_dist}m")
        print(f"  移动速度: {ugv_config.speed}m/s")
        print()
        
        print("创建UGV控制器...")
        ugv_controller = UGVController(ugv_config)
        
        # 检查连接状态
        if ugv_controller.is_connected():
            print("✅ UGV连接成功")
            
            # 测试基本功能
            print("\n=== 基本功能测试 ===")
            
            # 1. 获取当前位置
            current_pos = ugv_controller.get_current_position()
            print(f"当前位置: {current_pos}")
            
            # 2. 测试移动状态检查
            is_moving = ugv_controller.is_moving()
            print(f"移动状态: {is_moving}")
            
            # 3. 测试紧急停止功能
            print("测试紧急停止...")
            stop_success = ugv_controller.emergency_stop()
            print(f"紧急停止: {'成功' if stop_success else '失败'}")
            
            # 4. 重置紧急停止
            print("重置紧急停止状态...")
            reset_success = ugv_controller.reset_emergency_stop()
            print(f"重置紧急停止: {'成功' if reset_success else '失败'}")
            
            # 5. 测试小幅移动（如果用户同意）
            print("\n=== 移动测试 ===")
            response = input("是否进行小幅移动测试？(y/N): ").strip().lower()
            
            if response == 'y':
                print("执行小幅移动测试（移动到位置0.1）...")
                print("注意：确保UGV周围安全！")
                
                # 等待3秒让用户准备
                for i in range(3, 0, -1):
                    print(f"开始倒计时: {i}")
                    time.sleep(1)
                
                # 执行移动
                move_success = ugv_controller.move_to(0.1, wait=True)
                
                if move_success:
                    print("✅ 移动测试成功")
                    final_pos = ugv_controller.get_current_position()
                    print(f"最终位置: {final_pos}")
                    
                    # 返回原位
                    print("返回原位...")
                    ugv_controller.move_to(0.0, wait=True)
                    print(f"返回后位置: {ugv_controller.get_current_position()}")
                else:
                    print("❌ 移动测试失败")
            else:
                print("跳过移动测试")
            
            print("\n=== 测试完成 ===")
            print("正在断开连接...")
            ugv_controller.disconnect()
            print("✅ UGV控制器测试完成")
            
        else:
            print("❌ UGV连接失败")
            print("\n可能的解决方案:")
            print("1. 检查USB CAN适配器连接")
            print("2. 运行: python3 scripts/test_ugv_connection.py")
            print("3. 手动重置USB CAN适配器")
            
    except Exception as e:
        print(f"❌ UGV控制器测试异常: {e}")
        import traceback
        traceback.print_exc()

def quick_connection_test():
    """快速连接测试"""
    print("=== 快速UGV连接测试 ===")
    
    try:
        import pyagxrobots
        print("✅ pyagxrobots库可用")
        
        print("尝试创建RangerBase对象...")
        ugv = pyagxrobots.pysdkugv.RangerBase()
        print("✅ RangerBase创建成功")
        
        print("发送停止命令...")
        ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
        print("✅ 命令发送成功")
        
        # 清理
        del ugv
        import gc
        gc.collect()
        time.sleep(0.1)
        
        print("✅ 快速连接测试成功")
        return True
        
    except Exception as e:
        print(f"❌ 快速连接测试失败: {e}")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        # 快速测试模式
        quick_connection_test()
    else:
        # 完整测试模式
        test_ugv_controller()