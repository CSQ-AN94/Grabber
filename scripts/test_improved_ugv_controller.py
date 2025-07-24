#!/usr/bin/env python3
"""
测试改进后的UGV控制器
验证CAN接口自动配置功能
"""

import sys
import os
import time

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from controllers.ugv_controller import UGVController

def test_improved_ugv_controller():
    """测试改进后的UGV控制器"""
    print("改进后的UGV控制器测试")
    print("=" * 50)
    print("新功能:")
    print("✅ 自动配置CAN接口参数")
    print("✅ 自动启动CAN接口") 
    print("✅ 验证接口状态为UP")
    print("✅ 确保pyagxrobots初始化成功")
    print("=" * 50)
    
    try:
        # 加载配置
        config = load_config('config.ini')
        ugv_config = config.ugv
        
        print(f"📋 UGV配置:")
        print(f"  最大距离: {ugv_config.max_dist}m")
        print(f"  移动速度: {ugv_config.speed}m/s")
        print()
        
        print("🚀 创建UGV控制器（包含自动CAN配置）...")
        print()
        
        # 创建UGV控制器 - 这里会自动执行CAN配置
        ugv_controller = UGVController(ugv_config)
        
        # 检查初始化结果
        if ugv_controller.is_connected():
            print()
            print("🎉 UGV控制器初始化成功！")
            print()
            
            # 测试基本功能
            print("=== 基本功能测试 ===")
            
            # 1. 获取当前位置
            current_pos = ugv_controller.get_current_position()
            print(f"📍 当前位置: {current_pos}")
            
            # 2. 测试移动状态检查
            is_moving = ugv_controller.is_moving()
            print(f"🏃 移动状态: {is_moving}")
            
            # 3. 测试紧急停止功能
            print("🛑 测试紧急停止...")
            stop_success = ugv_controller.emergency_stop()
            print(f"紧急停止: {'成功' if stop_success else '失败'}")
            
            # 4. 重置紧急停止
            print("🔄 重置紧急停止状态...")
            reset_success = ugv_controller.reset_emergency_stop()
            print(f"重置紧急停止: {'成功' if reset_success else '失败'}")
            
            # 5. 测试小幅移动（如果用户同意）
            print("\n=== 移动测试 ===")
            response = input("⚠️ 是否进行小幅移动测试？确保UGV周围安全 (y/N): ").strip().lower()
            
            if response == 'y':
                print("🚀 执行小幅移动测试（移动到位置0.05）...")
                print("📍 注意：确保UGV周围安全！")
                
                # 等待3秒让用户准备
                for i in range(3, 0, -1):
                    print(f"⏰ 开始倒计时: {i}")
                    time.sleep(1)
                
                # 执行移动
                move_success = ugv_controller.move_to(0.05, wait=True)
                
                if move_success:
                    print("✅ 移动测试成功")
                    final_pos = ugv_controller.get_current_position()
                    print(f"📍 最终位置: {final_pos}")
                    
                    # 返回原位
                    print("🔄 返回原位...")
                    ugv_controller.move_to(0.0, wait=True)
                    print(f"📍 返回后位置: {ugv_controller.get_current_position()}")
                else:
                    print("❌ 移动测试失败")
            else:
                print("⏭️ 跳过移动测试")
            
            print("\n=== 测试完成 ===")
            print("🧹 正在断开连接...")
            ugv_controller.disconnect()
            print("✅ 改进后的UGV控制器测试完成")
            return True
            
        else:
            print("❌ UGV控制器初始化失败")
            print("\n🔧 可能的原因:")
            print("1. USB CAN适配器未连接")
            print("2. AgileX底盘未开机")
            print("3. CAN线缆连接问题")
            print("4. 需要以root权限运行（用于ip命令）")
            return False
            
    except Exception as e:
        print(f"❌ 测试过程异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def check_permissions():
    """检查运行权限"""
    print("🔍 检查运行权限...")
    
    import subprocess
    
    try:
        # 测试是否能执行ip命令
        result = subprocess.run(['ip', 'link', 'show'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            print("✅ ip命令权限正常")
            return True
        else:
            print("❌ ip命令权限不足")
            return False
    except Exception as e:
        print(f"❌ 权限检查失败: {e}")
        return False

if __name__ == "__main__":
    print("改进后的UGV控制器功能验证")
    print("=" * 60)
    
    # 检查权限
    if not check_permissions():
        print("\n⚠️ 权限不足，可能需要:")
        print("1. 以root权限运行容器")
        print("2. 或在容器外运行此测试")
        print("3. 确保Docker容器配置为privileged模式")
        sys.exit(1)
    
    # 运行测试
    success = test_improved_ugv_controller()
    
    if success:
        print("\n🎊 测试成功！改进后的UGV控制器工作正常")
        print("💡 现在UGV控制器会自动:")
        print("   - 配置CAN接口参数") 
        print("   - 启动CAN接口")
        print("   - 验证接口状态")
        print("   - 确保pyagxrobots初始化成功")
    else:
        print("\n🔧 测试失败，需要进一步排查问题")