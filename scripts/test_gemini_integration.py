#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini Live API 完整集成测试
测试语音交互、工具调用和完整的对话流程
"""

import sys
import os
import asyncio
import logging
import argparse

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from utils.state import WorldState
from intelligence.gemini_agent import GeminiAgent, RobotCommand
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from intelligence.speech import SpeechSystem

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class GeminiIntegrationTest:
    """Gemini Live API集成测试"""
    
    def __init__(self):
        self.config = None
        self.world_state = None
        self.robot_tools = None
        self.tool_registry = None
        self.gemini_agent = None
        self.speech_system = None
        self.commands_received = []
        
    async def setup(self):
        """初始化测试环境"""
        print("🔧 初始化测试环境...")
        
        # 加载配置
        self.config = load_config("config.ini")
        print(f"✅ 配置加载成功")
        print(f"   - Gemini API: {self.config.llm.gemini_api_key[:10]}...")
        print(f"   - Model: {self.config.llm.model_name}")
        print(f"   - Audio: {self.config.agent.audio_sample_rate}Hz")
        
        # 初始化世界状态
        self.world_state = WorldState()
        self.world_state.initialize_world_map(mock_data=True)
        print("✅ 世界状态初始化完成")
        
        # 初始化机器人工具
        self.robot_tools = MockRobotTools(self.world_state, self.config)
        self.tool_registry = ToolRegistry(self.robot_tools)
        print("✅ 机器人工具初始化完成")
        
        # 初始化语音系统
        self.speech_system = SpeechSystem(self.config.speech)
        print("✅ 语音系统初始化完成")
        
        # 初始化Gemini Agent
        self.gemini_agent = GeminiAgent(
            self.config.llm, 
            self.config.agent, 
            self.tool_registry
        )
        print("✅ Gemini Agent初始化完成")
        
    def command_handler(self, command: RobotCommand):
        """处理Agent命令"""
        self.commands_received.append(command)
        
        print(f"\n🤖 收到Agent命令:")
        print(f"   动作: {command.action}")
        print(f"   参数: {command.parameters}")
        print(f"   响应: {command.response_text}")
        print(f"   置信度: {command.confidence}")
        
        # 如果是语音响应，播放语音
        if command.action == "speak" and self.speech_system:
            try:
                asyncio.create_task(
                    self.speech_system.say(command.parameters.get("text", command.response_text))
                )
            except Exception as e:
                logger.warning(f"语音播放失败: {e}")
        
    async def test_basic_connection(self):
        """测试基本连接"""
        print("\n📡 测试Gemini Live API连接...")
        
        try:
            # 启动麦克风服务器
            await self.gemini_agent.microphone.start_server()
            print("✅ 麦克风服务器启动成功")
            
            # 测试会话创建（不实际启动交互）
            config_dict = self.gemini_agent._create_session_config()
            print("✅ 会话配置创建成功")
            print(f"   - 响应模式: {config_dict.get('response_modalities')}")
            print(f"   - 工具数量: {len(config_dict.get('tools', [{}])[0].get('function_declarations', []))}")
            
            await self.gemini_agent.microphone.stop_server()
            print("✅ 基本连接测试完成")
            
        except Exception as e:
            print(f"❌ 连接测试失败: {e}")
            raise
    
    async def test_tool_definitions(self):
        """测试工具定义"""
        print("\n🔧 测试工具定义...")
        
        tools = self.tool_registry.get_tool_definitions()
        if tools and len(tools) > 0:
            function_declarations = tools[0].get('function_declarations', [])
            print(f"✅ 工具定义加载成功，共 {len(function_declarations)} 个工具:")
            
            for func in function_declarations:
                print(f"   - {func['name']}: {func['description']}")
        else:
            print("❌ 工具定义为空")
            
    async def test_mock_tools(self):
        """测试模拟工具执行"""
        print("\n🛠️ 测试模拟工具执行...")
        
        test_cases = [
            ("scan_inventory", {"announce": True}),
            ("grab_item_by_name", {"item_name": "可口可乐"}),
            ("query_world_map", {}),
            ("calculate_checkout", {})
        ]
        
        for tool_name, params in test_cases:
            try:
                result = await self.tool_registry.execute_tool(tool_name, params)
                if result.get("success"):
                    print(f"✅ {tool_name}: {result.get('message')}")
                else:
                    print(f"⚠️ {tool_name}: {result.get('message')}")
            except Exception as e:
                print(f"❌ {tool_name}: 执行失败 - {e}")
    
    async def run_interactive_test(self, duration=60):
        """运行交互式测试"""
        print(f"\n🎤 开始 {duration} 秒交互式测试...")
        print("请在笔记本上运行音频客户端:")
        print("  python sensors/audio_client_tcp.py --host 192.168.3.10")
        print("然后开始说话测试语音交互和工具调用")
        print("=" * 50)
        
        try:
            # 启动Gemini交互会话
            task = asyncio.create_task(
                self.gemini_agent.start_interactive_session(self.command_handler)
            )
            
            # 等待指定时间或手动停止
            try:
                await asyncio.wait_for(task, timeout=duration)
            except asyncio.TimeoutError:
                print(f"\n⏰ {duration}秒测试时间结束")
            
        except KeyboardInterrupt:
            print("\n🛑 用户手动停止测试")
        finally:
            await self.gemini_agent.stop_session()
            
        # 显示测试结果
        print(f"\n📊 测试结果统计:")
        print(f"   收到命令数: {len(self.commands_received)}")
        if self.commands_received:
            action_counts = {}
            for cmd in self.commands_received:
                action_counts[cmd.action] = action_counts.get(cmd.action, 0) + 1
            
            print("   命令类型统计:")
            for action, count in action_counts.items():
                print(f"     - {action}: {count}次")
    
    async def test_speech_output(self):
        """测试语音输出"""
        print("\n🔊 测试语音输出...")
        
        test_texts = [
            "Gemini Live API集成测试开始",
            "语音合成系统工作正常",
            "工具调用功能已就绪"
        ]
        
        for text in test_texts:
            try:
                result = await self.speech_system.say(text)
                if result.get("success"):
                    print(f"✅ 语音输出: {text}")
                else:
                    print(f"❌ 语音输出失败: {result.get('message')}")
                await asyncio.sleep(1)
            except Exception as e:
                print(f"❌ 语音输出错误: {e}")


async def main():
    """主测试函数"""
    parser = argparse.ArgumentParser(description="Gemini Live API集成测试")
    parser.add_argument("--basic", action="store_true", help="仅运行基本测试")
    parser.add_argument("--interactive", action="store_true", help="运行交互式测试")
    parser.add_argument("--duration", type=int, default=60, help="交互测试持续时间(秒)")
    parser.add_argument("--speech", action="store_true", help="测试语音输出")
    
    args = parser.parse_args()
    
    test = GeminiIntegrationTest()
    
    try:
        await test.setup()
        
        if args.basic or (not args.interactive and not args.speech):
            await test.test_basic_connection()
            await test.test_tool_definitions() 
            await test.test_mock_tools()
            
        if args.speech:
            await test.test_speech_output()
            
        if args.interactive:
            await test.run_interactive_test(args.duration)
            
        print("\n🎉 所有测试完成!")
        
    except Exception as e:
        logger.error(f"测试失败: {e}")
        print(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())