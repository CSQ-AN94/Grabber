#!/usr/bin/env python3
"""
CAN通信链条全面诊断
分析：底盘CAN总线 → CAN转USB适配器 → Host主机USB接口 → SocketCAN接口 → Docker容器网络 → Python应用
"""

import subprocess
import time
import os
import sys
from typing import List, Dict, Tuple, Optional

class CANChainDiagnostic:
    """CAN通信链条诊断器"""
    
    def __init__(self):
        self.issues = []
        self.warnings = []
        self.successes = []
        
    def log_issue(self, message: str):
        """记录问题"""
        self.issues.append(message)
        print(f"❌ {message}")
    
    def log_warning(self, message: str):
        """记录警告"""
        self.warnings.append(message)
        print(f"⚠️ {message}")
    
    def log_success(self, message: str):
        """记录成功"""
        self.successes.append(message)
        print(f"✅ {message}")
    
    def run_command(self, cmd: List[str], timeout: int = 10) -> Tuple[bool, str, str]:
        """运行命令并返回结果"""
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def check_environment(self):
        """检查运行环境"""
        print("\\n" + "="*20 + " 环境检查 " + "="*20)
        
        # 检查是否在容器内
        if os.path.exists('/.dockerenv'):
            self.log_success("运行在Docker容器内")
        else:
            self.log_warning("运行在宿主机上（可能影响某些测试）")
        
        # 检查权限
        if os.geteuid() == 0:
            self.log_success("具有root权限")
        else:
            self.log_warning("非root权限（某些操作可能失败）")
    
    def check_usb_can_adapter(self):
        """第1环节：检查USB CAN适配器"""
        print("\\n" + "="*20 + " USB CAN适配器检查 " + "="*20)
        
        # 检查USB设备
        success, stdout, stderr = self.run_command(['lsusb'])
        if success:
            lines = stdout.split('\\n')
            # 查找可能的CAN适配器
            can_keywords = ['can', 'peak', 'kvaser', 'zlg', 'cantact', 'canable']
            can_devices = []
            
            for line in lines:
                if any(keyword in line.lower() for keyword in can_keywords):
                    can_devices.append(line.strip())
            
            if can_devices:
                self.log_success(f"检测到可能的CAN适配器: {len(can_devices)}个")
                for device in can_devices:
                    print(f"  📱 {device}")
            else:
                self.log_warning("未检测到明显的CAN适配器设备")
                print("  📋 所有USB设备:")
                for line in lines[:10]:  # 只显示前10个设备
                    if line.strip():
                        print(f"    {line.strip()}")
        else:
            self.log_issue("无法获取USB设备列表")
    
    def check_kernel_modules(self):
        """第2环节：检查内核模块"""
        print("\\n" + "="*20 + " 内核模块检查 " + "="*20)
        
        # 检查必要的内核模块
        required_modules = ['gs_usb', 'can', 'can_raw', 'socketcan']
        
        for module in required_modules:
            success, stdout, stderr = self.run_command(['lsmod'])
            if success and module in stdout:
                self.log_success(f"内核模块 {module} 已加载")
            else:
                self.log_warning(f"内核模块 {module} 可能未加载")
                
                # 尝试加载模块
                if module == 'gs_usb':
                    print(f"    尝试加载 {module}...")
                    load_success, _, load_stderr = self.run_command(['modprobe', module])
                    if load_success:
                        self.log_success(f"成功加载内核模块 {module}")
                    else:
                        self.log_issue(f"无法加载内核模块 {module}: {load_stderr}")
    
    def check_can_interfaces(self):
        """第3环节：检查CAN接口"""
        print("\\n" + "="*20 + " CAN接口检查 " + "="*20)
        
        # 检查网络接口
        success, stdout, stderr = self.run_command(['ip', 'link', 'show'])
        if success:
            if 'can0' in stdout:
                self.log_success("检测到can0接口")
                
                # 检查can0状态
                can_lines = [line for line in stdout.split('\\n') if 'can0' in line]
                for line in can_lines:
                    print(f"  📡 {line.strip()}")
                    
                    if 'UP' in line:
                        self.log_success("can0接口已启动")
                    else:
                        self.log_warning("can0接口未启动")
            else:
                self.log_issue("未检测到can0接口")
        else:
            self.log_issue("无法获取网络接口信息")
        
        # 检查CAN特定接口
        success, stdout, stderr = self.run_command(['ip', 'link', 'show', 'type', 'can'])
        if success and stdout.strip():
            self.log_success("检测到CAN类型接口")
            print("  🔗 CAN接口详情:")
            for line in stdout.split('\\n'):
                if line.strip():
                    print(f"    {line.strip()}")
        else:
            self.log_warning("未检测到CAN类型接口")
    
    def check_can_configuration(self):
        """第4环节：检查CAN配置"""
        print("\\n" + "="*20 + " CAN配置检查 " + "="*20)
        
        # 尝试配置can0（基于参考脚本）
        commands = [
            # 先关闭接口
            (['ip', 'link', 'set', 'can0', 'down'], "关闭can0接口"),
            # 配置并启动接口
            (['ip', 'link', 'set', 'can0', 'up', 'type', 'can', 'bitrate', '500000'], "启动can0接口（500k波特率）")
        ]
        
        for cmd, description in commands:
            print(f"  🔧 {description}...")
            success, stdout, stderr = self.run_command(cmd)
            if success:
                self.log_success(f"{description} 成功")
            else:
                self.log_issue(f"{description} 失败: {stderr}")
    
    def check_can_utilities(self):
        """第5环节：检查CAN工具"""
        print("\\n" + "="*20 + " CAN工具检查 " + "="*20)
        
        # 检查can-utils工具
        tools = ['cansend', 'candump', 'canecho']
        
        for tool in tools:
            success, stdout, stderr = self.run_command(['which', tool])
            if success:
                self.log_success(f"CAN工具 {tool} 可用")
            else:
                self.log_warning(f"CAN工具 {tool} 不可用")
    
    def test_can_communication(self):
        """第6环节：测试CAN通信"""
        print("\\n" + "="*20 + " CAN通信测试 " + "="*20)
        
        # 测试发送CAN消息
        test_commands = [
            (['cansend', 'can0', '123#DEADBEEF'], "发送测试CAN消息"),
            (['timeout', '2', 'candump', 'can0', '-n', '1'], "监听CAN消息")
        ]
        
        for cmd, description in test_commands:
            print(f"  📡 {description}...")
            success, stdout, stderr = self.run_command(cmd, timeout=5)
            if success:
                self.log_success(f"{description} 成功")
                if stdout.strip():
                    print(f"    输出: {stdout.strip()}")
            else:
                self.log_warning(f"{description} 失败: {stderr}")
    
    def check_docker_network_config(self):
        """第7环节：检查Docker网络配置"""
        print("\\n" + "="*20 + " Docker网络配置检查 " + "="*20)
        
        # 检查是否在容器内
        if not os.path.exists('/.dockerenv'):
            self.log_warning("未在Docker容器内运行")
            return
        
        # 检查网络模式（应该是host模式）
        success, stdout, stderr = self.run_command(['cat', '/proc/net/route'])
        if success:
            if '0.0.0.0' in stdout:
                self.log_success("容器具有网络访问权限")
            else:
                self.log_warning("容器网络配置可能有问题")
        
        # 检查设备挂载
        devices_to_check = ['/dev/can0', '/dev/bus/usb']
        for device in devices_to_check:
            if os.path.exists(device):
                self.log_success(f"设备 {device} 已挂载到容器")
            else:
                self.log_issue(f"设备 {device} 未挂载到容器")
        
        # 检查权限
        if os.path.exists('/dev/can0'):
            stat_info = os.stat('/dev/can0')
            self.log_success(f"/dev/can0 权限: {oct(stat_info.st_mode)[-3:]}")
    
    def test_python_can_library(self):
        """第8环节：测试Python CAN库"""
        print("\\n" + "="*20 + " Python CAN库测试 " + "="*20)
        
        try:
            import pyagxrobots
            self.log_success("pyagxrobots库导入成功")
            
            # 尝试创建RangerBase对象
            print("  🤖 尝试创建RangerBase对象...")
            try:
                ugv = pyagxrobots.pysdkugv.RangerBase()
                self.log_success("RangerBase对象创建成功")
                
                # 尝试发送命令
                print("  📡 发送测试命令...")
                ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
                self.log_success("测试命令发送成功")
                
                # 清理
                del ugv
                import gc
                gc.collect()
                time.sleep(0.1)
                
            except Exception as e:
                self.log_issue(f"RangerBase初始化失败: {e}")
                
        except ImportError as e:
            self.log_issue(f"pyagxrobots库导入失败: {e}")
    
    def generate_fix_suggestions(self):
        """生成修复建议"""
        print("\\n" + "="*20 + " 修复建议 " + "="*20)
        
        if self.issues:
            print("🔧 发现的问题和建议修复方案:")
            for i, issue in enumerate(self.issues, 1):
                print(f"  {i}. {issue}")
            
            print("\\n💡 通用修复步骤:")
            print("1. 在宿主机上运行 refs/setup_can2usb.bash")
            print("2. 检查USB CAN适配器物理连接")
            print("3. 重启Docker容器:")
            print("   docker compose down && docker compose up")
            print("4. 如果仍有问题，尝试:")
            print("   - 重新插拔USB CAN适配器")
            print("   - 重启宿主机网络服务")
            print("   - 检查内核版本兼容性")
        
        if self.warnings:
            print("\\n⚠️ 警告项目:")
            for warning in self.warnings:
                print(f"  • {warning}")
        
        print(f"\\n📊 诊断摘要:")
        print(f"  ✅ 成功项目: {len(self.successes)}")
        print(f"  ⚠️ 警告项目: {len(self.warnings)}")
        print(f"  ❌ 问题项目: {len(self.issues)}")
    
    def run_full_diagnostic(self):
        """运行完整诊断"""
        print("CAN通信链条全面诊断")
        print("=" * 60)
        print("分析链路: 底盘CAN → CAN转USB → Host USB → SocketCAN → Docker → Python")
        print("=" * 60)
        
        # 运行所有检查
        diagnostic_steps = [
            self.check_environment,
            self.check_usb_can_adapter,
            self.check_kernel_modules,
            self.check_can_interfaces,
            self.check_can_configuration,
            self.check_can_utilities,
            self.test_can_communication,
            self.check_docker_network_config,
            self.test_python_can_library
        ]
        
        for step in diagnostic_steps:
            try:
                step()
                time.sleep(0.5)  # 给每个步骤之间一点间隔
            except Exception as e:
                self.log_issue(f"诊断步骤异常: {e}")
        
        # 生成修复建议
        self.generate_fix_suggestions()

if __name__ == "__main__":
    diagnostic = CANChainDiagnostic()
    diagnostic.run_full_diagnostic()