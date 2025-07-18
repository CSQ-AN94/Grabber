#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成语音对话系统 - 真实GeminiAgent + 语音输入输出
结合成功的complete_dialogue_system.py架构与真实的GeminiAgent和LocalMicrophoneInput
实现完整的语音输入 → AI处理 → 语音输出对话流程
"""

import sys
import os
import asyncio
import logging
import threading
import time
from typing import Optional, Dict, Any

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.speech import SpeechSystem, SentenceBuffer
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from intelligence.gemini_agent import GeminiAgent, RobotCommand
from sensors.local_microphone import LocalMicrophoneInput
from utils.config import load_config, setup_logging
from utils.state import WorldState


class IntegratedVoiceDialogueSystem:
    """
    集成语音对话系统
    结合成功的complete_dialogue_system.py架构与真实的GeminiAgent
    实现完整的语音输入 → AI处理 → 语音输出对话流程
    """
    
    def __init__(self, config_path: str = "config.ini"):
        self.config = load_config(config_path)
        self.logger = logging.getLogger(__name__)
        
        # 核心组件
        self.world_state = WorldState()
        self.speech_system = SpeechSystem(self.config.speech)
        self.sentence_buffer = SentenceBuffer()
        self.robot_tools = MockRobotTools(self.world_state, self.config)
        self.tool_registry = ToolRegistry(self.robot_tools)
        
        # 语音输入/输出组件
        self.microphone = LocalMicrophoneInput(
            sample_rate=self.config.agent.audio_sample_rate,
            chunk_size=self.config.agent.audio_chunk_size
        )
        
        # 集成GeminiAgent
        self.gemini_agent = GeminiAgent(
            self.config.llm, 
            self.config.agent,
            self.tool_registry
        )
        
        # 语音输出消费者（基于成功的complete_dialogue_system.py模式）
        self.speech_consumer = VoiceOutputConsumer(self.sentence_buffer, self.speech_system)
        
        # 状态管理
        self.stop_event = threading.Event()
        self.is_running = False
        
        # 统计信息
        self.dialogue_count = 0
        self.start_time = None
        
        # 初始化世界状态
        self.world_state.initialize_world_map(mock_data=True)
        
        self.logger.info("集成语音对话系统初始化完成")
    
    async def start_voice_dialogue(self):
        """
        启动完整的语音对话系统
        语音输入 → GeminiAgent处理 → 语音输出
        """
        if self.is_running:
            self.logger.warning("对话系统已在运行")
            return
        
        self.is_running = True
        self.start_time = time.time()
        
        self.logger.info("=================================================")
        self.logger.info("启动集成语音对话系统")
        self.logger.info("=================================================")
        
        try:
            # 启动语音输出消费者线程
            self.logger.info("启动语音输出消费者...")
            consumer_thread = threading.Thread(
                target=self.speech_consumer.start_consuming,
                args=(self.stop_event,),
                name="VoiceOutputConsumerThread"
            )
            consumer_thread.daemon = True
            consumer_thread.start()
            
            # 启动GeminiAgent语音对话会话
            self.logger.info("启动GeminiAgent语音对话会话...")
            self.logger.info("🎤 请对着麦克风说话，开始对话...")
            self.logger.info("   (支持的命令: 扫描货架、抓取商品、推荐商品、结账等)")
            self.logger.info("   (按 Ctrl+C 结束对话)")
            
            # 开始语音对话会话
            await self.gemini_agent.start_interactive_session(self._handle_agent_response)
            
        except KeyboardInterrupt:
            self.logger.info("\n🛑 用户请求停止对话...")
        except Exception as e:
            self.logger.error(f"对话系统错误: {e}")
            raise
        finally:
            await self.stop_voice_dialogue()
    
    def _handle_agent_response(self, command: RobotCommand):
        """
        处理GeminiAgent的响应
        将响应文本加入语音输出队列
        """
        try:
            self.dialogue_count += 1
            self.logger.info(f"[对话 #{self.dialogue_count}] 收到Agent响应: {command.action}")
            
            # 将响应文本加入语音输出队列
            if command.response_text:
                self._queue_speech_output(command.response_text)
            
            # 记录工具调用
            if command.action != "speak":
                self.logger.info(f"🛠️ 工具调用: {command.action} - {command.parameters}")
        
        except Exception as e:
            self.logger.error(f"处理Agent响应时出错: {e}")
    
    def _queue_speech_output(self, text: str):
        """
        将文本加入语音输出队列
        使用与complete_dialogue_system.py相同的成功模式
        """
        try:
            if text and text.strip():
                self.logger.info(f"📢 语音输出队列: {text[:50]}...")
                
                # 确保文本有正确的句号结尾以便正确分割
                text_with_punctuation = text.strip()
                if not text_with_punctuation.endswith(('。', '！', '？', '……')):
                    text_with_punctuation += '。'
                
                # 加入sentence buffer进行处理
                self.sentence_buffer.add_text(text_with_punctuation)
                
        except Exception as e:
            self.logger.error(f"语音输出队列错误: {e}")
    
    async def stop_voice_dialogue(self):
        """停止语音对话系统"""
        if not self.is_running:
            return
        
        self.logger.info("🛑 停止集成语音对话系统...")
        self.is_running = False
        self.stop_event.set()
        
        try:
            # 停止GeminiAgent会话
            await self.gemini_agent.stop_session()
            
            # 刷新sentence buffer确保所有句子都被处理
            self.sentence_buffer.flush()
            
            # 等待语音输出完成
            await asyncio.sleep(3)
            
            # 停止语音组件
            self.sentence_buffer.stop()
            self.speech_system.stop_speech_system()
            
            self.logger.info("✅ 集成语音对话系统已停止")
            
        except Exception as e:
            self.logger.error(f"停止对话系统时出错: {e}")
    
    def get_dialogue_stats(self) -> dict:
        """获取对话统计信息"""
        uptime = time.time() - self.start_time if self.start_time else 0
        
        return {
            "dialogue_count": self.dialogue_count,
            "is_running": self.is_running,
            "uptime_seconds": uptime,
            "speech_queue_size": self.sentence_buffer.sentence_queue.qsize(),
            "world_map_items": len(self.world_state.get_world_map().get("items", [])),
            "microphone_stats": self.microphone.get_stats() if hasattr(self.microphone, 'get_stats') else {},
            "speech_consumer_stats": {
                "sentences_processed": self.speech_consumer.sentence_count,
                "is_running": self.speech_consumer.is_running
            }
        }


class VoiceOutputConsumer:
    """
    语音输出消费者
    复用complete_dialogue_system.py中成功的DialogueSpeechConsumer逻辑
    """
    
    def __init__(self, sentence_buffer: SentenceBuffer, speech_system: SpeechSystem):
        self.sentence_buffer = sentence_buffer
        self.speech_system = speech_system
        self.logger = logging.getLogger(__name__)
        self.sentence_count = 0
        self.is_running = False
    
    def start_consuming(self, stop_event: threading.Event):
        """
        启动语音消费者线程
        完全复用complete_dialogue_system.py的成功逻辑
        """
        self.is_running = True
        self.logger.info("🗣️ [语音消费者] 语音播报消费者已启动...")
        
        while not stop_event.is_set() and self.is_running:
            # 非阻塞地从队列中获取一个完整的句子
            sentence = self.sentence_buffer.get_sentence(block=False)
            
            if sentence:
                self.sentence_count += 1
                self.logger.info(f"🗣️ [语音消费者] <- 获取到完整句子 #{self.sentence_count}: '{sentence}'")
                self.logger.info("   ...正在提交给语音合成系统...")
                
                # 使用与complete_dialogue_system.py完全相同的异步调用方式
                try:
                    # 创建新的事件循环来处理异步调用
                    import threading as thread_module
                    
                    def run_speech_task(text_to_speak):
                        """在新线程中运行语音合成任务"""
                        try:
                            if not text_to_speak or not text_to_speak.strip():
                                self.logger.info(f"   ...空文本，跳过播放。")
                                return
                                
                            # 为这个线程创建新的事件循环
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            
                            # 异步调用 speech_system.say
                            result = loop.run_until_complete(self.speech_system.say(text_to_speak))
                            
                            # 打印结果
                            if result.get("success"):
                                self.logger.info(f"   ...'{text_to_speak[:20]}...' 播放完成。")
                            else:
                                self.logger.info(f"   ...'{text_to_speak[:20]}...' 播放失败: {result.get('message', '未知错误')}")
                            
                            loop.close()
                        except Exception as e:
                            self.logger.error(f"   ...'{text_to_speak[:20] if text_to_speak else 'unknown'}...' 播放错误: {e}")
                    
                    # 在独立线程中启动语音任务（fire-and-forget）
                    speech_thread = thread_module.Thread(target=run_speech_task, args=(sentence,))
                    speech_thread.daemon = True
                    speech_thread.start()
                    
                    self.logger.info(f"   ...'{sentence[:20]}...' 已提交到播放队列。")
                    
                except Exception as e:
                    self.logger.error(f"   ...语音播报时出错: {e}")
            else:
                # 短暂等待再检查
                time.sleep(0.1)
        
        self.logger.info(f"🗣️ [语音消费者] 总共处理了 {self.sentence_count} 个句子")
        self.is_running = False


async def main():
    """主函数 - 集成语音对话系统"""
    print("🎤 集成语音对话系统")
    print("=" * 60)
    print("真实语音输入 → GeminiAgent处理 → 语音输出")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 创建集成对话系统
    dialogue_system = IntegratedVoiceDialogueSystem()
    
    try:
        # 启动语音对话
        await dialogue_system.start_voice_dialogue()
        
    except Exception as e:
        print(f"❌ 系统错误: {e}")
        logging.error(f"系统错误: {e}", exc_info=True)
    finally:
        # 显示统计信息
        stats = dialogue_system.get_dialogue_stats()
        print(f"\n📊 对话统计:")
        print(f"  对话轮数: {stats['dialogue_count']}")
        print(f"  运行时间: {stats['uptime_seconds']:.1f}秒")
        print(f"  语音队列大小: {stats['speech_queue_size']}")
        print(f"  处理句子数: {stats['speech_consumer_stats']['sentences_processed']}")
        print(f"  世界地图商品数: {stats['world_map_items']}")
        
        # 停止系统
        await dialogue_system.stop_voice_dialogue()
        
        print("\n🎉 集成语音对话系统测试完成！")


if __name__ == "__main__":
    asyncio.run(main())