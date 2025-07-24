#!/usr/bin/env python3
"""
实时CAN通信测试
同时进行发送和监听，真正测试CAN通信链路
"""

import subprocess
import threading
import time
import signal
import sys
from typing import List, Dict, Optional

class RealtimeCANTester:
    """实时CAN通信测试器"""
    
    def __init__(self):
        self.candump_process = None
        self.monitoring_thread = None
        self.received_messages = []
        self.is_monitoring = False
        self.test_results = {
            'sent_messages': [],
            'received_messages': [],
            'candump_errors': [],
            'send_errors': []
        }
    
    def run_command(self, cmd: str, timeout: int = 10):
        """运行命令"""
        try:
            result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
            return result.returncode == 0, result.stdout, result.stderr
        except subprocess.TimeoutExpired:
            return False, "", "Command timed out"
        except Exception as e:
            return False, "", str(e)
    
    def start_can_monitoring(self):
        """启动CAN监听"""
        print("🔍 启动CAN消息监听...")
        
        try:
            # 启动candump进程
            self.candump_process = subprocess.Popen(
                ['candump', 'can0', '-t', 'z'],  # -t z 添加时间戳
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                universal_newlines=True
            )
            
            self.is_monitoring = True
            
            # 启动监听线程
            self.monitoring_thread = threading.Thread(target=self._monitor_can_messages, daemon=True)
            self.monitoring_thread.start()
            
            # 等待candump启动
            time.sleep(0.5)
            
            # 检查进程是否正常启动
            if self.candump_process.poll() is None:
                print("✅ CAN监听启动成功")
                return True
            else:
                stderr_output = self.candump_process.stderr.read()
                print(f"❌ CAN监听启动失败: {stderr_output}")
                self.test_results['candump_errors'].append(stderr_output)
                return False
                
        except Exception as e:
            print(f"❌ CAN监听启动异常: {e}")
            self.test_results['candump_errors'].append(str(e))
            return False
    
    def _monitor_can_messages(self):
        """CAN消息监听线程"""
        try:
            while self.is_monitoring and self.candump_process and self.candump_process.poll() is None:
                line = self.candump_process.stdout.readline()
                if line:
                    line = line.strip()
                    if line:
                        print(f"📥 接收: {line}")
                        self.received_messages.append(line)
                        self.test_results['received_messages'].append(line)
                else:
                    time.sleep(0.01)  # 避免忙等待
        except Exception as e:
            print(f"⚠️ 监听线程异常: {e}")
    
    def send_test_messages(self, count: int = 5):
        """发送测试消息"""
        print(f"📤 发送 {count} 条测试消息...")
        
        success_count = 0
        
        for i in range(count):
            # 构造测试消息
            can_id = f"{100 + i:03X}"  # 从100开始的十六进制ID
            data = f"DEADBEE{i:X}"
            message = f"{can_id}#{data}"
            
            print(f"  📤 发送消息 {i+1}/{count}: {message}")
            
            # 发送消息
            success, stdout, stderr = self.run_command(f"cansend can0 {message}")
            
            if success:
                print(f"    ✅ 发送成功")
                success_count += 1
                self.test_results['sent_messages'].append(message)
            else:
                print(f"    ❌ 发送失败: {stderr}")
                self.test_results['send_errors'].append(stderr)
            
            # 发送间隔
            time.sleep(0.2)
        
        print(f"📊 发送统计: {success_count}/{count} 成功")
        return success_count
    
    def stop_can_monitoring(self):
        """停止CAN监听"""
        print("🛑 停止CAN监听...")
        
        self.is_monitoring = False
        
        if self.candump_process:
            try:
                self.candump_process.terminate()
                self.candump_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.candump_process.kill()
                self.candump_process.wait()
            except Exception as e:
                print(f"⚠️ 停止监听进程时出错: {e}")
            
            self.candump_process = None
        
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.monitoring_thread.join(timeout=1)
    
    def analyze_results(self):
        """分析测试结果"""
        print("\\n" + "="*50)
        print("📊 CAN通信测试结果分析")
        print("="*50)
        
        sent_count = len(self.test_results['sent_messages'])
        received_count = len(self.test_results['received_messages'])
        
        print(f"📤 发送消息数: {sent_count}")
        print(f"📥 接收消息数: {received_count}")
        
        if sent_count > 0:
            print(f"📈 接收率: {received_count/sent_count*100:.1f}%")
        
        # 详细分析
        if received_count > 0:
            print("\\n✅ CAN通信正常工作!")
            print("📋 接收到的消息:")
            for msg in self.test_results['received_messages'][:5]:  # 只显示前5条
                print(f"  {msg}")
            if len(self.test_results['received_messages']) > 5:
                print(f"  ... 还有 {len(self.test_results['received_messages']) - 5} 条消息")
            return True
        
        elif sent_count > 0 and received_count == 0:
            print("\\n⚠️ 发送成功但未接收到消息")
            print("可能原因:")
            print("1. CAN环回配置问题")
            print("2. candump命令问题")
            print("3. CAN适配器固件问题")
            
            # 检查candump错误
            if self.test_results['candump_errors']:
                print("\\n❌ candump错误:")
                for error in self.test_results['candump_errors']:
                    print(f"  {error}")
            
            return False
        
        else:
            print("\\n❌ 发送和接收都失败")
            
            if self.test_results['send_errors']:
                print("📤 发送错误:")
                for error in self.test_results['send_errors']:
                    print(f"  {error}")
            
            if self.test_results['candump_errors']:
                print("📥 接收错误:")
                for error in self.test_results['candump_errors']:
                    print(f"  {error}")
            
            return False
    
    def test_can_interface_status(self):
        """测试CAN接口状态"""
        print("=== CAN接口状态检查 ===")
        
        # 检查接口配置
        success, stdout, stderr = self.run_command("ip -d link show can0")
        if success:
            print("📡 can0接口详细信息:")
            for line in stdout.split('\\n'):
                if line.strip():
                    print(f"  {line.strip()}")
            
            # 检查是否启用了环回
            if 'loopback on' in stdout.lower():
                print("✅ 环回模式已启用")
            else:
                print("⚠️ 环回模式未启用")
                
            if 'recv-own-msgs on' in stdout.lower():
                print("✅ 接收自己消息已启用")
            else:
                print("⚠️ 接收自己消息未启用")
        else:
            print(f"❌ 无法获取can0接口信息: {stderr}")
            return False
        
        return True
    
    def run_comprehensive_test(self):
        """运行综合CAN测试"""
        print("实时CAN通信综合测试")
        print("=" * 50)
        
        # 检查接口状态
        if not self.test_can_interface_status():
            return False
        
        try:
            # 启动监听
            if not self.start_can_monitoring():
                print("❌ 无法启动CAN监听，测试终止")
                return False
            
            # 等待监听稳定
            time.sleep(1)
            
            # 发送测试消息
            sent_count = self.send_test_messages(5)
            
            if sent_count == 0:
                print("❌ 无法发送任何消息，测试终止")
                return False
            
            # 等待接收
            print("⏳ 等待3秒接收消息...")
            time.sleep(3)
            
            # 分析结果
            success = self.analyze_results()
            
            return success
            
        except KeyboardInterrupt:
            print("\\n⏹️ 测试被用户中断")
            return False
        except Exception as e:
            print(f"❌ 测试过程异常: {e}")
            return False
        finally:
            self.stop_can_monitoring()
    
    def cleanup(self):
        """清理资源"""
        self.stop_can_monitoring()

def test_candump_alone():
    """单独测试candump命令"""
    print("\\n=== 单独测试candump命令 ===")
    
    # 测试candump是否能正常启动
    try:
        print("🔧 测试candump启动...")
        process = subprocess.Popen(
            ['candump', 'can0'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # 等待1秒
        time.sleep(1)
        
        # 检查进程状态
        if process.poll() is None:
            print("✅ candump进程正常运行")
            
            # 终止进程
            process.terminate()
            process.wait(timeout=2)
            
            return True
        else:
            # 进程已退出，获取错误信息
            stdout, stderr = process.communicate()
            print(f"❌ candump进程退出")
            if stderr:
                print(f"  错误: {stderr}")
            if stdout:
                print(f"  输出: {stdout}")
            return False
            
    except Exception as e:
        print(f"❌ candump测试异常: {e}")
        return False

if __name__ == "__main__":
    # 首先测试candump
    candump_ok = test_candump_alone()
    
    if not candump_ok:
        print("\\n❌ candump命令本身有问题，无法进行综合测试")
        print("💡 建议:")
        print("1. 重新安装can-utils: sudo apt install --reinstall can-utils")
        print("2. 检查can0接口权限")
        print("3. 检查CAN接口是否正确配置")
        sys.exit(1)
    
    # 综合测试
    tester = RealtimeCANTester()
    
    def signal_handler(sig, frame):
        print("\\n🛑 接收到中断信号，清理资源...")
        tester.cleanup()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        success = tester.run_comprehensive_test()
        
        if success:
            print("\\n🎉 CAN通信测试通过！")
            print("✅ 现在可以测试Docker容器中的pyagxrobots库")
        else:
            print("\\n❌ CAN通信测试失败")
            print("🔧 建议进一步排查:")
            print("1. 检查CAN适配器硬件")
            print("2. 尝试其他CAN测试工具")
            print("3. 检查系统日志: dmesg | grep can")
            
    finally:
        tester.cleanup()