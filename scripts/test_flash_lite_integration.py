#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FlashLite Agent与改进VAD集成测试
测试端到端的语音理解功能，验证VAD改进效果
"""

import sys
import os
import time
import asyncio
import logging
from datetime import datetime

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.flash_lite_agent import FlashLiteAgent, RobotCommand
from utils.config import load_config


class FlashLiteIntegrationTester:
    """FlashLite Agent集成测试器"""
    
    def __init__(self):
        # 加载配置
        try:
            config = load_config()
            self.llm_config = config.llm
            self.agent_config = config.agent
        except Exception as e:
            print(f"❌ 配置加载失败: {e}")
            print("使用默认配置...")
            # 创建默认配置
            from utils.config import LLMConfig, AgentConfig
            self.llm_config = LLMConfig(
                gemini_api_key="your_api_key_here",  # 需要真实API key
                model_name="gemini-2.5-flash-lite"
            )
            self.agent_config = AgentConfig(
                audio_sample_rate=16000,
                audio_chunk_size=1024,
                response_timeout=10.0
            )
        
        # 初始化工具注册表（Mock版本）
        self.tool_registry = self._create_mock_tool_registry()
        
        # 初始化FlashLite Agent
        self.agent = FlashLiteAgent(
            llm_config=self.llm_config,
            agent_config=self.agent_config,
            tool_registry=self.tool_registry
        )
        
        # 测试统计
        self.test_start_time = None
        self.commands_received = []
        
        # 设置日志
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        self.logger = logging.getLogger(__name__)
    
    def _create_mock_tool_registry(self):
        """创建Mock工具注册表"""
        class MockToolRegistry:
            def get_tool_definitions(self):
                return [{
                    "function_declarations": [
                        {
                            "name": "scan_shelf", 
                            "description": "扫描货架上的商品",
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "shelf_level": {
                                        "type": "string",
                                        "description": "货架层级",
                                        "enum": ["top", "bottom", "all"]
                                    }
                                },
                                "required": ["shelf_level"]
                            }
                        },
                        {
                            "name": "grab_item",
                            "description": "抓取指定商品", 
                            "parameters": {
                                "type": "object",
                                "properties": {
                                    "item_name": {
                                        "type": "string",
                                        "description": "商品名称"
                                    }
                                },
                                "required": ["item_name"]
                            }
                        }
                    ]
                }]
            
            async def execute_tool(self, tool_name: str, args: dict):
                """Mock工具执行"""
                print(f"🔧 Mock执行: {tool_name}({args})")
                await asyncio.sleep(0.5)
                return {
                    "success": True,
                    "message": f"成功执行{tool_name}操作",
                    "data": {"mock_result": True}
                }
        
        return MockToolRegistry()
    
    def setup_agent_callbacks(self):
        """设置Agent回调"""
        def on_robot_command(command: RobotCommand):
            """接收机器人命令回调"""
            current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            
            print(f"\n🤖 [{current_time}] 收到机器人命令:")
            print(f"   动作: {command.action}")
            print(f"   参数: {command.parameters}")
            print(f"   响应: {command.response_text}")
            print(f"   置信度: {command.confidence}")
            
            # 记录命令
            self.commands_received.append({
                'timestamp': current_time,
                'action': command.action,
                'parameters': command.parameters,
                'response_text': command.response_text,
                'confidence': command.confidence
            })
        
        return on_robot_command
    
    async def run_integration_test(self):
        """运行集成测试"""
        print("=== FlashLite Agent与改进VAD集成测试 ===")
        print("测试目标:")
        print("1. 验证改进VAD与FlashLite Agent的端到端集成") 
        print("2. 测试语音理解和工具调用功能")
        print("3. 验证VAD改进效果（语句完整性）")
        print("4. 测试TTS响应播报")
        print("5. 验证整体系统性能")
        print()
        
        # 检查API配置
        if not self.llm_config.gemini_api_key or self.llm_config.gemini_api_key == "your_api_key_here":
            print("⚠️ 警告: 未配置Gemini API密钥")
            print("将运行Mock模式，无法测试真实AI响应")
            print("要测试完整功能，请在config.yaml中配置正确的API密钥")
            print()
        
        try:
            # 设置回调
            command_callback = self.setup_agent_callbacks()
            
            print("✅ 正在启动FlashLite Agent...")
            print("⏳ 初始化语音识别和AI模型...")
            
            # 启动Agent会话
            self.test_start_time = time.time()
            
            # 启动交互式会话
            session_task = asyncio.create_task(
                self.agent.start_interactive_session(command_callback)
            )
            
            print("✅ FlashLite Agent会话已启动")
            print()
            print("=== 开始语音交互测试 ===")
            print("请进行以下测试:")
            print("1. 说: '扫描一下货架上的商品'")
            print("2. 说: '帮我拿一瓶可口可乐'") 
            print("3. 说: '货架上有什么苹果吗？'")
            print("4. 测试长语句: '请帮我扫描货架上的所有商品，然后拿一个苹果给我'")
            print("5. 测试中断和重说")
            print()
            print("观察要点:")
            print("- VAD是否能检测完整语句（不再分割为短片段）")
            print("- AI是否能正确理解语音内容")
            print("- 工具调用是否准确执行")
            print("- TTS响应是否清晰")
            print()
            print("按 Ctrl+C 停止测试")
            print()
            
            # 启动实时统计
            stats_task = asyncio.create_task(self._print_real_time_stats())
            
            # 等待用户交互
            await asyncio.gather(session_task, stats_task, return_exceptions=True)
            
        except KeyboardInterrupt:
            print("\n\n⏹️ 用户停止测试")
        except Exception as e:
            print(f"\n❌ 测试过程出错: {e}")
        finally:
            # 停止Agent
            await self.agent.stop_session()
            self._print_final_summary()
    
    async def _print_real_time_stats(self):
        """显示实时统计"""
        while True:
            try:
                await asyncio.sleep(10)  # 每10秒显示一次
                
                # 获取Agent统计
                agent_stats = self.agent.get_session_stats()
                
                # 获取VAD统计
                vad_stats = self.agent.vad.get_stats()
                
                uptime = time.time() - self.test_start_time
                
                print(f"\n📊 实时统计 (运行时间: {uptime:.1f}秒)")
                print(f"   语句处理: {agent_stats.get('utterances_processed', 0)}")
                print(f"   工具调用: {agent_stats.get('tool_calls_made', 0)}")
                print(f"   TTS响应: {agent_stats.get('tts_responses', 0)}")
                print(f"   错误次数: {agent_stats.get('errors', 0)}")
                print(f"   VAD语句: {vad_stats['utterance_count']}")
                print(f"   平均语句长度: {vad_stats['average_utterance_length']:.2f}秒")
                print(f"   音频源: {vad_stats['audio_source']}")
                print(f"   当前状态: {'🎤 语音中' if vad_stats['is_in_speech'] else '🤫 静音中'}")
                
            except Exception as e:
                self.logger.debug(f"统计显示错误: {e}")
                break
    
    def _print_final_summary(self):
        """显示最终测试总结"""
        total_time = time.time() - self.test_start_time if self.test_start_time else 0
        agent_stats = self.agent.get_session_stats()
        vad_stats = self.agent.vad.get_stats()
        
        print("\n" + "="*70)
        print("📋 FlashLite Agent集成测试总结")
        print("="*70)
        
        # 基本统计
        print(f"测试时长: {total_time:.1f}秒")
        print(f"语句处理: {agent_stats.get('utterances_processed', 0)}")
        print(f"工具调用: {agent_stats.get('tool_calls_made', 0)}")
        print(f"TTS响应: {agent_stats.get('tts_responses', 0)}")
        print(f"错误次数: {agent_stats.get('errors', 0)}")
        
        # VAD改进效果
        print(f"\n🎤 VAD改进效果:")
        print(f"   检测语句: {vad_stats['utterance_count']}")
        print(f"   总语音时长: {vad_stats['total_speech_duration']:.1f}秒")
        print(f"   平均语句长度: {vad_stats['average_utterance_length']:.2f}秒")
        print(f"   音频源: {vad_stats['audio_source']}")
        
        # 命令详情
        if self.commands_received:
            print(f"\n🤖 执行的命令详情:")
            for i, cmd in enumerate(self.commands_received, 1):
                print(f"   {i}. [{cmd['timestamp']}] {cmd['action']}({cmd['parameters']})")
                print(f"      响应: {cmd['response_text'][:50]}...")
        
        # 效果评估
        print(f"\n🔍 系统性能评估:")
        
        # VAD改进评估
        avg_length = vad_stats['average_utterance_length']
        if avg_length > 2.0:
            print("✅ VAD语句长度: 优秀 (>2秒)")
        elif avg_length > 1.0:
            print("✅ VAD语句长度: 良好 (>1秒)")  
        elif avg_length > 0.5:
            print("⚠️ VAD语句长度: 一般 (>0.5秒)")
        else:
            print("❌ VAD语句长度: 需改进 (<0.5秒)")
        
        print(f"\n✅ 集成测试完成")


async def main():
    """主函数"""
    print("开始FlashLite Agent集成测试...")
    print("请确保在Docker容器内运行此脚本")
    print()
    
    tester = FlashLiteIntegrationTester()
    
    try:
        await tester.run_integration_test()
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return 1
    
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️ 测试被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 测试脚本异常: {e}")
        sys.exit(1)