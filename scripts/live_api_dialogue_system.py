#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Live API多轮对话系统 - 基于Google Get_started_LiveAPI.ipynb最佳实践
实现真正的异步双向实时语音对话系统
结合成功的语音输出架构与Live API的优势
"""

import sys
import os
import asyncio
import logging
import threading
import time
import json
import contextlib
import wave
from typing import Optional, Dict, Any, AsyncGenerator
from dataclasses import dataclass

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google import genai
from google.genai import types

from intelligence.speech import SpeechSystem, SentenceBuffer
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from intelligence.gemini_agent import RobotCommand
from utils.config import load_config, setup_logging
from utils.state import WorldState


@contextlib.contextmanager
def wave_file(filename, channels=1, rate=24000, sample_width=2):
    """创建WAV文件上下文管理器"""
    with wave.open(filename, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(rate)
        yield wf


async def async_enumerate(aiterable):
    """异步枚举器"""
    n = 0
    async for item in aiterable:
        yield n, item
        n += 1


class LiveAPIDialogueSystem:
    """
    Live API多轮对话系统
    基于Get_started_LiveAPI.ipynb的最佳实践
    集成语音输出和工具调用功能
    """
    
    def __init__(self, config_path: str = "config.ini"):
        self.config = load_config(config_path)
        self.logger = logging.getLogger(__name__)
        
        # Live API客户端
        self.client = genai.Client(api_key=self.config.llm.gemini_api_key)
        self.model = "gemini-2.0-flash-live-001"
        self.session = None
        
        # 核心组件
        self.world_state = WorldState()
        self.speech_system = SpeechSystem(self.config.speech)
        self.sentence_buffer = SentenceBuffer()
        self.robot_tools = MockRobotTools(self.world_state, self.config)
        self.tool_registry = ToolRegistry(self.robot_tools)
        
        # 语音输出消费者
        self.speech_consumer = VoiceOutputConsumer(self.sentence_buffer, self.speech_system)
        
        # 状态管理
        self.stop_event = threading.Event()
        self.is_running = False
        self.audio_index = 0
        
        # 统计信息
        self.dialogue_count = 0
        self.start_time = None
        
        # 初始化世界状态
        self.world_state.initialize_world_map(mock_data=True)
        
        self.logger.info("Live API对话系统初始化完成")
    
    def _create_live_config(self) -> types.LiveConnectConfig:
        """创建Live API连接配置"""
        config_dict = {
            "response_modalities": ["TEXT"],  # 先只使用文本输出
            "system_instruction": "你是一个智能零售机器人助手。请用中文友好地回复用户。"
        }
        
        # 添加工具定义
        if self.tool_registry:
            try:
                tools = self.tool_registry.get_tool_definitions()
                if tools:
                    config_dict["tools"] = tools
            except Exception as e:
                self.logger.warning(f"添加工具定义失败: {e}")
        
        return types.LiveConnectConfig(**config_dict)
    
    async def start_dialogue(self):
        """启动Live API对话系统"""
        if self.is_running:
            self.logger.warning("对话系统已在运行")
            return
        
        self.is_running = True
        self.start_time = time.time()
        
        self.logger.info("=" * 60)
        self.logger.info("启动Live API多轮对话系统")
        self.logger.info("=" * 60)
        
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
            
            # 创建Live API配置
            config = self._create_live_config()
            
            # 开始Live API会话
            self.logger.info("连接到Gemini Live API...")
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                self.session = session
                self.logger.info("✅ Live API连接已建立")
                self.logger.info("🤖 开始智能对话 - 您可以发送文本消息")
                self.logger.info("   (输入 'q' 退出对话)")
                
                # 运行并发任务：发送用户输入和接收模型响应
                try:
                    # 创建并发任务
                    send_task = asyncio.create_task(self._send_messages())
                    recv_task = asyncio.create_task(self._receive_responses())
                    
                    # 等待发送任务完成（用户输入'q'）
                    await send_task
                    
                    # 发送任务完成后，取消接收任务
                    recv_task.cancel()
                    
                    # 等待接收任务完成取消
                    try:
                        await recv_task
                    except asyncio.CancelledError:
                        pass
                    
                except asyncio.CancelledError:
                    # 正常的任务取消
                    pass
                
        except KeyboardInterrupt:
            self.logger.info("\n🛑 用户请求停止对话...")
        except Exception as e:
            self.logger.error(f"Live API对话系统错误: {e}")
            raise
        finally:
            await self.stop_dialogue()
    
    async def _send_messages(self):
        """发送用户消息的异步任务"""
        self.logger.info("📝 等待用户输入...")
        
        while self.is_running:
            try:
                # 异步获取用户输入
                message = await asyncio.to_thread(input, "💬 用户 > ")
                
                if message.lower().strip() == 'q':
                    self.logger.info("🔚 用户请求退出对话")
                    break
                
                if message.strip():
                    self.dialogue_count += 1
                    self.logger.info(f"[对话 #{self.dialogue_count}] 发送用户消息: {message}")
                    
                    # 发送到Live API
                    await self.session.send_client_content(
                        turns={"role": "user", "parts": [{"text": message}]}, 
                        turn_complete=True
                    )
            
            except Exception as e:
                self.logger.error(f"发送消息错误: {e}")
                break
    
    async def _receive_responses(self):
        """接收模型响应的异步任务"""
        try:
            while self.is_running:
                # 接收Live API响应
                turn = self.session.receive()
                await self._process_turn(turn)
                
        except asyncio.CancelledError:
            self.logger.debug("接收任务被取消")
        except Exception as e:
            self.logger.error(f"接收响应错误: {e}")
    
    async def _process_turn(self, turn):
        """处理一个完整的模型回合"""
        text_parts = []
        audio_file = None
        has_audio = False
        
        # 创建音频文件（如果需要）
        audio_file = f"intelligence/live_audio_{self.audio_index}.wav"
        self.audio_index += 1
        
        with wave_file(audio_file) as wav:
            async for response in turn:
                await self._handle_response(response, text_parts, wav)
                
                # 检查是否有音频数据
                if hasattr(response, 'data') and response.data:
                    has_audio = True
        
        # 处理完整的响应文本
        if text_parts:
            full_text = ''.join(text_parts)
            if full_text.strip():
                self.logger.info(f"🤖 助手文本响应: {full_text}")
                self._queue_speech_output(full_text)
        
        # 清理空音频文件
        if not has_audio and os.path.exists(audio_file):
            os.remove(audio_file)
        elif has_audio:
            self.logger.info(f"🎵 收到Live API音频: {audio_file}")
            # 这里可以添加音频播放逻辑
    
    async def _handle_response(self, response, text_parts: list, wav=None):
        """处理单个响应"""
        try:
            # 处理文本响应
            if hasattr(response, 'text') and response.text:
                text_parts.append(response.text)
            
            # 处理音频数据
            if hasattr(response, 'data') and response.data and wav:
                wav.writeframes(response.data)
            
            # 处理服务器内容（工具调用等）
            if hasattr(response, 'server_content') and response.server_content:
                await self._handle_server_content(response.server_content)
            
        except Exception as e:
            self.logger.error(f"处理响应错误: {e}")
    
    async def _handle_server_content(self, server_content):
        """处理服务器内容，包括工具调用"""
        try:
            if hasattr(server_content, 'model_turn') and server_content.model_turn:
                if hasattr(server_content.model_turn, 'parts'):
                    for part in server_content.model_turn.parts:
                        if hasattr(part, 'function_call'):
                            await self._handle_function_call(part.function_call)
        except Exception as e:
            self.logger.error(f"处理服务器内容错误: {e}")
    
    async def _handle_function_call(self, function_call):
        """处理函数调用"""
        try:
            function_name = function_call.name
            parameters = dict(function_call.args) if hasattr(function_call, 'args') else {}
            
            self.logger.info(f"🛠️ 执行工具调用: {function_name} with {parameters}")
            
            # 执行工具函数
            if self.tool_registry:
                result = await self.tool_registry.execute_tool(function_name, parameters)
                
                # 发送结果回Live API
                await self.session.send_client_content(
                    turns=[{
                        "role": "function",
                        "parts": [{
                            "function_response": {
                                "name": function_name,
                                "response": result
                            }
                        }]
                    }],
                    turn_complete=True
                )
                
                # 处理工具执行结果的语音输出
                if result.get("message"):
                    self.logger.info(f"🔧 工具执行结果: {result['message']}")
                    self._queue_speech_output(result["message"])
            
        except Exception as e:
            self.logger.error(f"处理函数调用错误: {e}")
    
    def _queue_speech_output(self, text: str):
        """将文本加入语音输出队列"""
        try:
            if text and text.strip():
                self.logger.info(f"📢 语音输出队列: {text[:50]}...")
                
                # 确保文本有正确的句号结尾
                text_with_punctuation = text.strip()
                if not text_with_punctuation.endswith(('。', '！', '？', '……')):
                    text_with_punctuation += '。'
                
                # 加入sentence buffer
                self.sentence_buffer.add_text(text_with_punctuation)
                
        except Exception as e:
            self.logger.error(f"语音输出队列错误: {e}")
    
    async def stop_dialogue(self):
        """停止对话系统"""
        if not self.is_running:
            return
        
        self.logger.info("🛑 停止Live API对话系统...")
        self.is_running = False
        self.stop_event.set()
        
        try:
            # 刷新sentence buffer
            self.sentence_buffer.flush()
            
            # 等待语音输出完成
            await asyncio.sleep(2)
            
            # 停止语音组件
            self.sentence_buffer.stop()
            self.speech_system.stop_speech_system()
            
            self.logger.info("✅ Live API对话系统已停止")
            
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
            "speech_consumer_stats": {
                "sentences_processed": self.speech_consumer.sentence_count,
                "is_running": self.speech_consumer.is_running
            }
        }


class VoiceOutputConsumer:
    """
    语音输出消费者
    复用完全验证的架构
    """
    
    def __init__(self, sentence_buffer: SentenceBuffer, speech_system: SpeechSystem):
        self.sentence_buffer = sentence_buffer
        self.speech_system = speech_system
        self.logger = logging.getLogger(__name__)
        self.sentence_count = 0
        self.is_running = False
    
    def start_consuming(self, stop_event: threading.Event):
        """启动语音消费者线程"""
        self.is_running = True
        self.logger.info("🗣️ [语音消费者] 语音播报消费者已启动...")
        
        while not stop_event.is_set() and self.is_running:
            sentence = self.sentence_buffer.get_sentence(block=False)
            
            if sentence:
                self.sentence_count += 1
                self.logger.info(f"🗣️ [语音消费者] <- 获取到完整句子 #{self.sentence_count}: '{sentence}'")
                self.logger.info("   ...正在提交给语音合成系统...")
                
                try:
                    import threading as thread_module
                    
                    def run_speech_task(text_to_speak):
                        """在新线程中运行语音合成任务"""
                        try:
                            if not text_to_speak or not text_to_speak.strip():
                                self.logger.info(f"   ...空文本，跳过播放。")
                                return
                                
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            
                            result = loop.run_until_complete(self.speech_system.say(text_to_speak))
                            
                            if result.get("success"):
                                self.logger.info(f"   ...'{text_to_speak[:20]}...' 播放完成。")
                            else:
                                self.logger.info(f"   ...'{text_to_speak[:20]}...' 播放失败: {result.get('message', '未知错误')}")
                            
                            loop.close()
                        except Exception as e:
                            self.logger.error(f"   ...'{text_to_speak[:20] if text_to_speak else 'unknown'}...' 播放错误: {e}")
                    
                    speech_thread = thread_module.Thread(target=run_speech_task, args=(sentence,))
                    speech_thread.daemon = True
                    speech_thread.start()
                    
                    self.logger.info(f"   ...'{sentence[:20]}...' 已提交到播放队列。")
                    
                except Exception as e:
                    self.logger.error(f"   ...语音播报时出错: {e}")
            else:
                time.sleep(0.1)
        
        self.logger.info(f"🗣️ [语音消费者] 总共处理了 {self.sentence_count} 个句子")
        self.is_running = False


async def main():
    """主函数 - Live API对话系统"""
    print("🤖 Live API多轮对话系统")
    print("=" * 60)
    print("基于Google Get_started_LiveAPI.ipynb最佳实践")
    print("文本输入 → Live API处理 → 文本+音频输出")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 创建Live API对话系统
    dialogue_system = LiveAPIDialogueSystem()
    
    try:
        # 启动对话
        await dialogue_system.start_dialogue()
        
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
        await dialogue_system.stop_dialogue()
        
        print("\n🎉 Live API对话系统测试完成！")


if __name__ == "__main__":
    asyncio.run(main())