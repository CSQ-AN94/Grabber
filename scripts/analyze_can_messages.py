#!/usr/bin/env python3
"""
分析CAN消息通信问题
监听pyagxrobots库尝试发送的消息，模拟底盘响应
"""

import subprocess
import threading
import time
import signal
import sys
import socket
import struct

class CANMessageAnalyzer:
    """CAN消息分析器"""
    
    def __init__(self):
        self.monitoring = False
        self.candump_process = None
        self.sent_messages = []
        self.received_messages = []
    
    def start_can_monitoring(self):
        """启动CAN消息监听"""
        print("🔍 启动CAN消息监听，查看pyagxrobots发送的消息...")
        
        try:
            self.candump_process = subprocess.Popen(
                ['candump', 'can0', '-t', 'z', '-x'],  # -x 显示扩展信息
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            self.monitoring = True
            
            # 启动监听线程
            threading.Thread(target=self._monitor_messages, daemon=True).start()
            
            time.sleep(0.5)
            return True
            
        except Exception as e:
            print(f"❌ 启动监听失败: {e}")
            return False
    
    def _monitor_messages(self):
        """监听CAN消息"""
        try:
            while self.monitoring and self.candump_process:
                line = self.candump_process.stdout.readline()
                if line:
                    line = line.strip()
                    if line:
                        print(f"📡 CAN消息: {line}")
                        
                        # 分析消息
                        if "150" in line or "151" in line:
                            print(f"🎯 底盘通信消息: {line}")
                        
                        self.received_messages.append(line)
                else:
                    time.sleep(0.01)
        except Exception as e:
            print(f"⚠️ 监听异常: {e}")
    
    def send_mock_base_version_response(self):
        """发送模拟的底盘版本响应"""
        print("🤖 发送模拟底盘版本响应...")
        
        try:
            # AgileX底盘版本响应格式（需要研究具体格式）
            # ID 0x151 通常是版本查询响应
            
            # 尝试几种可能的响应格式
            test_responses = [
                "151#0102030405060708",  # 基本版本响应
                "151#01000000000000000",  # 另一种格式
                "151#FFFFFFFFFFFFFFFF",   # 测试响应
            ]
            
            for response in test_responses:
                print(f"📤 发送: {response}")
                result = subprocess.run(['cansend', 'can0', response], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    print(f"✅ 发送成功: {response}")
                else:
                    print(f"❌ 发送失败: {result.stderr}")
                
                time.sleep(0.1)
            
            return True
            
        except Exception as e:
            print(f"❌ 发送模拟响应失败: {e}")
            return False
    
    def test_with_mock_responses(self):
        """在发送模拟响应的同时测试pyagxrobots"""
        print("🧪 测试pyagxrobots + 模拟响应...")
        
        # 启动后台响应发送
        def send_continuous_responses():
            """持续发送响应"""
            for i in range(10):  # 发送10次
                if not self.monitoring:
                    break
                
                # 发送版本响应
                subprocess.run(['cansend', 'can0', '151#0102030405060708'], 
                             capture_output=True)
                
                time.sleep(0.5)
        
        # 启动响应线程
        response_thread = threading.Thread(target=send_continuous_responses, daemon=True)
        response_thread.start()
        
        # 短暂延迟后测试pyagxrobots
        time.sleep(1)
        
        try:
            print("🤖 测试pyagxrobots初始化...")
            import pyagxrobots
            
            ugv = pyagxrobots.pysdkugv.RangerBase()
            print("🎉 成功！模拟响应有效")
            
            # 测试基本命令
            ugv.SetMotionCommand(0.0, 0.0, 0.0, 0.0)
            print("✅ 命令发送成功")
            
            del ugv
            return True
            
        except Exception as e:
            print(f"❌ 仍然失败: {e}")
            return False
    
    def stop_monitoring(self):
        """停止监听"""
        self.monitoring = False
        
        if self.candump_process:
            try:
                self.candump_process.terminate()
                self.candump_process.wait(timeout=2)
            except:
                self.candump_process.kill()
            self.candump_process = None
    
    def analyze_agx_communication(self):
        """分析AgileX通信协议"""
        print("AgileX Ranger Mini 3 CAN通信分析")
        print("=" * 50)
        
        try:
            # 启动监听
            if not self.start_can_monitoring():
                return False
            
            print("\\n阶段1: 监听pyagxrobots尝试的通信...")
            print("请在另一个终端运行: python3 -c \"import pyagxrobots; pyagxrobots.pysdkugv.RangerBase()\"")
            print("或者等待10秒后自动测试...")
            
            # 等待或手动触发
            time.sleep(10)
            
            print("\\n阶段2: 尝试发送模拟响应...")
            self.send_mock_base_version_response()
            
            print("\\n阶段3: 测试模拟响应效果...")
            success = self.test_with_mock_responses()
            
            print("\\n阶段4: 分析结果...")
            print(f"📋 捕获的消息数量: {len(self.received_messages)}")
            
            if self.received_messages:
                print("📋 CAN消息样本:")
                for msg in self.received_messages[:5]:
                    print(f"  {msg}")
            
            return success
            
        except KeyboardInterrupt:
            print("\\n⏹️ 分析被用户中断")
            return False
        finally:
            self.stop_monitoring()

def test_direct_can_communication():
    """直接测试CAN通信"""
    print("\\n=== 直接CAN通信测试 ===")
    
    try:
        # 使用Python socket直接发送CAN消息
        import socket
        import struct
        
        # 创建CAN socket
        can_socket = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        can_socket.bind(('can0',))
        
        print("✅ CAN socket创建成功")
        
        # 构造CAN消息
        # CAN ID 0x150 - 版本查询
        can_id = 0x150
        data = b'\\x01\\x02\\x03\\x04\\x05\\x06\\x07\\x08'
        
        # CAN frame格式: ID (4字节) + DLC (1字节) + 数据 (8字节) + 填充
        frame = struct.pack("=IB3x8s", can_id, len(data), data)
        
        print(f"📤 发送CAN消息: ID=0x{can_id:03X}, 数据={data.hex()}")
        can_socket.send(frame)
        print("✅ 消息发送成功")
        
        # 设置接收超时
        can_socket.settimeout(2.0)
        
        try:
            # 尝试接收响应
            response = can_socket.recv(16)
            response_id, response_dlc = struct.unpack("=IB3x", response[:8])
            response_data = response[8:]
            
            print(f"📥 接收到响应: ID=0x{response_id:03X}, 数据={response_data.hex()}")
            
        except socket.timeout:
            print("⏰ 接收超时 - 没有设备响应")
        
        can_socket.close()
        return True
        
    except Exception as e:
        print(f"❌ 直接CAN通信失败: {e}")
        return False

if __name__ == "__main__":
    print("CAN消息通信问题分析")
    print("=" * 50)
    print("目标: 理解pyagxrobots为什么无法获取底盘版本")
    print("=" * 50)
    
    # 直接CAN测试
    test_direct_can_communication()
    
    # 详细分析
    analyzer = CANMessageAnalyzer()
    
    def signal_handler(sig, frame):
        print("\\n🛑 接收到中断信号...")
        analyzer.stop_monitoring()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        success = analyzer.analyze_agx_communication()
        
        if success:
            print("\\n🎉 找到了解决方案！")
        else:
            print("\\n🔧 需要进一步分析...")
            print("\\n💡 可能的解决方案:")
            print("1. 连接真实的AgileX底盘")
            print("2. 修改pyagxrobots库跳过版本检查")
            print("3. 创建虚拟底盘响应服务")
            
    finally:
        analyzer.stop_monitoring()