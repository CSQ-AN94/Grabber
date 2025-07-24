#!/usr/bin/env python3
"""
Ranger Mini底盘通信问题专项诊断
基于官方UGV SDK文档的问题排查方法
"""

import subprocess
import time
import threading
import signal
import sys
from typing import Dict, List, Optional

class RangerMiniDiagnostic:
    """Ranger Mini底盘诊断器"""
    
    def __init__(self):
        self.monitoring = False
        self.candump_process = None
        self.received_messages = []
        
        # AgileX Ranger Mini的关键CAN ID（基于SDK文档）
        self.agx_can_ids = {
            # 版本和状态查询
            0x150: "版本查询请求",
            0x151: "版本查询响应", 
            
            # 控制命令
            0x111: "运动控制命令",
            0x112: "运动控制响应",
            
            # 状态报告
            0x211: "底盘状态1",
            0x212: "底盘状态2", 
            0x221: "传感器状态",
            
            # 其他可能的ID
            0x421: "扩展状态查询",
            0x422: "扩展状态响应",
        }
    
    def start_can_monitoring(self):
        """启动CAN监听"""
        print("🔍 启动CAN消息监听...")
        
        try:
            self.candump_process = subprocess.Popen(
                ['candump', 'can0', '-t', 'z', '-x'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, 
                text=True,
                bufsize=1
            )
            
            self.monitoring = True
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
                    if line and 'can0' in line:
                        self.received_messages.append(line)
                        
                        # 解析消息ID
                        try:
                            parts = line.split()
                            if len(parts) >= 2:
                                can_part = parts[1]
                                if '#' in can_part:
                                    id_str = can_part.split('#')[0]
                                    can_id = int(id_str, 16)
                                    
                                    # 标记重要消息
                                    if can_id in self.agx_can_ids:
                                        desc = self.agx_can_ids[can_id]
                                        print(f"🎯 AgileX消息: 0x{can_id:03X} - {desc}")
                                        print(f"   完整消息: {line}")
                                    else:
                                        print(f"📡 其他消息: {line}")
                        except:
                            print(f"📡 消息: {line}")
                else:
                    time.sleep(0.01)
        except Exception as e:
            print(f"⚠️ 监听异常: {e}")
    
    def test_manual_version_query(self):
        """手动测试版本查询"""
        print("\\n🔧 手动版本查询测试...")
        
        # 发送版本查询（模拟pyagxrobots行为）
        version_query_commands = [
            "150#0000000000000000",  # 空数据版本查询
            "150#0100000000000000",  # 带标识的版本查询
            "150#FFFFFFFFFFFFFFFF",  # 全FF查询
        ]
        
        print("📤 发送版本查询命令...")
        for cmd in version_query_commands:
            print(f"  发送: {cmd}")
            result = subprocess.run(['cansend', 'can0', cmd], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  ✅ 发送成功")
            else:
                print(f"  ❌ 发送失败: {result.stderr}")
            
            time.sleep(0.5)  # 等待响应
        
        print("⏳ 等待3秒观察响应...")
        time.sleep(3)
        
        # 检查是否收到0x151响应
        version_responses = [msg for msg in self.received_messages if '151' in msg]
        
        if version_responses:
            print("✅ 收到版本响应:")
            for resp in version_responses:
                print(f"  📥 {resp}")
            return True
        else:
            print("❌ 未收到版本响应 (0x151)")
            return False
    
    def test_pyagxrobots_with_monitoring(self):
        """在监听状态下测试pyagxrobots"""
        print("\\n🤖 监听状态下测试pyagxrobots...")
        
        # 清空之前的消息
        self.received_messages.clear()
        
        print("📋 开始pyagxrobots初始化...")
        print("预期: 应该看到发送到0x150的版本查询")
        
        try:
            import pyagxrobots
            
            print("🚀 执行: pyagxrobots.pysdkugv.RangerBase()")
            ugv = pyagxrobots.pysdkugv.RangerBase()
            
            print("🎉 初始化成功！")
            
            # 测试命令
            ugv.SetMotionCommand(0.0, 0.0, 0.0, 0.0)
            print("✅ 命令发送成功")
            
            del ugv
            return True
            
        except Exception as e:
            print(f"❌ 初始化失败: {e}")
            
            # 分析捕获的消息
            print("\\n📋 初始化过程中的CAN消息:")
            recent_messages = self.received_messages[-10:]  # 最近10条消息
            
            if recent_messages:
                for msg in recent_messages:
                    print(f"  {msg}")
                
                # 检查是否有版本查询
                version_queries = [msg for msg in recent_messages if '150' in msg]
                version_responses = [msg for msg in recent_messages if '151' in msg]
                
                print(f"\\n📊 分析结果:")
                print(f"  版本查询 (0x150): {len(version_queries)} 条")
                print(f"  版本响应 (0x151): {len(version_responses)} 条")
                
                if version_queries and not version_responses:
                    print("\\n💡 问题确认: pyagxrobots发送了版本查询，但没有收到响应")
                    print("原因: 没有真实的Ranger Mini底盘连接到CAN总线")
                elif not version_queries:
                    print("\\n💡 问题可能: pyagxrobots甚至没有发送版本查询")
                    print("原因: CAN接口初始化可能失败")
            else:
                print("  无CAN消息捕获")
                print("\\n💡 问题可能: CAN通信完全失败")
            
            return False
    
    def check_ranger_mini_version_compatibility(self):
        """检查Ranger Mini版本兼容性"""
        print("\\n🔍 Ranger Mini版本兼容性检查...")
        print("基于官方SDK文档:")
        print("  - Ranger Mini 1.0: 已停产，使用修改版Protocol V2")
        print("  - Ranger Mini 2.0: 当前版本，使用标准Protocol V2")
        print("  - Ranger Mini 3.0: 可能使用Protocol V2")
        
        print("\\n💡 如果您使用Ranger Mini 1.0:")
        print("  需要使用特殊的RangerMiniV1Robot类")
        print("  但pyagxrobots可能不支持此特殊处理")
        
        print("\\n🤔 确认您的底盘型号:")
        print("  1. 检查底盘标签或文档") 
        print("  2. 如果是Mini 1.0，可能需要特殊配置")
        print("  3. 如果是Mini 2.0/3.0，应该使用标准配置")
    
    def provide_solutions(self):
        """提供解决方案"""
        print("\\n🛠️ 解决方案建议:")
        print("=" * 50)
        
        print("\\n1. 【验证底盘连接】")
        print("   - 确认Ranger Mini已开机")
        print("   - 检查CAN线缆连接")
        print("   - 验证底盘LED状态指示灯")
        
        print("\\n2. 【确认底盘型号】")
        print("   - 如果是Ranger Mini 1.0 (已停产)")
        print("     可能需要修改pyagxrobots库或使用不同的接口")
        print("   - 如果是Ranger Mini 2.0/3.0")
        print("     应该可以正常工作")
        
        print("\\n3. 【检查CAN波特率】")
        print("   - 当前设置: 500000")
        print("   - 尝试其他波特率: 250000, 1000000")
        print("   - 命令: sudo ip link set can0 down")
        print("           sudo ip link set can0 up type can bitrate 250000")
        
        print("\\n4. 【调试模式测试】")
        print("   - 使用官方SDK的demo程序")
        print("   - 如果有C++ demo，先测试C++版本")
        print("   - 确认底盘基本通信后再使用Python包装")
        
        print("\\n5. 【联系技术支持】")
        print("   - AgileX官方技术支持")
        print("   - 提供CAN总线日志文件")
        print("   - 提供底盘型号和固件版本")
    
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
    
    def run_comprehensive_diagnosis(self):
        """运行完整诊断"""
        print("Ranger Mini底盘通信问题专项诊断")
        print("=" * 60)
        print("基于官方UGV SDK文档的问题排查方法")
        print("目标: 解决'arbitration_id'错误问题")
        print("=" * 60)
        
        try:
            # 启动监听
            if not self.start_can_monitoring():
                print("❌ 无法启动CAN监听，诊断终止")
                return
            
            print("✅ CAN监听已启动")
            
            # 版本兼容性检查
            self.check_ranger_mini_version_compatibility()
            
            # 手动版本查询测试
            has_response = self.test_manual_version_query()
            
            # pyagxrobots测试
            init_success = self.test_pyagxrobots_with_monitoring()
            
            # 结果分析
            print("\\n" + "=" * 60)
            print("🏁 诊断结果总结")
            print("=" * 60)
            
            if init_success:
                print("🎉 问题已解决！pyagxrobots可以正常使用")
            elif has_response:
                print("⚠️ 底盘有响应，但pyagxrobots仍失败")
                print("可能是协议版本或库兼容性问题")
            else:
                print("❌ 底盘无响应，确认是硬件连接问题")
                print("需要检查底盘是否开机和CAN连接")
            
            # 提供解决方案
            self.provide_solutions()
            
        except KeyboardInterrupt:
            print("\\n⏹️ 诊断被用户中断")
        finally:
            self.stop_monitoring()

if __name__ == "__main__":
    diagnostic = RangerMiniDiagnostic()
    
    def signal_handler(sig, frame):
        print("\\n🛑 接收到中断信号...")
        diagnostic.stop_monitoring()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    diagnostic.run_comprehensive_diagnosis()