#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
多轮连续对话系统测试
整合 GeminiAgent + SpeechSystem + LocalMicrophone + RobotTools
"""

import sys
import os
import asyncio
import logging
import threading
import time
from typing import Optional

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.gemini_agent import GeminiAgent, RobotCommand
from intelligence.speech import SpeechSystem, SentenceBuffer
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from sensors.local_microphone import LocalMicrophoneInput
from utils.config import load_config, setup_logging
from utils.state import WorldState

class IntegratedDialogueSystem:
    """
    多轮连续对话系统 - 整合所有组件
    
    架构：
    1. 语音输入 (LocalMicrophone) → GeminiAgent → Gemini Live API
    2. Gemini Live API → RobotTools (工具调用)
    3. Gemini Live API → SentenceBuffer → SpeechSystem (语音输出)
    4. 连续循环，支持多轮对话
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
        
        # 语音输入
        self.microphone = LocalMicrophoneInput(
            sample_rate=16000,
            chunk_size=1024
        )
        
        # Gemini Agent
        self.gemini_agent = GeminiAgent(
            self.config.llm, 
            self.config.agent, 
            self.tool_registry
        )
        
        # 状态管理
        self.is_running = False
        self.stop_event = threading.Event()
        self.dialogue_count = 0
        
        # 初始化世界状态
        self.world_state.initialize_world_map(mock_data=True)
        
        self.logger.info("多轮对话系统初始化完成")
    
    async def start_dialogue_session(self):
        """启动多轮对话会话"""
        if self.is_running:
            self.logger.warning("对话会话已在运行")
            return
        
        self.is_running = True
        self.logger.info("🎤 启动多轮对话会话")
        
        try:
            # 欢迎语音
            await self.speech_system.say("您好！我是智能零售机器人助手，请告诉我您需要什么帮助。")
            
            # 启动Gemini Agent会话
            await self.gemini_agent.start_interactive_session(self._handle_agent_response)
            
        except Exception as e:
            self.logger.error(f"对话会话启动失败: {e}")
            raise
        finally:
            await self.stop_dialogue_session()
    
    def _handle_agent_response(self, command: RobotCommand):
        """
        处理Gemini Agent的响应
        将文本响应发送到语音输出系统
        """
        try:
            self.dialogue_count += 1
            self.logger.info(f"[对话 #{self.dialogue_count}] 收到响应: {command.action}")
            
            # 处理不同类型的响应
            if command.action == "speak":
                # 文本响应 - 直接语音输出
                response_text = command.parameters.get("text", command.response_text)
                self._queue_speech_output(response_text)
                
            elif command.action in ["scan_inventory", "grab_item_by_name", "calculate_checkout"]:
                # 工具调用响应 - 语音播报结果
                result_text = command.response_text
                self._queue_speech_output(result_text)
                
            else:
                # 其他响应类型
                self.logger.info(f"处理响应类型: {command.action}")
                if command.response_text:
                    self._queue_speech_output(command.response_text)
                    
        except Exception as e:
            self.logger.error(f"处理Agent响应时出错: {e}")
    
    def _queue_speech_output(self, text: str):
        """
        将文本加入语音输出队列
        使用SentenceBuffer进行句子重组
        """
        try:
            if text and text.strip():
                self.logger.info(f"📢 准备语音输出: {text[:50]}...")
                
                # 将文本加入句子缓冲区
                self.sentence_buffer.add_text(text)
                
                # 启动语音输出线程（如果尚未启动）
                if not hasattr(self, '_speech_consumer_thread') or not self._speech_consumer_thread.is_alive():
                    self._start_speech_consumer()
                    
        except Exception as e:
            self.logger.error(f"语音输出队列错误: {e}")
    
    def _start_speech_consumer(self):
        """启动语音输出消费者线程"""
        try:
            self._speech_consumer_thread = threading.Thread(
                target=self._speech_consumer_worker,
                daemon=True
            )
            self._speech_consumer_thread.start()
            self.logger.info("语音输出消费者线程已启动")
        except Exception as e:
            self.logger.error(f"启动语音消费者线程失败: {e}")
    
    def _speech_consumer_worker(self):
        """语音输出消费者工作线程"""
        self.logger.info("🗣️ 语音输出消费者开始工作")
        
        while self.is_running:
            try:
                # 非阻塞获取完整句子
                sentence = self.sentence_buffer.get_sentence(block=False)
                
                if sentence:
                    self.logger.info(f"🎵 语音输出: {sentence}")
                    
                    # 异步提交到语音系统
                    try:
                        # 创建新的事件循环
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        # 执行语音合成
                        result = loop.run_until_complete(self.speech_system.say(sentence))
                        
                        if result.get("success"):
                            self.logger.info(f"✅ 语音播放成功: {sentence[:30]}...")
                        else:
                            self.logger.warning(f"❌ 语音播放失败: {result.get('message')}")
                        
                        loop.close()
                    except Exception as e:
                        self.logger.error(f"语音合成错误: {e}")
                else:
                    # 短暂等待
                    time.sleep(0.1)
                    
            except Exception as e:
                self.logger.error(f"语音消费者工作线程错误: {e}")
                time.sleep(0.5)
        
        self.logger.info("🗣️ 语音输出消费者工作线程结束")
    
    async def stop_dialogue_session(self):
        """停止对话会话"""
        if not self.is_running:
            return
        
        self.logger.info("🛑 停止对话会话")
        self.is_running = False
        self.stop_event.set()
        
        try:
            # 停止Gemini Agent
            await self.gemini_agent.stop_session()
            
            # 停止语音系统
            self.sentence_buffer.stop()
            self.speech_system.stop_speech_system()
            
            # 停止麦克风
            await self.microphone.stop_recording()
            
            self.logger.info("✅ 对话会话已停止")
            
        except Exception as e:
            self.logger.error(f"停止对话会话时出错: {e}")
    
    def get_session_stats(self) -> dict:
        """获取会话统计信息"""
        return {
            "dialogue_count": self.dialogue_count,
            "is_running": self.is_running,
            "microphone_stats": self.microphone.get_stats() if self.microphone else None,
            "speech_queue_size": self.sentence_buffer.sentence_queue.qsize(),
            "world_map_items": len(self.world_state.get_world_map().get("items", [])),
        }


async def main():
    """主函数 - 多轮对话系统测试"""
    print("🤖 多轮连续对话系统测试")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 检查麦克风设备
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        print("\n📱 可用音频设备:")
        for i, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                print(f"  输入设备 {i}: {device['name']} ({device['max_input_channels']} channels)")
    except Exception as e:
        print(f"⚠️  音频设备检查失败: {e}")
    
    print("\n🎯 启动多轮对话系统...")
    
    # 创建对话系统
    dialogue_system = IntegratedDialogueSystem()
    
    try:
        # 启动对话会话
        await dialogue_system.start_dialogue_session()
        
    except KeyboardInterrupt:
        print("\n🛑 用户中断对话...")
    except Exception as e:
        print(f"❌ 系统错误: {e}")
        logging.error(f"系统错误: {e}", exc_info=True)
    finally:
        # 显示统计信息
        stats = dialogue_system.get_session_stats()
        print(f"\n📊 会话统计:")
        print(f"  对话轮数: {stats['dialogue_count']}")
        print(f"  语音队列大小: {stats['speech_queue_size']}")
        print(f"  世界地图商品数: {stats['world_map_items']}")
        
        # 停止会话
        await dialogue_system.stop_dialogue_session()
        
        print("\n👋 感谢使用多轮对话系统！")


if __name__ == "__main__":
    asyncio.run(main())