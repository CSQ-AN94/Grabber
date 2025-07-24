#!/usr/bin/env python3
"""
创建虚拟UGV响应服务
模拟AgileX Ranger Mini 3底盘的CAN响应，让pyagxrobots库能正常初始化
"""

import subprocess
import threading
import time
import signal
import sys
import os
from typing import Dict, List

class VirtualUGVService:
    """虚拟UGV服务"""
    
    def __init__(self):
        self.running = False
        self.response_thread = None
        
        # AgileX Ranger Mini 3 CAN协议（基于常见配置）
        self.can_responses = {
            # 版本查询响应 (0x151)
            0x150: "151#0102030405060708",  # 版本查询 -> 版本响应
            
            # 状态查询响应
            0x421: "422#0000000000000000",  # 状态查询 -> 状态响应
            
            # 控制命令确认
            0x111: "112#0000000000000000",  # 运动控制 -> 确认响应
        }
        
        # 周期性发送的状态消息
        self.periodic_messages = [
            "422#0000000000000000",  # 底盘状态
            "423#0000000000000000",  # 传感器状态
        ]
        
        print("🤖 虚拟UGV服务初始化完成")
        print("📋 支持的CAN响应:")
        for query_id, response in self.can_responses.items():
            print(f"  0x{query_id:03X} -> {response}")
    
    def send_can_message(self, message: str) -> bool:
        """发送CAN消息"""
        try:
            result = subprocess.run(['cansend', 'can0', message], 
                                  capture_output=True, text=True)
            return result.returncode == 0
        except Exception:
            return False
    
    def start_periodic_responses(self):
        """启动周期性响应"""
        print("🔄 启动周期性状态广播...")
        
        def periodic_sender():
            while self.running:
                for message in self.periodic_messages:
                    if not self.running:
                        break
                    
                    if self.send_can_message(message):
                        print(f"📡 周期广播: {message}")
                    
                    time.sleep(0.1)  # 避免过于频繁
                
                time.sleep(1.0)  # 每秒发送一轮
        
        self.periodic_thread = threading.Thread(target=periodic_sender, daemon=True)
        self.periodic_thread.start()
    
    def start_response_service(self):
        """启动响应服务"""
        print("🚀 启动虚拟UGV响应服务...")
        
        try:
            # 启动candump监听查询消息
            self.candump_process = subprocess.Popen(
                ['candump', 'can0', '-t', 'z'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            self.running = True
            
            # 启动周期性响应
            self.start_periodic_responses()
            
            # 启动响应监听线程
            self.response_thread = threading.Thread(target=self._response_handler, daemon=True)
            self.response_thread.start()
            
            print("✅ 虚拟UGV服务已启动")
            return True
            
        except Exception as e:
            print(f"❌ 启动虚拟UGV服务失败: {e}")
            return False
    
    def _response_handler(self):
        """处理CAN消息并发送响应"""
        try:
            while self.running and self.candump_process:
                line = self.candump_process.stdout.readline()
                if line:
                    line = line.strip()
                    if line and 'can0' in line:
                        # 解析CAN消息
                        try:
                            # 提取CAN ID
                            parts = line.split()
                            if len(parts) >= 2:
                                can_part = parts[1]  # 格式: can0  150#01020304
                                
                                if '#' in can_part:
                                    id_str = can_part.split('#')[0]
                                    can_id = int(id_str, 16)
                                    
                                    print(f"📥 接收查询: ID=0x{can_id:03X}")
                                    
                                    # 检查是否需要响应
                                    if can_id in self.can_responses:
                                        response = self.can_responses[can_id]
                                        
                                        # 短暂延迟模拟真实设备响应时间
                                        time.sleep(0.01)
                                        
                                        if self.send_can_message(response):
                                            print(f"📤 发送响应: {response}")
                                        else:
                                            print(f"❌ 响应发送失败: {response}")
                                    
                        except (ValueError, IndexError):
                            # 忽略解析错误
                            pass
                else:
                    time.sleep(0.01)
                    
        except Exception as e:
            print(f"⚠️ 响应处理异常: {e}")
    
    def stop_service(self):
        """停止服务"""
        print("🛑 停止虚拟UGV服务...")
        
        self.running = False
        
        if hasattr(self, 'candump_process') and self.candump_process:
            try:
                self.candump_process.terminate()
                self.candump_process.wait(timeout=2)
            except:
                self.candump_process.kill()
            self.candump_process = None
        
        print("✅ 虚拟UGV服务已停止")
    
    def test_with_pyagxrobots(self):
        """测试与pyagxrobots的兼容性"""
        print("\\n🧪 测试pyagxrobots兼容性...")
        
        # 先发送一些初始响应确保服务正常
        initial_responses = [
            "151#0102030405060708",  # 版本响应
            "422#0000000000000000",  # 状态响应
        ]
        
        for response in initial_responses:
            self.send_can_message(response)
            time.sleep(0.1)
        
        # 等待服务稳定
        time.sleep(2)
        
        try:
            print("🤖 尝试初始化pyagxrobots...")
            import pyagxrobots
            
            ugv = pyagxrobots.pysdkugv.RangerBase()
            print("🎉 pyagxrobots初始化成功！")
            
            # 测试基本命令
            print("📡 测试运动控制命令...")
            ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
            print("✅ 运动控制命令发送成功")
            
            # 清理
            del ugv
            import gc
            gc.collect()
            
            print("🎊 虚拟UGV与pyagxrobots完全兼容！")
            return True
            
        except Exception as e:
            print(f"❌ pyagxrobots测试失败: {e}")
            
            # 显示详细错误
            import traceback
            print("🔍 详细错误信息:")
            traceback.print_exc()
            
            return False

def create_ugv_service_script():
    """创建UGV服务启动脚本"""
    print("\\n📝 创建UGV服务脚本...")
    
    service_script = '''#!/usr/bin/env python3
"""
AgileX Ranger Mini 3 虚拟底盘服务
在后台运行，响应pyagxrobots库的CAN查询
"""

import sys
import time
import signal
from scripts.create_virtual_ugv import VirtualUGVService

def main():
    print("启动AgileX虚拟底盘服务...")
    
    service = VirtualUGVService()
    
    def signal_handler(sig, frame):
        print("\\n接收到停止信号...")
        service.stop_service()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    if service.start_response_service():
        print("虚拟底盘服务运行中... (Ctrl+C 停止)")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    
    service.stop_service()

if __name__ == "__main__":
    main()
'''
    
    try:
        with open('/app/virtual_ugv_service.py', 'w') as f:
            f.write(service_script)
        
        os.chmod('/app/virtual_ugv_service.py', 0o755)
        print("✅ 服务脚本已创建: /app/virtual_ugv_service.py")
        return True
        
    except Exception as e:
        print(f"❌ 创建服务脚本失败: {e}")
        return False

def run_comprehensive_test():
    """运行完整的虚拟UGV测试"""
    print("AgileX虚拟底盘服务测试")
    print("=" * 50)
    print("目标: 让pyagxrobots库在没有真实底盘的情况下正常工作")
    print("=" * 50)
    
    # 创建服务脚本
    create_ugv_service_script()
    
    # 启动虚拟服务
    service = VirtualUGVService()
    
    def signal_handler(sig, frame):
        print("\\n🛑 接收到中断信号...")
        service.stop_service()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        if service.start_response_service():
            print("\\n⏳ 等待5秒让服务稳定...")
            time.sleep(5)
            
            # 测试兼容性
            success = service.test_with_pyagxrobots()
            
            if success:
                print("\\n🎉 测试成功！解决方案:")
                print("1. 在容器中运行虚拟底盘服务:")
                print("   python3 virtual_ugv_service.py &")
                print("2. 然后运行你的应用:")
                print("   python3 main.py")
                print("\\n💡 或者集成到应用启动流程中")
            else:
                print("\\n🔧 需要调整CAN响应格式或协议")
                print("建议连接真实底盘进行协议分析")
            
            return success
            
    except KeyboardInterrupt:
        print("\\n⏹️ 测试被用户中断")
        return False
    finally:
        service.stop_service()

if __name__ == "__main__":
    run_comprehensive_test()