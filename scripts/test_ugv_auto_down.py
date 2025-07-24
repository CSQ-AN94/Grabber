#!/usr/bin/env python3
"""
测试UGV控制器的自动CAN接口DOWN功能
验证初始化时UP，断开时DOWN
"""

import sys
import os
import time
import subprocess

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from controllers.ugv_controller import UGVController

def check_can_interface_status():
    """检查CAN接口状态"""
    try:
        result = subprocess.run(['ip', 'link', 'show', 'can0'], 
                              capture_output=True, text=True, timeout=5)
        if result.returncode == 0:
            if "UP" in result.stdout:
                return "UP"
            elif "DOWN" in result.stdout:
                return "DOWN"
            else:
                return "UNKNOWN"
        else:
            return "ERROR"
    except Exception as e:
        return f"EXCEPTION: {e}"

def test_ugv_auto_down():
    """测试UGV控制器的自动UP/DOWN功能"""
    print("UGV控制器自动CAN接口管理测试")
    print("=" * 50)
    print("测试目标:")
    print("✅ 初始化时自动配置CAN接口为UP")
    print("✅ 断开时自动设置CAN接口为DOWN")
    print("=" * 50)
    
    # 检查初始状态
    print("🔍 步骤1: 检查初始CAN接口状态")
    initial_status = check_can_interface_status()
    print(f"   初始状态: {initial_status}")
    
    try:
        # 加载配置
        config = load_config('config.ini')
        ugv_config = config.ugv
        
        print("\n🚀 步骤2: 创建UGV控制器（应该自动UP）")
        ugv_controller = UGVController(ugv_config)
        
        # 检查UP后状态
        print("\n🔍 步骤3: 验证CAN接口已UP")
        up_status = check_can_interface_status()
        print(f"   UP后状态: {up_status}")
        
        if up_status == "UP":
            print("   ✅ CAN接口成功配置为UP")
        else:
            print("   ❌ CAN接口未正确配置为UP")
        
        # 检查UGV连接状态
        print("\n🔍 步骤4: 验证UGV连接状态")
        if ugv_controller.is_connected():
            print("   ✅ UGV连接成功")
        else:
            print("   ❌ UGV连接失败")
        
        # 等待一下让用户观察
        print("\n⏳ 步骤5: 等待3秒...")
        time.sleep(3)
        
        # 手动断开连接
        print("🔌 步骤6: 手动断开UGV连接（应该自动DOWN）")
        ugv_controller.disconnect()
        
        # 检查DOWN后状态
        print("\n🔍 步骤7: 验证CAN接口已DOWN")
        down_status = check_can_interface_status()
        print(f"   DOWN后状态: {down_status}")
        
        if down_status == "DOWN":
            print("   ✅ CAN接口成功设置为DOWN")
        else:
            print("   ❌ CAN接口未设置为DOWN")
        
        # 测试结果总结
        print("\n" + "=" * 50)
        print("📊 测试结果总结")
        print("=" * 50)
        print(f"初始状态: {initial_status}")
        print(f"UP后状态: {up_status}")
        print(f"DOWN后状态: {down_status}")
        
        # 判断测试是否成功
        if up_status == "UP" and down_status == "DOWN":
            print("\n🎉 测试成功！")
            print("✅ UGV控制器正确管理CAN接口状态:")
            print("   - 初始化时: 自动UP")
            print("   - 断开时: 自动DOWN")
            return True
        else:
            print("\n⚠️ 测试部分成功")
            if up_status != "UP":
                print("❌ 初始化时CAN接口未正确UP")
            if down_status != "DOWN":
                print("❌ 断开时CAN接口未正确DOWN")
            return False
        
    except Exception as e:
        print(f"\n❌ 测试过程异常: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_auto_cleanup_with_exception():
    """测试异常情况下的自动清理"""
    print("\n" + "=" * 50)
    print("🧪 异常清理测试")
    print("=" * 50)
    print("测试场景: 使用with语句和异常处理")
    
    try:
        config = load_config('config.ini')
        ugv_config = config.ugv
        
        print("🚀 创建UGV控制器...")
        ugv_controller = UGVController(ugv_config)
        
        print("🔍 检查UP状态...")
        up_status = check_can_interface_status()
        print(f"   状态: {up_status}")
        
        print("💥 模拟异常（强制退出）...")
        # 这里不调用disconnect()，而是直接删除对象
        # atexit.register应该会自动调用disconnect()
        del ugv_controller
        
        # 等待atexit处理
        time.sleep(1)
        
        print("🔍 检查清理后状态...")
        final_status = check_can_interface_status()
        print(f"   状态: {final_status}")
        
        if final_status == "DOWN":
            print("✅ atexit自动清理成功")
            return True
        else:
            print("⚠️ atexit清理可能不完整")
            return False
            
    except Exception as e:
        print(f"❌ 异常清理测试失败: {e}")
        return False

if __name__ == "__main__":
    print("UGV控制器CAN接口自动管理功能验证")
    print("=" * 60)
    
    # 主要测试
    success1 = test_ugv_auto_down()
    
    # 异常清理测试
    success2 = test_auto_cleanup_with_exception()
    
    # 最终结果
    print("\n" + "=" * 60)
    print("🏁 最终测试结果")
    print("=" * 60)
    
    if success1 and success2:
        print("🎊 所有测试通过！")
        print("✅ UGV控制器CAN接口自动管理功能正常")
        print("\n💡 功能特性:")
        print("   - 初始化时: 自动配置并启动CAN接口")
        print("   - 正常断开: 自动关闭CAN接口")
        print("   - 异常退出: atexit自动清理CAN接口")
    else:
        print("⚠️ 部分测试未通过")
        if not success1:
            print("❌ 基本UP/DOWN功能有问题")
        if not success2:
            print("❌ 异常清理功能有问题")
    
    # 最终状态检查
    final_status = check_can_interface_status()
    print(f"\n📋 最终CAN接口状态: {final_status}")
    
    if final_status != "DOWN":
        print("💡 建议手动关闭CAN接口: ip link set can0 down")