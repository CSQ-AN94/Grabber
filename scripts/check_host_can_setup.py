#!/usr/bin/env python3
"""
宿主机CAN配置检查脚本
基于 refs/setup_can2usb.bash 和 refs/bringup_can2usb.bash
确保宿主机端的CAN配置正确
"""

import subprocess
import time
import os
from typing import List, Tuple, Optional

class HostCANSetup:
    """宿主机CAN配置检查器"""
    
    def __init__(self):
        self.setup_script_commands = [
            "sudo modprobe gs_usb",
            "sudo ip link set can0 up type can bitrate 500000",
            "sudo apt install -y can-utils"
        ]
        
        self.bringup_script_commands = [
            "sudo ip link set can0 up type can bitrate 500000"
        ]
    
    def run_command(self, cmd: str, timeout: int = 30) -> Tuple[bool, str, str]:
        """运行shell命令"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def check_running_environment(self):
        """检查运行环境"""
        print("=== 运行环境检查 ===")
        
        if os.path.exists('/.dockerenv'):
            print("❌ 检测到Docker容器环境")
            print("⚠️ 此脚本需要在宿主机上运行，不是在容器内")
            print("💡 请退出容器，在宿主机终端运行此脚本")
            return False
        else:
            print("✅ 运行在宿主机环境")
            return True
    
    def check_sudo_permissions(self):
        """检查sudo权限"""
        print("\\n=== Sudo权限检查 ===")
        
        success, stdout, stderr = self.run_command("sudo -n true", timeout=5)
        if success:
            print("✅ 具有sudo权限")
            return True
        else:
            print("❌ 需要sudo权限")
            print("💡 请确保当前用户可以使用sudo")
            return False
    
    def check_usb_devices(self):
        """检查USB设备"""
        print("\\n=== USB设备检查 ===")
        
        success, stdout, stderr = self.run_command("lsusb")
        if success:
            print("📋 当前USB设备:")
            
            # 查找CAN适配器
            can_keywords = ['can', 'peak', 'kvaser', 'zlg', 'cantact', 'canable']
            can_devices = []
            
            for line in stdout.split('\\n'):
                line = line.strip()
                if line:
                    print(f"  {line}")
                    if any(keyword in line.lower() for keyword in can_keywords):
                        can_devices.append(line)
            
            if can_devices:
                print(f"\\n✅ 检测到可能的CAN适配器: {len(can_devices)}个")
                for device in can_devices:
                    print(f"  🔌 {device}")
                return True
            else:
                print("\\n⚠️ 未明确检测到CAN适配器")
                print("💡 请确认USB CAN适配器已正确连接")
                return False
        else:
            print("❌ 无法获取USB设备列表")
            return False
    
    def load_kernel_module(self):
        """加载内核模块（setup_can2usb.bash 第一步）"""
        print("\\n=== 加载内核模块 gs_usb ===")
        
        # 首先检查模块是否已加载
        success, stdout, stderr = self.run_command("lsmod | grep gs_usb")
        if success and "gs_usb" in stdout:
            print("✅ gs_usb模块已加载")
            return True
        
        # 尝试加载模块
        print("🔧 加载gs_usb内核模块...")
        success, stdout, stderr = self.run_command("sudo modprobe gs_usb")
        
        if success:
            print("✅ gs_usb模块加载成功")
            
            # 验证加载
            time.sleep(1)
            success, stdout, stderr = self.run_command("lsmod | grep gs_usb")
            if success and "gs_usb" in stdout:
                print("✅ 验证：gs_usb模块确实已加载")
                return True
            else:
                print("⚠️ gs_usb模块加载后未在lsmod中找到")
                return False
        else:
            print(f"❌ gs_usb模块加载失败: {stderr}")
            return False
    
    def setup_can_interface(self):
        """配置CAN接口（setup_can2usb.bash 第二步）"""
        print("\\n=== 配置CAN接口 ===")
        
        # 首先检查can0是否存在
        success, stdout, stderr = self.run_command("ip link show can0")
        if not success:
            print("❌ can0接口不存在")
            print("💡 请检查USB CAN适配器连接和gs_usb模块")
            return False
        
        print("✅ can0接口存在")
        print("🔧 配置can0接口（500k波特率）...")
        
        # 先关闭接口（如果已启动）
        self.run_command("sudo ip link set can0 down")
        
        # 启动接口并设置波特率
        success, stdout, stderr = self.run_command("sudo ip link set can0 up type can bitrate 500000")
        
        if success:
            print("✅ can0接口配置成功")
            
            # 验证配置
            time.sleep(1)
            success, stdout, stderr = self.run_command("ip link show can0")
            if success:
                print("📡 can0接口状态:")
                for line in stdout.split('\\n'):
                    if line.strip():
                        print(f"  {line.strip()}")
                
                if "UP" in stdout:
                    print("✅ can0接口已启动")
                    return True
                else:
                    print("⚠️ can0接口配置后未启动")
                    return False
            else:
                print("❌ 无法验证can0接口状态")
                return False
        else:
            print(f"❌ can0接口配置失败: {stderr}")
            return False
    
    def install_can_utils(self):
        """安装CAN工具（setup_can2usb.bash 第三步）"""
        print("\\n=== 安装CAN工具 ===")
        
        # 检查can-utils是否已安装
        tools = ['cansend', 'candump', 'canecho']
        all_installed = True
        
        for tool in tools:
            success, stdout, stderr = self.run_command(f"which {tool}")
            if success:
                print(f"✅ {tool} 已安装")
            else:
                print(f"❌ {tool} 未安装")
                all_installed = False
        
        if all_installed:
            print("✅ 所有CAN工具已安装")
            return True
        
        # 安装can-utils
        print("🔧 安装can-utils...")
        success, stdout, stderr = self.run_command("sudo apt update && sudo apt install -y can-utils", timeout=60)
        
        if success:
            print("✅ can-utils安装成功")
            return True
        else:
            print(f"❌ can-utils安装失败: {stderr}")
            return False
    
    def test_can_communication(self):
        """测试CAN通信"""
        print("\\n=== CAN通信测试 ===")
        
        # 测试发送CAN消息
        print("🔧 测试发送CAN消息...")
        success, stdout, stderr = self.run_command("cansend can0 123#DEADBEEF")
        
        if success:
            print("✅ CAN消息发送成功")
        else:
            print(f"❌ CAN消息发送失败: {stderr}")
            return False
        
        # 测试监听CAN消息
        print("🔧 测试CAN消息监听（2秒）...")
        success, stdout, stderr = self.run_command("timeout 2 candump can0")
        
        if success:
            if stdout.strip():
                print("✅ CAN消息监听成功，接收到数据:")
                print(f"  {stdout.strip()}")
            else:
                print("⚠️ CAN消息监听成功，但无数据接收（正常，因为没有外部设备）")
            return True
        else:
            print(f"❌ CAN消息监听失败: {stderr}")
            return False
    
    def run_full_setup_check(self):
        """运行完整的宿主机CAN配置检查"""
        print("宿主机CAN配置全面检查")
        print("=" * 50)
        print("基于 refs/setup_can2usb.bash 和 refs/bringup_can2usb.bash")
        print("=" * 50)
        
        # 检查运行环境
        if not self.check_running_environment():
            return False
        
        # 检查sudo权限
        if not self.check_sudo_permissions():
            return False
        
        # 执行配置步骤
        steps = [
            ("USB设备检查", self.check_usb_devices),
            ("加载内核模块", self.load_kernel_module),
            ("配置CAN接口", self.setup_can_interface),
            ("安装CAN工具", self.install_can_utils),
            ("测试CAN通信", self.test_can_communication)
        ]
        
        failed_steps = []
        
        for step_name, step_func in steps:
            print(f"\\n{'='*15} {step_name} {'='*15}")
            try:
                success = step_func()
                if not success:
                    failed_steps.append(step_name)
            except Exception as e:
                print(f"❌ {step_name} 异常: {e}")
                failed_steps.append(step_name)
            
            time.sleep(1)
        
        # 总结
        print("\\n" + "=" * 50)
        print("🏁 宿主机CAN配置检查完成")
        print("=" * 50)
        
        if failed_steps:
            print(f"❌ 失败的步骤: {', '.join(failed_steps)}")
            print("\\n💡 接下来的建议:")
            print("1. 解决上述失败的步骤")
            print("2. 重新插拔USB CAN适配器")
            print("3. 重启后重新运行此脚本")
            print("4. 确认硬件兼容性")
            return False
        else:
            print("✅ 所有配置检查通过！")
            print("\\n🎉 宿主机CAN配置正确，可以启动Docker容器测试")
            print("\\n📝 接下来的步骤:")
            print("1. 启动Docker容器:")
            print("   docker compose up")
            print("2. 在容器内运行CAN诊断:")
            print("   python3 scripts/diagnose_can_chain.py")
            return True

if __name__ == "__main__":
    setup_checker = HostCANSetup()
    setup_checker.run_full_setup_check()