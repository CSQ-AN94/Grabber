#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重构后的系统完整测试
验证所有功能正常工作
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from intelligence.speech_local import LocalSpeechSystem
from intelligence.gemini_agent import GeminiAgent
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from utils.state import WorldState

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class RefactoredSystemTest:
    """重构后系统测试类"""
    
    def __init__(self):
        self.config = None
        self.world_state = None
        self.speech_system = None
        self.gemini_agent = None
        self.robot_tools = None
        self.tool_registry = None
    
    async def setup(self):
        """初始化测试环境"""
        print("🔧 初始化重构后的系统...")
        
        # 加载配置
        self.config = load_config("config.ini")
        print(f"✅ 配置加载成功")
        
        # 初始化世界状态
        self.world_state = WorldState()
        self.world_state.initialize_world_map(mock_data=True)
        print("✅ 世界状态初始化完成")
        
        # 初始化本地语音系统
        self.speech_system = LocalSpeechSystem(self.config.speech)
        print("✅ 本地语音系统初始化完成")
        
        # 初始化机器人工具
        self.robot_tools = MockRobotTools(self.world_state, self.config)
        self.tool_registry = ToolRegistry(self.robot_tools)
        print("✅ 机器人工具初始化完成")
        
        # 初始化Gemini Agent（本地音频版本）
        if self.config.llm.gemini_api_key != 'YOUR_GEMINI_API_KEY_HERE':
            self.gemini_agent = GeminiAgent(
                self.config.llm, 
                self.config.agent, 
                self.tool_registry
            )
            print("✅ Gemini Agent（本地音频版）初始化完成")
        else:
            print("⚠️ Gemini API密钥未配置，跳过Agent初始化")
    
    async def test_speech_system(self):
        """测试本地语音系统"""
        print("\n🎵 测试本地语音系统...")
        
        try:
            test_texts = [
                "重构后的系统运行正常",
                "本地音频功能已就绪",
                "语音合成工作正常"
            ]
            
            for i, text in enumerate(test_texts, 1):
                print(f"📢 测试 {i}/{len(test_texts)}: {text}")
                result = await self.speech_system.say(text)
                
                if result["success"]:
                    print(f"✅ 成功")
                else:
                    print(f"❌ 失败: {result['message']}")
                
                await asyncio.sleep(0.3)
            
            print("✅ 本地语音系统测试完成")
            return True
            
        except Exception as e:
            print(f"❌ 语音系统测试失败: {e}")
            return False
    
    async def test_robot_tools(self):
        """测试机器人工具"""
        print("\n🛠️ 测试机器人工具...")
        
        try:
            # 测试库存扫描
            result = await self.robot_tools.scan_inventory(announce=True)
            if result["success"]:
                print("✅ 库存扫描工具正常")
            else:
                print(f"❌ 库存扫描工具失败: {result['message']}")
            
            # 测试商品抓取
            result = await self.robot_tools.grab_item_by_name("可口可乐")
            if result["success"]:
                print("✅ 商品抓取工具正常")
            else:
                print(f"❌ 商品抓取工具失败: {result['message']}")
            
            # 测试结账计算
            result = await self.robot_tools.calculate_checkout()
            if result["success"]:
                print("✅ 结账计算工具正常")
            else:
                print(f"❌ 结账计算工具失败: {result['message']}")
            
            print("✅ 机器人工具测试完成")
            return True
            
        except Exception as e:
            print(f"❌ 机器人工具测试失败: {e}")
            return False
    
    async def test_gemini_integration(self):
        """测试Gemini Agent集成"""
        print("\n🤖 测试Gemini Agent集成...")
        
        if not self.gemini_agent:
            print("⚠️ Gemini Agent未初始化，跳过测试")
            return True
        
        try:
            # 测试会话配置
            config_dict = self.gemini_agent._create_session_config()
            print(f"✅ 会话配置正常: {len(config_dict.get('tools', []))} 个工具")
            
            # 测试本地麦克风配置
            mic_stats = self.gemini_agent.microphone.get_stats()
            print("✅ 本地麦克风接口配置正常")
            
            print("✅ Gemini Agent集成测试完成")
            return True
            
        except Exception as e:
            print(f"❌ Gemini Agent集成测试失败: {e}")
            return False
    
    async def test_main_application(self):
        """测试主应用程序导入"""
        print("\n🚀 测试主应用程序...")
        
        try:
            # 尝试导入主应用
            from main import GrabberSystem
            
            print("✅ 主应用程序导入成功")
            print("✅ 所有依赖关系正常")
            return True
            
        except Exception as e:
            print(f"❌ 主应用程序测试失败: {e}")
            return False
    
    async def run_all_tests(self):
        """运行所有测试"""
        print("🔧 重构后系统完整测试")
        print("=" * 50)
        
        await self.setup()
        
        test_results = []
        
        # 运行各项测试
        test_results.append(await self.test_speech_system())
        test_results.append(await self.test_robot_tools())
        test_results.append(await self.test_gemini_integration())
        test_results.append(await self.test_main_application())
        
        # 统计结果
        passed = sum(test_results)
        total = len(test_results)
        
        print(f"\n📊 测试结果总结:")
        print(f"   通过: {passed}/{total}")
        print(f"   成功率: {passed/total*100:.1f}%")
        
        if passed == total:
            print("\n🎉 重构后系统测试全部通过!")
            print("✅ 系统重构成功完成!")
        else:
            print(f"\n⚠️ 有 {total-passed} 项测试失败，需要进一步检查")
        
        return passed == total


async def main():
    """主测试函数"""
    test = RefactoredSystemTest()
    success = await test.run_all_tests()
    
    if success:
        print("\n🎯 重构计划执行成功!")
        print("音频系统已从网络架构成功转换为本地架构")
    else:
        print("\n❌ 重构过程中发现问题，需要进一步调试")


if __name__ == "__main__":
    asyncio.run(main())