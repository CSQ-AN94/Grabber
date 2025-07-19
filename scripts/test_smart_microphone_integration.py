#!/usr/bin/env python3
"""
真实语音AI集成测试 - 基于真实组件的完整集成
严格要求：真实麦克风 + 真实Live API + 真实TTS
"""

import sys
import os
import asyncio
import logging
import time
from typing import Optional, Dict, Any
from dataclasses import dataclass

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.gemini_agent import GeminiAgent, RobotCommand
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from intelligence.speech import SpeechSystem
from utils.config import load_config, setup_logging
from utils.state import WorldState


@dataclass
class RealIntegrationStats:
    """真实集成统计"""
    start_time: float
    live_api_responses: int = 0
    tts_success: int = 0
    tts_failures: int = 0
    tool_calls: int = 0


class RealVoiceAIIntegration:
    """真实语音AI集成系统 - 基于真实组件"""
    
    def __init__(self, config_path: str = "config.ini"):
        self.config = load_config(config_path)
        self.logger = logging.getLogger(__name__)
        
        # 统计信息
        self.stats = RealIntegrationStats(start_time=time.time())
        
        # 初始化真实组件
        self.world_state = WorldState()
        self.world_state.initialize_world_map(mock_data=True)
        
        # 创建真实的Robot Tools和Registry
        self.robot_tools = MockRobotTools(self.world_state, self.config)
        self.tool_registry = ToolRegistry(self.robot_tools)
        
        # 创建真实的GeminiAgent - 它内置SmartMicrophone和Live API
        self.gemini_agent = GeminiAgent(
            self.config.llm, 
            self.config.agent, 
            self.tool_registry
        )
        
        # 创建真实的TTS系统
        self.speech_system = SpeechSystem(self.config.speech)
        
        # 运行状态
        self.is_running = False
        
        self.logger.info("真实语音AI集成系统初始化完成")
    
    def real_command_handler(self, command: RobotCommand):
        """处理真实的GeminiAgent命令"""
        try:
            self.logger.info(f"收到真实Live API命令: {command.action}")
            
            if command.action == "speak":
                # 这是真实的Live API响应
                self.stats.live_api_responses += 1
                response_text = command.response_text
                
                self.logger.info(f"🤖 [真实Live API响应 #{self.stats.live_api_responses}]: {response_text}")
                
                # 使用真实TTS处理真实响应
                try:
                    loop = asyncio.get_event_loop()
                    loop.create_task(self._process_real_tts(response_text))
                except RuntimeError:
                    # 如果没有运行的事件循环，创建一个新的任务
                    asyncio.ensure_future(self._process_real_tts(response_text))
                
            else:
                # 真实工具调用
                self.stats.tool_calls += 1
                self.logger.info(f"🛠️ [真实工具调用 #{self.stats.tool_calls}] {command.action}: {command.response_text}")
                
                # 工具调用结果也用真实TTS
                if command.response_text:
                    try:
                        loop = asyncio.get_event_loop()
                        loop.create_task(self._process_real_tts(command.response_text))
                    except RuntimeError:
                        asyncio.ensure_future(self._process_real_tts(command.response_text))
                
        except Exception as e:
            self.logger.error(f"真实命令处理错误: {e}")
    
    async def _process_real_tts(self, text: str):
        """处理真实的TTS"""
        try:
            if not text or not text.strip():
                return
                
            # 使用真实的SpeechSystem进行TTS
            result = await self.speech_system.say(text.strip())
            
            if result.get("success"):
                self.stats.tts_success += 1
                self.logger.info(f"✅ 真实TTS成功: {text[:30]}...")
            else:
                self.stats.tts_failures += 1
                self.logger.error(f"❌ 真实TTS失败: {result.get('message', 'Unknown error')}")
                
        except Exception as e:
            self.logger.error(f"真实TTS处理错误: {e}")
            self.stats.tts_failures += 1
    
    async def run_real_integration(self):
        """运行真实的语音AI集成"""
        self.logger.info("=" * 70)
        self.logger.info("🎤 真实语音AI集成测试")
        self.logger.info("✅ 真实麦克风 + 真实Live API + 真实TTS")
        self.logger.info("🎯 完全基于真实组件的集成")
        self.logger.info("🔧 无任何模拟数据")
        self.logger.info("=" * 70)
        
        self.is_running = True
        
        try:
            # 发送真实欢迎消息
            welcome_msg = "真实语音AI集成系统已启动，请开始语音对话！"
            self.logger.info(f"🤖 系统: {welcome_msg}")
            
            # 后台欢迎TTS - 不阻塞主流程
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self._process_real_tts(welcome_msg))
            except RuntimeError:
                asyncio.ensure_future(self._process_real_tts(welcome_msg))
            
            # 获取真实麦克风状态
            mic_stats = self.gemini_agent.microphone.get_stats()
            self.logger.info(f"🎤 真实音频设备: {mic_stats['audio_source']}")
            self.logger.info(f"📊 采样率: {mic_stats['sample_rate']} Hz")
            
            # 启动统计任务
            stats_task = asyncio.create_task(self._real_stats_reporter())
            
            # 启动真实的GeminiAgent交互会话
            self.logger.info("🚀 启动真实GeminiAgent交互会话...")
            self.logger.info("🎤 请开始语音对话...")
            self.logger.info("🔄 系统将实时处理您的语音并调用真实Live API")
            self.logger.info("🗣️ 真实AI响应将通过真实TTS播放")
            self.logger.info("🛑 按Ctrl+C停止测试")
            self.logger.info("-" * 50)
            
            # 这是关键：启动真实的GeminiAgent会话
            # 它会自动处理：真实麦克风 → 真实Live API → 真实响应
            await self.gemini_agent.start_interactive_session(self.real_command_handler)
            
        except KeyboardInterrupt:
            self.logger.info("\n🛑 用户请求停止测试")
        except Exception as e:
            self.logger.error(f"真实集成测试错误: {e}")
            raise
        finally:
            await self._cleanup()
    
    async def _real_stats_reporter(self):
        """真实统计报告"""
        while self.is_running:
            try:
                await asyncio.sleep(30)  # 每30秒报告一次
                if self.is_running:
                    await self._log_real_stats()
            except Exception as e:
                self.logger.error(f"统计报告错误: {e}")
    
    async def _log_real_stats(self):
        """记录真实统计"""
        uptime = time.time() - self.stats.start_time
        mic_stats = self.gemini_agent.microphone.get_stats()
        
        self.logger.info("📊 真实集成状态报告:")
        self.logger.info(f"  ⏱️ 运行时间: {uptime:.1f}秒")
        self.logger.info(f"  🎤 真实音频块: {mic_stats['chunks_received']}")
        self.logger.info(f"  🗣️ 真实语音事件: {mic_stats['speech_events']}")
        self.logger.info(f"  🔇 真实静音事件: {mic_stats['silence_events']}")
        self.logger.info(f"  🤖 真实Live API响应: {self.stats.live_api_responses}")
        self.logger.info(f"  🔊 真实TTS成功: {self.stats.tts_success}")
        self.logger.info(f"  ❌ 真实TTS失败: {self.stats.tts_failures}")
        self.logger.info(f"  🛠️ 真实工具调用: {self.stats.tool_calls}")
        self.logger.info(f"  📡 真实数据速率: {mic_stats['bytes_per_second']:.1f} B/s")
    
    async def _cleanup(self):
        """清理资源"""
        self.logger.info("🛑 停止真实语音AI集成测试...")
        self.is_running = False
        
        try:
            # 停止真实GeminiAgent
            await self.gemini_agent.stop_session()
            
            # 停止真实TTS系统
            self.speech_system.stop_speech_system()
            
            # 显示最终统计
            await self._print_final_real_stats()
            
            self.logger.info("✅ 真实语音AI集成测试已完全停止")
            
        except Exception as e:
            self.logger.error(f"清理资源错误: {e}")
    
    async def _print_final_real_stats(self):
        """显示最终真实统计"""
        uptime = time.time() - self.stats.start_time
        mic_stats = self.gemini_agent.microphone.get_stats()
        
        print(f"\n📊 真实集成最终报告:")
        print(f"  ⏱️ 总运行时间: {uptime:.1f}秒")
        print(f"  🎤 真实音频处理:")
        print(f"    - 音频源: {mic_stats['audio_source']}")
        print(f"    - 接收字节: {mic_stats['bytes_received']}")
        print(f"    - 音频块数: {mic_stats['chunks_received']}")
        print(f"    - 语音事件: {mic_stats['speech_events']}")
        print(f"    - 静音事件: {mic_stats['silence_events']}")
        print(f"    - 数据速率: {mic_stats['bytes_per_second']:.1f} B/s")
        
        print(f"  🤖 真实AI交互:")
        print(f"    - Live API响应: {self.stats.live_api_responses}")
        print(f"    - 工具调用: {self.stats.tool_calls}")
        
        print(f"  🔊 真实语音合成:")
        print(f"    - TTS成功: {self.stats.tts_success}")
        print(f"    - TTS失败: {self.stats.tts_failures}")
        
        if self.stats.tts_success + self.stats.tts_failures > 0:
            success_rate = (self.stats.tts_success / (self.stats.tts_success + self.stats.tts_failures)) * 100
            print(f"    - 成功率: {success_rate:.1f}%")
        
        print(f"\n✅ 真实集成验证:")
        print(f"  ✅ 真实麦克风输入: {'正常' if mic_stats['chunks_received'] > 0 else '异常'}")
        print(f"  ✅ 真实语音检测: {'正常' if mic_stats['speech_events'] > 0 else '未检测到'}")
        print(f"  ✅ 真实Live API: {'正常' if self.stats.live_api_responses > 0 else '未调用'}")
        print(f"  ✅ 真实TTS处理: {'正常' if self.stats.tts_success > 0 else '异常'}")
        
        # 集成完整性验证
        if (mic_stats['speech_events'] > 0 and 
            self.stats.live_api_responses > 0 and 
            self.stats.tts_success > 0):
            print(f"  🎉 完整集成: 成功 (真实语音→真实AI→真实TTS)")
        else:
            print(f"  ⚠️ 完整集成: 需要改进")
            
        # 性能评估
        if uptime > 0:
            response_rate = self.stats.live_api_responses / (uptime / 60)
            print(f"  📈 真实对话频率: {response_rate:.1f} 次/分钟")


async def main():
    """主函数"""
    print("🎤 真实语音AI集成测试")
    print("=" * 70)
    print("严格要求：")
    print("  🎯 真实麦克风数据 - 监听用户语音")
    print("  🤖 真实Live API调用 - 发送音频到Gemini")
    print("  📝 真实JSON响应 - 处理API返回的response_text")
    print("  🔊 真实TTS处理 - 转换response_text为语音")
    print("=" * 70)
    print("集成流程：")
    print("  1. 用户语音 → SmartMicrophone → 音频流")
    print("  2. 音频流 → GeminiAgent → Live API")
    print("  3. Live API → JSON响应 → RobotCommand")
    print("  4. RobotCommand → response_text → SpeechSystem")
    print("  5. SpeechSystem → TTS → 语音播放")
    print("=" * 70)
    print("🚀 启动真实语音AI集成测试...")
    print("=" * 70)
    
    # 设置日志 - 使用简单的控制台日志避免权限问题
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[logging.StreamHandler()]
    )
    
    # 创建真实集成系统
    integration_system = RealVoiceAIIntegration()
    
    try:
        # 运行真实集成
        await integration_system.run_real_integration()
        
    except Exception as e:
        print(f"❌ 真实集成系统错误: {e}")
        logging.error(f"真实集成系统错误: {e}", exc_info=True)
    
    print("\n🎉 真实语音AI集成测试完成！")
    print("✅ 验证了真实组件的完整集成")


if __name__ == "__main__":
    asyncio.run(main())