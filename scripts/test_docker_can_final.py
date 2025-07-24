#!/usr/bin/env python3
"""
Docker容器中CAN通信最终测试
现在我们知道宿主机CAN工作正常，测试容器中的pyagxrobots
"""

import os
import sys
import time
import subprocess
from typing import Tuple

def check_container_environment():
    """检查容器环境"""
    print("=== Docker容器环境检查 ===")
    
    if os.path.exists('/.dockerenv'):
        print("✅ 运行在Docker容器中")
    else:
        print("⚠️ 未检测到Docker环境")
        print("💡 建议在容器中运行此脚本")
    
    # 检查CAN设备挂载
    if os.path.exists('/dev/can0'):
        print("✅ /dev/can0 设备已挂载")
        
        # 检查设备权限
        try:
            stat_info = os.stat('/dev/can0')
            print(f"📋 /dev/can0 权限: {oct(stat_info.st_mode)[-3:]}")
        except Exception as e:
            print(f"⚠️ 无法获取/dev/can0权限信息: {e}")
    else:
        print("❌ /dev/can0 设备未挂载")
        print("💡 检查docker-compose.yml中的设备挂载配置")
        return False
    
    return True

def test_container_can_access():
    """测试容器中的CAN访问"""
    print("\n=== 容器CAN访问测试 ===")
    
    try:
        # 测试ip命令
        result = subprocess.run(['ip', 'link', 'show', 'can0'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ 容器中can0接口可见")
            print("📡 can0状态:")
            for line in result.stdout.split('\n'):
                if line.strip():
                    print(f"  {line.strip()}")
        else:
            print("❌ 容器中无法访问can0接口")
            print(f"错误: {result.stderr}")
            return False
        
        # 测试candump（如果可用）
        candump_result = subprocess.run(['which', 'candump'], 
                                      capture_output=True, text=True)
        if candump_result.returncode == 0:
            print("✅ candump命令在容器中可用")
            
            # 快速测试candump
            print("🔧 测试容器中的candump...")
            candump_process = subprocess.Popen(
                ['candump', 'can0'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            time.sleep(1)
            
            if candump_process.poll() is None:
                print("✅ 容器中candump正常启动")
                candump_process.terminate()
                candump_process.wait()
            else:
                stdout, stderr = candump_process.communicate()
                print(f"❌ 容器中candump启动失败: {stderr}")
        else:
            print("⚠️ candump命令在容器中不可用")
        
        return True
        
    except Exception as e:
        print(f"❌ 容器CAN访问测试异常: {e}")
        return False

def test_pyagxrobots_import():
    """测试pyagxrobots库导入"""
    print("\n=== pyagxrobots库导入测试 ===")
    
    try:
        import pyagxrobots
        print("✅ pyagxrobots库导入成功")
        
        # 检查库版本或属性
        if hasattr(pyagxrobots, '__version__'):
            print(f"📋 pyagxrobots版本: {pyagxrobots.__version__}")
        
        # 检查是否有pysdkugv模块
        if hasattr(pyagxrobots, 'pysdkugv'):
            print("✅ pysdkugv模块可用")
            
            # 检查RangerBase类
            if hasattr(pyagxrobots.pysdkugv, 'RangerBase'):
                print("✅ RangerBase类可用")
                return True
            else:
                print("❌ RangerBase类不可用")
                return False
        else:
            print("❌ pysdkugv模块不可用")
            return False
            
    except ImportError as e:
        print(f"❌ pyagxrobots库导入失败: {e}")
        print("💡 检查库是否正确安装")
        return False
    except Exception as e:
        print(f"❌ pyagxrobots库测试异常: {e}")
        return False

def test_ugv_initialization():
    """测试UGV初始化"""
    print("\n=== UGV初始化测试 ===")
    
    try:
        import pyagxrobots
        
        print("🤖 尝试创建RangerBase对象...")
        
        # 这是关键测试！
        ugv = pyagxrobots.pysdkugv.RangerBase()
        print("✅ RangerBase对象创建成功！")
        
        print("📡 尝试发送测试命令...")
        ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
        print("✅ 测试命令发送成功！")
        
        print("🧹 清理资源...")
        del ugv
        import gc
        gc.collect()
        time.sleep(0.5)
        
        print("🎉 UGV初始化测试完全成功！")
        return True
        
    except Exception as e:
        print(f"❌ UGV初始化失败: {e}")
        print("📋 错误详情:")
        import traceback
        traceback.print_exc()
        
        # 分析错误类型
        error_str = str(e).lower()
        if "network is down" in error_str:
            print("\n💡 'Network is down' 错误分析:")
            print("1. 可能是CAN总线状态检查失败")
            print("2. 检查宿主机CAN接口是否正确配置")
            print("3. 确认Docker容器网络模式为host")
        elif "permission" in error_str:
            print("\n💡 权限错误分析:")
            print("1. 检查Docker容器是否以privileged模式运行")
            print("2. 确认/dev/can0设备正确挂载")
        elif "no such device" in error_str:
            print("\n💡 设备不存在错误:")
            print("1. 检查CAN适配器是否连接")
            print("2. 确认宿主机can0接口已启动")
        
        return False

def run_comprehensive_docker_test():
    """运行完整的Docker容器CAN测试"""
    print("Docker容器CAN通信完整测试")
    print("=" * 60)
    print("前置条件: 宿主机CAN通信已验证正常（200%接收率）")
    print("=" * 60)
    
    test_steps = [
        ("容器环境检查", check_container_environment),
        ("容器CAN访问测试", test_container_can_access), 
        ("pyagxrobots库导入", test_pyagxrobots_import),
        ("UGV初始化测试", test_ugv_initialization)
    ]
    
    failed_steps = []
    
    for step_name, step_func in test_steps:
        print(f"\n{'='*20} {step_name} {'='*20}")
        
        try:
            success = step_func()
            if success:
                print(f"✅ {step_name} 通过")
            else:
                print(f"❌ {step_name} 失败")
                failed_steps.append(step_name)
                
                # 如果前面的步骤失败，后续可能无法进行
                if step_name in ["容器环境检查", "pyagxrobots库导入"]:
                    print(f"⚠️ {step_name} 失败，跳过后续测试")
                    break
                    
        except Exception as e:
            print(f"❌ {step_name} 异常: {e}")
            failed_steps.append(step_name)
        
        time.sleep(1)
    
    # 最终总结
    print("\n" + "=" * 60)
    print("🏁 Docker容器CAN测试完成")
    print("=" * 60)
    
    if not failed_steps:
        print("🎉 所有测试通过！")
        print("✅ Docker容器中的pyagxrobots库工作正常")
        print("✅ UGV控制器可以正常使用")
        print("\n📝 接下来可以:")
        print("1. 运行完整的UGV控制器测试")
        print("2. 集成到grabber应用中")
        return True
    else:
        print(f"❌ 失败的测试: {', '.join(failed_steps)}")
        print("\n🔧 排查建议:")
        if "容器环境检查" in failed_steps:
            print("- 确认Docker容器配置正确")
            print("- 检查设备挂载和权限")
        if "UGV初始化测试" in failed_steps:
            print("- 问题已定位到pyagxrobots库层面")
            print("- 检查库版本和CAN接口兼容性")
        return False

if __name__ == "__main__":
    success = run_comprehensive_docker_test()
    
    if success:
        print("\n🚀 现在可以测试完整的UGV控制器:")
        print("python3 scripts/test_ugv_simple.py")
    else:
        print("\n🔧 需要解决上述问题后再进行UGV控制器测试")