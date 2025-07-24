#!/usr/bin/env python3
"""
CAN环回测试和修复脚本
解决CAN发送成功但接收失败的问题
"""

import subprocess
import time
import threading
import signal
import sys
from typing import Tuple, Optional

class CANLoopbackFixer:
    """CAN环回问题修复器"""
    
    def __init__(self):
        self.candump_process = None
        self.received_messages = []
        
    def run_command(self, cmd: str, timeout: int = 10) -> Tuple[bool, str, str]:
        """运行命令"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def check_can_interface_details(self):
        """检查CAN接口详细信息"""
        print("=== CAN接口详细检查 ===")
        
        # 检查接口状态
        success, stdout, stderr = self.run_command("ip -d link show can0")
        if success:
            print("📡 can0接口详细信息:")
            for line in stdout.split('\\n'):
                if line.strip():
                    print(f"  {line.strip()}")
        
        # 检查CAN统计信息
        success, stdout, stderr = self.run_command("cat /proc/net/can/stats")
        if success:
            print("\\n📊 CAN统计信息:")
            print(stdout)
        
        # 检查CAN接口统计
        success, stdout, stderr = self.run_command("ip -s link show can0")
        if success:
            print("📈 can0接口统计:")
            for line in stdout.split('\\n'):
                if line.strip():
                    print(f"  {line.strip()}")
    
    def test_can_loopback_modes(self):
        """测试不同的CAN环回模式"""
        print("\\n=== 测试CAN环回模式 ===")
        
        # 测试1: 标准环回模式
        print("🔧 测试1: 启用CAN环回模式...")
        
        # 关闭接口
        self.run_command("sudo ip link set can0 down")
        time.sleep(0.5)
        
        # 启用环回模式并重新启动
        success, stdout, stderr = self.run_command(
            "sudo ip link set can0 up type can bitrate 500000 loopback on"
        )
        
        if success:
            print("✅ 环回模式启用成功")
            
            # 测试环回通信
            if self.test_loopback_communication():
                print("✅ 环回通信测试成功")
                return True
            else:
                print("❌ 环回通信测试失败")
        else:
            print(f"❌ 环回模式启用失败: {stderr}")
        
        # 测试2: 禁用环回，启用接收自己消息
        print("\\n🔧 测试2: 启用接收自己消息模式...")
        
        self.run_command("sudo ip link set can0 down")
        time.sleep(0.5)
        
        success, stdout, stderr = self.run_command(
            "sudo ip link set can0 up type can bitrate 500000 recv-own-msgs on"
        )
        
        if success:
            print("✅ 接收自己消息模式启用成功")
            
            if self.test_loopback_communication():
                print("✅ 接收自己消息测试成功")
                return True
            else:
                print("❌ 接收自己消息测试失败")
        else:
            print(f"❌ 接收自己消息模式启用失败: {stderr}")
        
        # 测试3: 同时启用环回和接收自己消息
        print("\\n🔧 测试3: 同时启用环回和接收自己消息...")
        
        self.run_command("sudo ip link set can0 down")
        time.sleep(0.5)
        
        success, stdout, stderr = self.run_command(
            "sudo ip link set can0 up type can bitrate 500000 loopback on recv-own-msgs on"
        )
        
        if success:
            print("✅ 环回+接收自己消息模式启用成功")
            
            if self.test_loopback_communication():
                print("✅ 完整环回测试成功")
                return True
            else:
                print("❌ 完整环回测试失败")
        else:
            print(f"❌ 完整环回模式启用失败: {stderr}")
        
        return False
    
    def test_loopback_communication(self) -> bool:
        """测试环回通信"""
        print("  📡 启动CAN消息监听...")
        
        # 启动candump进程
        try:
            self.candump_process = subprocess.Popen(
                ['candump', 'can0'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # 等待candump启动
            time.sleep(1)
            
            # 发送测试消息
            print("  📤 发送测试消息...")
            for i in range(3):
                test_msg = f"12{i}#DEADBEE{i}"
                success, stdout, stderr = self.run_command(f"cansend can0 {test_msg}")
                if success:
                    print(f"    ✅ 发送消息 {test_msg}")
                else:
                    print(f"    ❌ 发送消息失败: {stderr}")
                time.sleep(0.5)
            
            # 等待接收
            time.sleep(2)
            
            # 停止candump并检查输出
            self.candump_process.terminate()
            stdout, stderr = self.candump_process.communicate(timeout=5)
            self.candump_process = None
            
            print("  📥 接收到的消息:")
            if stdout.strip():
                received_lines = stdout.strip().split('\\n')
                for line in received_lines:
                    if line.strip():
                        print(f"    🔊 {line.strip()}")
                        self.received_messages.append(line.strip())
                
                return len(received_lines) > 0
            else:
                print("    ❌ 未接收到任何消息")
                if stderr.strip():
                    print(f"    错误信息: {stderr.strip()}")
                return False
                
        except Exception as e:
            print(f"  ❌ 环回通信测试异常: {e}")
            if self.candump_process:
                try:
                    self.candump_process.terminate()
                    self.candump_process = None
                except:
                    pass
            return False
    
    def test_can_with_external_tool(self):
        """使用外部工具测试CAN通信"""
        print("\\n=== 使用can-utils进行详细测试 ===")
        
        # 测试cangen（CAN消息生成器）
        print("🔧 使用cangen生成测试消息...")
        
        try:
            # 启动candump监听
            candump_process = subprocess.Popen(
                ['timeout', '5', 'candump', 'can0'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            time.sleep(1)
            
            # 使用cangen生成消息
            cangen_process = subprocess.Popen(
                ['timeout', '3', 'cangen', 'can0', '-g', '100', '-I', '123'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # 等待完成
            cangen_stdout, cangen_stderr = cangen_process.communicate()
            candump_stdout, candump_stderr = candump_process.communicate()
            
            print("📤 cangen输出:")
            if cangen_stdout.strip():
                print(f"  {cangen_stdout.strip()}")
            if cangen_stderr.strip():
                print(f"  错误: {cangen_stderr.strip()}")
            
            print("📥 candump输出:")
            if candump_stdout.strip():
                print(f"  {candump_stdout.strip()}")
                return True
            else:
                print("  ❌ 未接收到cangen生成的消息")
                if candump_stderr.strip():
                    print(f"  错误: {candump_stderr.strip()}")
                return False
                
        except Exception as e:
            print(f"❌ can-utils测试异常: {e}")
            return False
    
    def check_can_kernel_modules(self):
        """检查CAN相关内核模块"""
        print("\\n=== CAN内核模块检查 ===")
        
        modules = ['can', 'can_raw', 'can_bcm', 'vcan', 'gs_usb']
        
        for module in modules:
            success, stdout, stderr = self.run_command(f"lsmod | grep {module}")
            if success and module in stdout:
                print(f"✅ {module} 模块已加载")
            else:
                print(f"⚠️ {module} 模块可能未加载")
                
                # 尝试加载can_raw（重要的CAN socket模块）
                if module == 'can_raw':
                    print(f"  🔧 尝试加载 {module}...")
                    load_success, _, load_stderr = self.run_command(f"sudo modprobe {module}")
                    if load_success:
                        print(f"  ✅ {module} 加载成功")
                    else:
                        print(f"  ❌ {module} 加载失败: {load_stderr}")
    
    def fix_can_loopback_issues(self):
        """修复CAN环回问题的完整流程"""
        print("CAN环回问题诊断和修复")
        print("=" * 50)
        
        # 检查接口详细信息
        self.check_can_interface_details()
        
        # 检查内核模块
        self.check_can_kernel_modules()
        
        # 测试不同环回模式
        if self.test_can_loopback_modes():
            print("\\n🎉 CAN环回问题已解决!")
            
            # 给出最终配置建议
            print("\\n📝 推荐的CAN配置:")
            print("sudo ip link set can0 down")
            print("sudo ip link set can0 up type can bitrate 500000 loopback on recv-own-msgs on")
            
            return True
        else:
            print("\\n❌ 标准环回测试失败，尝试外部工具测试...")
            
            if self.test_can_with_external_tool():
                print("\\n⚠️ 外部工具测试成功，可能是环回配置问题")
                print("建议在实际应用中测试与真实CAN设备的通信")
                return True
            else:
                print("\\n❌ 所有CAN通信测试都失败")
                print("\\n🔧 建议的排查步骤:")
                print("1. 检查CAN适配器硬件连接")
                print("2. 确认CAN总线终端电阻配置")
                print("3. 使用示波器检查CAN信号")
                print("4. 尝试不同的CAN适配器")
                return False
    
    def cleanup(self):
        """清理资源"""
        if self.candump_process:
            try:
                self.candump_process.terminate()
                self.candump_process.wait(timeout=2)
            except:
                try:
                    self.candump_process.kill()
                except:
                    pass
            self.candump_process = None

if __name__ == "__main__":
    fixer = CANLoopbackFixer()
    
    def signal_handler(sig, frame):
        print("\\n🛑 接收到中断信号，清理资源...")
        fixer.cleanup()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        success = fixer.fix_can_loopback_issues()
        if success:
            print("\\n✅ 现在可以测试Docker容器中的CAN访问")
        else:
            print("\\n❌ CAN环回问题未解决，需要进一步检查硬件")
    finally:
        fixer.cleanup()