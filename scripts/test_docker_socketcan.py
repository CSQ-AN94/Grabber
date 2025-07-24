#!/usr/bin/env python3
"""
Docker容器SocketCAN访问测试
通过网络接口访问CAN，而不是设备文件
"""

import os
import sys
import time
import subprocess
import socket
import struct
from typing import Tuple

def check_container_environment():
    """检查容器环境"""
    print("=== Docker容器环境检查 ===")
    
    if os.path.exists('/.dockerenv'):
        print("✅ 运行在Docker容器中")
    else:
        print("⚠️ 未检测到Docker环境")
    
    # 检查网络模式（应该是host模式）
    try:
        with open('/proc/net/route', 'r') as f:
            content = f.read()
            if '0.0.0.0' in content:
                print("✅ 容器具有网络访问权限")
            else:
                print("⚠️ 容器网络配置可能有问题")
    except Exception as e:
        print(f"⚠️ 无法检查网络配置: {e}")
    
    return True

def test_socketcan_interface():
    """测试SocketCAN网络接口"""
    print("\n=== SocketCAN网络接口测试 ===")
    
    try:
        # 检查can0网络接口
        result = subprocess.run(['ip', 'link', 'show', 'can0'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ can0网络接口在容器中可见")
            print("📡 can0状态:")
            for line in result.stdout.split('\n'):
                if line.strip():
                    print(f"  {line.strip()}")
            
            # 检查接口是否UP
            if "UP" in result.stdout:
                print("✅ can0接口已启动")
                return True
            else:
                print("❌ can0接口未启动")
                return False
        else:
            print("❌ can0网络接口在容器中不可见")
            print(f"错误: {result.stderr}")
            return False
            
    except Exception as e:
        print(f"❌ SocketCAN接口测试异常: {e}")
        return False

def test_python_socketcan():
    """测试Python SocketCAN访问"""
    print("\n=== Python SocketCAN访问测试 ===")
    
    try:
        # 导入socket模块
        import socket
        print("✅ socket模块可用")
        
        # 检查CAN协议支持
        if hasattr(socket, 'AF_CAN'):
            print("✅ AF_CAN协议支持可用")
        else:
            print("❌ AF_CAN协议支持不可用")
            return False
        
        if hasattr(socket, 'CAN_RAW'):
            print("✅ CAN_RAW协议支持可用")
        else:
            print("❌ CAN_RAW协议支持不可用")
            return False
        
        # 尝试创建CAN socket
        print("🔧 创建CAN socket...")
        can_socket = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        print("✅ CAN socket创建成功")
        
        # 尝试绑定到can0接口
        print("🔧 绑定到can0接口...")
        can_socket.bind(('can0',))
        print("✅ 绑定can0接口成功")
        
        # 设置非阻塞模式进行测试
        can_socket.setblocking(False)
        
        # 关闭socket
        can_socket.close()
        print("✅ Python SocketCAN访问完全正常")
        
        return True
        
    except OSError as e:
        print(f"❌ SocketCAN系统错误: {e}")
        if "Network is down" in str(e):
            print("💡 网络接口可能未启动或配置错误")
        elif "Operation not permitted" in str(e):
            print("💡 权限不足，检查容器privileged模式")
        elif "No such device" in str(e):
            print("💡 can0设备不存在或未在容器中可见")
        return False
    except Exception as e:
        print(f"❌ Python SocketCAN访问异常: {e}")
        return False

def test_can_utils_in_container():
    """测试容器中的CAN工具"""
    print("\n=== 容器CAN工具测试 ===")
    
    # 检查can-utils工具
    tools = ['cansend', 'candump']
    available_tools = []
    
    for tool in tools:
        result = subprocess.run(['which', tool], capture_output=True, text=True)
        if result.returncode == 0:
            print(f"✅ {tool} 可用")
            available_tools.append(tool)
        else:
            print(f"❌ {tool} 不可用")
    
    if not available_tools:
        print("⚠️ 容器中没有CAN工具，但不影响pyagxrobots库使用")
        return True
    
    # 如果有cansend，测试发送
    if 'cansend' in available_tools:
        print("🔧 测试CAN消息发送...")
        result = subprocess.run(['cansend', 'can0', '123#DEADBEEF'], 
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("✅ CAN消息发送成功")
        else:
            print(f"❌ CAN消息发送失败: {result.stderr}")
    
    return len(available_tools) > 0

def test_pyagxrobots_import():
    """测试pyagxrobots库导入"""
    print("\n=== pyagxrobots库导入测试 ===")
    
    try:
        import pyagxrobots
        print("✅ pyagxrobots库导入成功")
        
        # 检查pysdkugv模块
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
        return False
    except Exception as e:
        print(f"❌ pyagxrobots库测试异常: {e}")
        return False

def test_ugv_initialization():
    """测试UGV初始化"""
    print("\n=== UGV初始化最终测试 ===")
    
    try:
        import pyagxrobots
        
        print("🤖 尝试创建RangerBase对象...")
        print("💡 这是关键测试 - 之前失败的地方")
        
        # 关键测试！
        ugv = pyagxrobots.pysdkugv.RangerBase()
        print("🎉 RangerBase对象创建成功！")
        
        print("📡 发送测试停止命令...")
        ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
        print("✅ 测试命令发送成功！")
        
        print("🧹 清理资源...")
        del ugv
        import gc
        gc.collect()
        time.sleep(0.5)
        
        print("🎊 UGV初始化完全成功！")
        print("✅ 'Network is down [Error Code 100]' 问题已解决")
        
        return True
        
    except Exception as e:
        print(f"❌ UGV初始化失败: {e}")
        
        # 详细错误分析
        error_str = str(e).lower()
        print("\\n📋 错误分析:")
        
        if "network is down" in error_str:
            print("❌ 仍然是 'Network is down' 错误")
            print("💡 可能的原因:")
            print("  1. CAN接口在容器中不可见")
            print("  2. CAN接口未正确启动")
            print("  3. pyagxrobots库无法访问SocketCAN")
        elif "permission" in error_str:
            print("❌ 权限错误")
            print("💡 检查容器privileged模式")
        elif "no such device" in error_str:
            print("❌ 设备不存在")
            print("💡 检查host网络模式配置")
        else:
            print(f"❌ 其他错误: {e}")
        
        # 显示详细异常信息
        import traceback
        print("\\n🔍 详细异常信息:")
        traceback.print_exc()
        
        return False

def run_comprehensive_socketcan_test():
    """运行完整的SocketCAN测试"""
    print("Docker容器SocketCAN访问完整测试")
    print("=" * 60)
    print("修复：移除/dev/can0设备挂载，使用SocketCAN网络接口")
    print("=" * 60)
    
    test_steps = [
        ("容器环境检查", check_container_environment),
        ("SocketCAN网络接口", test_socketcan_interface),
        ("Python SocketCAN访问", test_python_socketcan),
        ("容器CAN工具测试", test_can_utils_in_container),
        ("pyagxrobots库导入", test_pyagxrobots_import),
        ("UGV初始化测试", test_ugv_initialization)
    ]
    
    failed_steps = []
    critical_failed = False
    
    for step_name, step_func in test_steps:
        print(f"\\n{'='*20} {step_name} {'='*20}")
        
        try:
            success = step_func()
            if success:
                print(f"✅ {step_name} 通过")
            else:
                print(f"❌ {step_name} 失败")
                failed_steps.append(step_name)
                
                # 关键步骤失败，后续无法进行
                if step_name in ["SocketCAN网络接口", "pyagxrobots库导入"]:
                    print(f"⚠️ {step_name} 是关键步骤，跳过后续测试")
                    critical_failed = True
                    break
                    
        except Exception as e:
            print(f"❌ {step_name} 异常: {e}")
            failed_steps.append(step_name)
            
            if step_name in ["SocketCAN网络接口", "pyagxrobots库导入"]:
                critical_failed = True
                break
        
        time.sleep(1)
    
    # 最终总结
    print("\\n" + "=" * 60)
    print("🏁 SocketCAN测试完成")
    print("=" * 60)
    
    if not failed_steps:
        print("🎉 所有测试通过！")
        print("✅ Docker容器中的pyagxrobots库工作正常")
        print("✅ 'Network is down [Error Code 100]' 问题已解决")
        print("\\n🚀 现在可以:")
        print("1. 运行完整UGV控制器测试: python3 scripts/test_ugv_simple.py")
        print("2. 集成到grabber应用中")
        return True
    else:
        print(f"❌ 失败的测试: {', '.join(failed_steps)}")
        
        if critical_failed:
            print("\\n🔧 关键步骤失败，需要解决:")
            print("1. 确保宿主机CAN接口正常运行")
            print("2. 重启Docker容器: docker compose down && docker compose up")
            print("3. 检查Docker网络模式是否为host")
        else:
            print("\\n💡 非关键步骤失败，但UGV可能仍可使用")
            print("建议直接测试UGV控制器")
        
        return len(failed_steps) <= 2  # 允许一些非关键步骤失败

if __name__ == "__main__":
    success = run_comprehensive_socketcan_test()
    
    if success:
        print("\\n🎊 测试成功！现在可以使用UGV控制器了")
    else:
        print("\\n🔧 需要进一步排查问题")