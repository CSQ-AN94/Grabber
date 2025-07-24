#!/usr/bin/env python3
"""
UGV连接诊断和修复脚本
解决 "Network is down [Error Code 100]" 和 SocketCAN 问题
"""

import subprocess
import time
import sys
import os
from typing import Optional, Tuple

def check_can_interfaces():
    """检查CAN接口状态"""
    print("=== CAN接口状态检查 ===")
    
    try:
        result = subprocess.run(['ip', 'link', 'show', 'type', 'can'], 
                              capture_output=True, text=True)
        if result.returncode == 0 and result.stdout.strip():
            print("📋 检测到的CAN接口:")
            print(result.stdout)
            return True
        else:
            print("❌ 未检测到CAN接口")
            return False
    except Exception as e:
        print(f"❌ CAN接口检查失败: {e}")
        return False

def check_usb_can_adapter():
    """检查USB CAN适配器"""
    print("\n=== USB CAN适配器检查 ===")
    
    try:
        result = subprocess.run(['lsusb'], capture_output=True, text=True)
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            can_devices = [line for line in lines if any(keyword in line.lower() 
                          for keyword in ['can', 'peak', 'kvaser', 'zlg'])]
            
            if can_devices:
                print("✅ 检测到CAN适配器:")
                for device in can_devices:
                    print(f"  {device}")
                return True
            else:
                print("⚠️ 未检测到明确的CAN适配器，显示所有USB设备:")
                print(result.stdout)
                return False
    except Exception as e:
        print(f"❌ USB设备检查失败: {e}")
        return False

def reset_can_interface(interface: str = "can0"):
    """重置CAN接口"""
    print(f"\n=== 重置CAN接口 {interface} ===")
    
    commands = [
        ['sudo', 'ip', 'link', 'set', interface, 'down'],
        ['sudo', 'ip', 'link', 'set', interface, 'up', 'type', 'can', 'bitrate', '500000']
    ]
    
    for cmd in commands:
        try:
            print(f"执行: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                print(f"✅ 命令执行成功")
            else:
                print(f"⚠️ 命令执行警告: {result.stderr}")
                
        except subprocess.TimeoutExpired:
            print(f"⏰ 命令执行超时")
            return False
        except Exception as e:
            print(f"❌ 命令执行失败: {e}")
            return False
    
    return True

def kill_conflicting_processes():
    """杀死可能冲突的进程"""
    print("\n=== 清理冲突进程 ===")
    
    processes_to_kill = ['python3', 'canplayer', 'candump', 'cansend']
    
    for process_name in processes_to_kill:
        try:
            result = subprocess.run(['pgrep', '-f', 'pyagxrobots'], 
                                  capture_output=True, text=True)
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                print(f"发现pyagxrobots相关进程: {pids}")
                
                for pid in pids:
                    try:
                        subprocess.run(['kill', '-9', pid], check=True)
                        print(f"✅ 杀死进程 {pid}")
                    except:
                        print(f"⚠️ 无法杀死进程 {pid}")
        except:
            pass

def test_can_communication(interface: str = "can0"):
    """测试CAN通信"""
    print(f"\n=== 测试CAN通信 {interface} ===")
    
    try:
        # 发送测试CAN消息
        cmd = ['cansend', interface, '123#DEADBEEF']
        print(f"发送测试消息: {' '.join(cmd)}")
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        
        if result.returncode == 0:
            print("✅ CAN消息发送成功")
            return True
        else:
            print(f"❌ CAN消息发送失败: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("⏰ CAN通信测试超时")
        return False
    except Exception as e:
        print(f"❌ CAN通信测试失败: {e}")
        return False

def test_ugv_initialization():
    """测试UGV初始化"""
    print("\n=== UGV初始化测试 ===")
    
    try:
        import pyagxrobots
        print("✅ pyagxrobots库导入成功")
        
        # 尝试初始化UGV
        print("尝试创建RangerBase对象...")
        ugv = pyagxrobots.pysdkugv.RangerBase()
        print("✅ UGV对象创建成功")
        
        # 尝试发送测试命令
        print("发送停止命令测试...")
        ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
        print("✅ 运动命令发送成功")
        
        # 清理
        del ugv
        import gc
        gc.collect()
        time.sleep(0.5)
        
        return True
        
    except Exception as e:
        print(f"❌ UGV初始化失败: {e}")
        return False

def comprehensive_ugv_fix():
    """综合UGV连接修复"""
    print("UGV连接问题综合诊断和修复")
    print("=" * 50)
    
    steps = [
        ("检查CAN接口", check_can_interfaces),
        ("检查USB CAN适配器", check_usb_can_adapter),
        ("清理冲突进程", kill_conflicting_processes),
        ("重置CAN接口", lambda: reset_can_interface("can0")),
        ("测试CAN通信", lambda: test_can_communication("can0")),
        ("测试UGV初始化", test_ugv_initialization)
    ]
    
    for step_name, step_func in steps:
        print(f"\n{'='*20} {step_name} {'='*20}")
        
        try:
            success = step_func()
            if success:
                print(f"✅ {step_name} 成功")
            else:
                print(f"⚠️ {step_name} 有问题，但继续执行")
        except Exception as e:
            print(f"❌ {step_name} 异常: {e}")
        
        time.sleep(1)  # 步骤间暂停
    
    print(f"\n{'='*50}")
    print("🔧 修复流程完成")
    print("\n建议操作:")
    print("1. 如果仍有问题，请手动拔掉USB CAN适配器")
    print("2. 等待3秒后重新插入")
    print("3. 重新运行此脚本")

def manual_usb_reset_guide():
    """手动USB重置指南"""
    print("\n" + "="*50)
    print("🔧 手动USB CAN适配器重置指南")
    print("="*50)
    print("1. 找到USB CAN适配器（通常是小型USB设备）")
    print("2. 从电脑上拔掉USB CAN适配器")  
    print("3. 等待3秒钟...")
    print("4. 重新插入USB CAN适配器")
    print("5. 等待系统识别设备（约2-3秒）")
    print("6. 重新运行测试")
    print()
    
    input("完成上述步骤后，按Enter键继续测试...")
    return test_ugv_initialization()

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--manual-reset":
        # 手动重置模式
        manual_usb_reset_guide()
    else:
        # 自动修复模式
        comprehensive_ugv_fix()
        
        # 如果自动修复失败，提供手动指南
        print("\n如果问题仍然存在，请运行:")
        print("python3 scripts/test_ugv_connection.py --manual-reset")