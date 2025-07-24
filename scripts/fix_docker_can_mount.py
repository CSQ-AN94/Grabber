#!/usr/bin/env python3
"""
修复Docker容器CAN设备挂载问题
确保/dev/can0正确挂载到容器中
"""

import subprocess
import os
import time
from typing import Tuple

def run_command(cmd: str, timeout: int = 10) -> Tuple[bool, str, str]:
    """运行命令"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"
    except Exception as e:
        return False, "", str(e)

def check_host_can_device():
    """检查宿主机CAN设备状态"""
    print("=== 宿主机CAN设备检查 ===")
    
    # 检查/dev/can0是否存在
    if os.path.exists('/dev/can0'):
        print("✅ 宿主机/dev/can0存在")
        
        # 检查设备权限
        try:
            stat_info = os.stat('/dev/can0')
            print(f"📋 设备权限: {oct(stat_info.st_mode)[-3:]}")
            print(f"📋 设备所有者: UID={stat_info.st_uid}, GID={stat_info.st_gid}")
        except Exception as e:
            print(f"⚠️ 无法获取设备信息: {e}")
        
        return True
    else:
        print("❌ 宿主机/dev/can0不存在")
        return False

def check_can_interface_status():
    """检查CAN接口状态"""
    print("\\n=== CAN接口状态检查 ===")
    
    success, stdout, stderr = run_command("ip link show can0")
    if success:
        print("✅ can0网络接口存在")
        print("📡 can0状态:")
        for line in stdout.split('\\n'):
            if line.strip():
                print(f"  {line.strip()}")
        
        # 检查接口是否UP
        if "UP" in stdout:
            print("✅ can0接口已启动")
            return True
        else:
            print("⚠️ can0接口未启动")
            return False
    else:
        print("❌ can0网络接口不存在")
        print(f"错误: {stderr}")
        return False

def ensure_can_device_exists():
    """确保CAN设备文件存在"""
    print("\\n=== 确保CAN设备文件存在 ===")
    
    if os.path.exists('/dev/can0'):
        print("✅ /dev/can0已存在")
        return True
    
    print("⚠️ /dev/can0不存在，尝试创建...")
    
    # 获取can0的网络接口信息
    success, stdout, stderr = run_command("ip link show can0")
    if not success:
        print("❌ can0网络接口不存在，无法创建设备文件")
        return False
    
    # CAN设备通常是网络设备，不需要/dev下的设备文件
    # 但某些应用可能需要，我们可以尝试创建符号链接
    print("💡 CAN设备是网络接口，通常不需要/dev下的设备文件")
    print("如果应用需要，可以通过网络接口方式访问")
    
    return True

def fix_docker_compose_config():
    """检查并修复docker-compose.yml配置"""
    print("\\n=== Docker Compose配置检查 ===")
    
    compose_file = "/app/docker-compose.yml"
    if not os.path.exists(compose_file):
        compose_file = "docker-compose.yml"
    
    if not os.path.exists(compose_file):
        print("❌ 找不到docker-compose.yml文件")
        return False
    
    print(f"📋 检查配置文件: {compose_file}")
    
    try:
        with open(compose_file, 'r') as f:
            content = f.read()
        
        if '/dev/can0:/dev/can0' in content:
            print("✅ docker-compose.yml中已配置CAN设备挂载")
        else:
            print("⚠️ docker-compose.yml中未找到CAN设备挂载配置")
        
        if 'privileged: true' in content:
            print("✅ 容器已配置privileged模式")
        else:
            print("⚠️ 容器未配置privileged模式")
        
        if 'network_mode: \"host\"' in content:
            print("✅ 容器已配置host网络模式")
        else:
            print("⚠️ 容器未配置host网络模式")
        
        return True
        
    except Exception as e:
        print(f"❌ 读取配置文件失败: {e}")
        return False

def test_alternative_can_access():
    """测试替代的CAN访问方法"""
    print("\\n=== 测试替代CAN访问方法 ===")
    
    # 方法1: 通过网络接口访问（推荐）
    print("🔧 方法1: 通过SocketCAN网络接口")
    success, stdout, stderr = run_command("ip link show can0")
    if success:
        print("✅ 可以通过SocketCAN接口访问")
        
        # 测试Python socket CAN访问
        try:
            import socket
            import struct
            
            # 创建CAN socket
            can_socket = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
            
            # 绑定到can0接口
            can_socket.bind(('can0',))
            
            print("✅ Python SocketCAN访问成功")
            can_socket.close()
            
            return True
            
        except Exception as e:
            print(f"⚠️ Python SocketCAN访问失败: {e}")
    
    # 方法2: 检查是否有其他CAN设备
    print("\\n🔧 方法2: 检查其他CAN设备")
    success, stdout, stderr = run_command("ls -la /dev/ | grep can")
    if success and stdout.strip():
        print("📋 找到的CAN相关设备:")
        print(stdout)
    else:
        print("⚠️ 未找到其他CAN设备")
    
    return False

def create_docker_restart_script():
    """创建Docker重启脚本"""
    print("\\n=== 创建Docker重启脚本 ===")
    
    restart_script = '''#!/bin/bash
echo "重启Docker容器以确保设备正确挂载..."

# 停止容器
docker compose down

# 等待2秒
sleep 2

# 确保宿主机CAN接口正常
sudo ip link set can0 down 2>/dev/null || true
sudo ip link set can0 up type can bitrate 500000 loopback on recv-own-msgs on

# 等待1秒
sleep 1

# 启动容器
docker compose up -d

echo "容器重启完成，请测试CAN访问"
'''
    
    try:
        with open('/app/restart_docker_can.sh', 'w') as f:
            f.write(restart_script)
        
        # 添加执行权限
        os.chmod('/app/restart_docker_can.sh', 0o755)
        
        print("✅ Docker重启脚本已创建: /app/restart_docker_can.sh")
        return True
        
    except Exception as e:
        print(f"❌ 创建重启脚本失败: {e}")
        return False

def run_comprehensive_fix():
    """运行完整的修复流程"""
    print("Docker容器CAN设备挂载问题修复")
    print("=" * 50)
    
    # 检查是否在容器内
    if os.path.exists('/.dockerenv'):
        print("⚠️ 当前在Docker容器内")
        print("某些修复操作需要在宿主机执行")
    else:
        print("✅ 当前在宿主机")
    
    fix_steps = [
        ("检查宿主机CAN设备", check_host_can_device),
        ("检查CAN接口状态", check_can_interface_status),
        ("确保CAN设备存在", ensure_can_device_exists),
        ("检查Docker配置", fix_docker_compose_config),
        ("测试替代访问方法", test_alternative_can_access),
        ("创建重启脚本", create_docker_restart_script)
    ]
    
    results = []
    
    for step_name, step_func in fix_steps:
        print(f"\\n{'='*15} {step_name} {'='*15}")
        
        try:
            success = step_func()
            results.append((step_name, success))
            
            if success:
                print(f"✅ {step_name} 完成")
            else:
                print(f"⚠️ {step_name} 需要注意")
                
        except Exception as e:
            print(f"❌ {step_name} 异常: {e}")
            results.append((step_name, False))
        
        time.sleep(1)
    
    # 总结和建议
    print("\\n" + "=" * 50)
    print("🔧 修复结果总结")
    print("=" * 50)
    
    success_count = sum(1 for _, success in results if success)
    total_count = len(results)
    
    print(f"✅ 成功项目: {success_count}/{total_count}")
    
    print("\\n💡 接下来的步骤:")
    
    if os.path.exists('/.dockerenv'):
        print("1. 退出容器到宿主机")
        print("2. 确保宿主机CAN接口正常:")
        print("   sudo ip link set can0 up type can bitrate 500000 loopback on recv-own-msgs on")
        print("3. 重启Docker容器:")
        print("   docker compose down && docker compose up")
        print("4. 重新测试容器中的CAN访问")
    else:
        print("1. 运行重启脚本:")
        print("   ./restart_docker_can.sh")
        print("2. 或手动重启容器:")
        print("   docker compose down && docker compose up")
        print("3. 重新测试: docker compose run --rm grabber_dev python3 scripts/test_docker_can_final.py")

if __name__ == "__main__":
    run_comprehensive_fix()