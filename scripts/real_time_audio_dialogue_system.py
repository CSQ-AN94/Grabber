#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
实时音频对话系统 - 真正的Live API集成
音频输入：麦克风持续监听 → 音频流 → Live API
文本输入：系统内部callback（工具结果）→ Live API  
文本输出：Live API JSON → 工具调用 + 实时语音合成
"""

import sys
import os
import asyncio
import logging
import threading
import time
import json
import numpy as np
from typing import Optional, Dict, Any, Callable
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

# 音频处理
try:
    import sounddevice as sd
except ImportError:
    sd = None


class AudioStreamer:
    """实时音频流处理器"""
    
    def __init__(self, sample_rate: int = 16000, chunk_size: int = 1024):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.is_streaming = False
        self.audio_queue = asyncio.Queue(maxsize=100)
        self.logger = logging.getLogger(__name__)
        
        # 配置音频设备
        self._setup_audio_device()
    
    def _setup_audio_device(self):
        """配置音频设备"""
        if not sd:
            self.logger.error("sounddevice 未安装，无法使用音频流")
            self.input_device = None
            return
            
        try:
            # 查找可用的输入设备
            devices = sd.query_devices()
            self.logger.info("扫描音频设备...")
            
            # 寻找默认输入设备或任何可用输入设备
            self.input_device = None
            for device_id, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    try:
                        # 尝试使用更宽松的采样率设置
                        supported_rates = [16000, 44100, 48000, 22050]
                        for rate in supported_rates:
                            try:
                                sd.check_input_settings(
                                    device=device_id, 
                                    samplerate=rate,
                                    channels=1
                                )
                                self.input_device = device_id
                                self.sample_rate = rate
                                self.logger.info(f"✅ 选择音频设备: [{device_id}] {device['name']} @ {rate}Hz")
                                return
                            except:
                                continue
                    except:
                        continue
            
            if self.input_device is None:
                self.logger.warning("未找到合适的音频输入设备，将使用模拟音频")
                
        except Exception as e:
            self.logger.error(f"音频设备配置失败: {e}")
            self.input_device = None
    
    def _audio_callback(self, indata, frames, time, status):
        """音频输入回调"""
        if status:
            self.logger.debug(f"音频状态: {status}")
        
        if self.is_streaming:
            try:
                # 转换为16位PCM
                audio_data = (indata.flatten() * 32767).astype(np.int16)
                audio_bytes = audio_data.tobytes()
                
                # 验证音频数据
                if self._validate_audio_chunk(audio_bytes):
                    try:
                        self.audio_queue.put_nowait(audio_bytes)
                    except asyncio.QueueFull:
                        # 队列满时丢弃最老的数据
                        try:
                            self.audio_queue.get_nowait()
                            self.audio_queue.put_nowait(audio_bytes)
                        except asyncio.QueueEmpty:
                            pass
            except Exception as e:
                self.logger.debug(f"音频处理错误: {e}")
    
    def _validate_audio_chunk(self, chunk: bytes) -> bool:
        """验证音频块"""
        if len(chunk) < 64 or len(chunk) % 2 != 0:
            return False
        
        # 检查音频幅度
        audio_data = np.frombuffer(chunk, dtype=np.int16)
        max_amplitude = np.max(np.abs(audio_data))
        return max_amplitude > 50  # 过滤太小的音频
    
    async def start_streaming(self):
        """开始音频流"""
        if self.input_device is None:
            self.logger.warning("没有可用的音频设备，启动模拟音频流")
            await self._start_mock_audio_stream()
            return
        
        try:
            self.audio_stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype=np.float32,
                blocksize=self.chunk_size,
                callback=self._audio_callback,
                device=self.input_device
            )
            
            self.audio_stream.start()
            self.is_streaming = True
            self.logger.info(f"🎤 音频流已启动 ({self.sample_rate}Hz)")
            
        except Exception as e:
            self.logger.error(f"启动音频流失败: {e}")
            await self._start_mock_audio_stream()
    
    async def _start_mock_audio_stream(self):
        """启动模拟音频流"""
        self.is_streaming = True
        self.logger.info("🎤 模拟音频流已启动")
        
        # 生成模拟的静音音频数据
        asyncio.create_task(self._generate_mock_audio())
    
    async def _generate_mock_audio(self):
        """生成模拟音频数据"""
        while self.is_streaming:
            # 生成静音数据
            silence = np.zeros(self.chunk_size, dtype=np.int16)
            audio_bytes = silence.tobytes()
            
            try:
                self.audio_queue.put_nowait(audio_bytes)
            except asyncio.QueueFull:
                try:
                    self.audio_queue.get_nowait()
                    self.audio_queue.put_nowait(audio_bytes)
                except asyncio.QueueEmpty:
                    pass
            
            await asyncio.sleep(self.chunk_size / self.sample_rate)  # 模拟实时
    
    async def get_audio_chunk(self) -> Optional[bytes]:
        """获取音频块"""
        try:
            return await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None
    
    async def stop_streaming(self):
        """停止音频流"""
        self.is_streaming = False
        
        if hasattr(self, 'audio_stream') and self.audio_stream:
            try:
                self.audio_stream.stop()
                self.audio_stream.close()
            except:
                pass
        
        # 清空队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        self.logger.info("🎤 音频流已停止")


class RealTimeAudioDialogueSystem:
    """
    实时音频对话系统
    音频输入：麦克风流 → Live API
    文本输入：工具callback → Live API
    文本输出：Live API JSON → 工具调用 + TTS
    """
    
    def __init__(self, config_path: str = "config.ini"):
        self.config = load_config(config_path)
        self.logger = logging.getLogger(__name__)
        
        # Live API组件
        self.client = genai.Client(api_key=self.config.llm.gemini_api_key)
        self.model = "gemini-2.0-flash-live-001"
        self.session = None
        
        # 音频流组件
        self.audio_streamer = AudioStreamer(
            sample_rate=self.config.agent.audio_sample_rate,
            chunk_size=self.config.agent.audio_chunk_size
        )
        
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
        
        # 统计信息
        self.dialogue_count = 0
        self.tool_calls_count = 0
        self.start_time = None
        
        # 初始化
        self.world_state.initialize_world_map(mock_data=True)
        self.logger.info("实时音频对话系统初始化完成")
    
    def _create_live_config(self) -> types.LiveConnectConfig:
        """创建Live API配置"""
        config_dict = {
            "response_modalities": ["TEXT"],  # 只要文本输出，语音我们自己合成
            "system_instruction": """你是一个智能零售机器人助手。
你只能通过工具调用来执行操作，不要直接描述动作。
当用户请求时，直接调用相应的工具函数。
保持回复简洁，专注于工具调用。""",
            "tools": self.tool_registry.get_tool_definitions()
        }
        
        return types.LiveConnectConfig(**config_dict)
    
    async def start_dialogue(self):
        """启动实时音频对话"""
        if self.is_running:
            self.logger.warning("对话系统已在运行")
            return
        
        self.is_running = True
        self.start_time = time.time()
        
        self.logger.info("=" * 60)
        self.logger.info("启动实时音频对话系统")
        self.logger.info("音频输入：麦克风流 → Live API")
        self.logger.info("文本输入：工具callback → Live API")
        self.logger.info("文本输出：Live API JSON → 工具调用 + TTS")
        self.logger.info("=" * 60)
        
        try:
            # 启动语音输出消费者
            consumer_thread = threading.Thread(
                target=self.speech_consumer.start_consuming,
                args=(self.stop_event,),
                name="VoiceOutputConsumerThread"
            )
            consumer_thread.daemon = True
            consumer_thread.start()
            
            # 启动音频流
            await self.audio_streamer.start_streaming()
            
            # 连接Live API
            config = self._create_live_config()
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                self.session = session
                self.logger.info("✅ 已连接到Gemini Live API")
                self.logger.info("🎤 开始实时音频对话...")
                
                # 发送初始系统消息
                await self._send_system_greeting()
                
                # 运行并发任务
                audio_task = asyncio.create_task(self._audio_input_loop())
                response_task = asyncio.create_task(self._response_processing_loop())
                
                # 等待任务完成
                try:
                    await asyncio.gather(audio_task, response_task, return_exceptions=True)
                except Exception as e:
                    self.logger.error(f"任务执行错误: {e}")
                
        except KeyboardInterrupt:
            self.logger.info("\n🛑 用户请求停止对话...")
        except Exception as e:
            self.logger.error(f"实时对话错误: {e}")
            raise
        finally:
            await self.stop_dialogue()
    
    async def _send_system_greeting(self):
        """发送系统问候"""
        greeting = "系统已准备就绪，请开始对话。"
        self.logger.info(f"🤖 系统: {greeting}")
        self._queue_speech_output(greeting)
    
    async def _audio_input_loop(self):
        """音频输入循环"""
        self.logger.info("🎤 开始音频输入流...")
        
        while self.is_running:
            try:
                audio_chunk = await self.audio_streamer.get_audio_chunk()
                if audio_chunk and len(audio_chunk) >= 64:
                    # 发送音频到Live API
                    await self.session.send_realtime_input(
                        audio=types.Blob(
                            data=audio_chunk,
                            mime_type=f"audio/pcm;rate={self.audio_streamer.sample_rate}"
                        )
                    )
                    
                await asyncio.sleep(0.01)  # 防止CPU占用过高
                
            except Exception as e:
                self.logger.error(f"音频输入错误: {e}")
                if "1007" in str(e):
                    self.logger.error("音频格式错误，停止音频输入")
                    break
                await asyncio.sleep(0.1)
    
    async def _response_processing_loop(self):
        """响应处理循环"""
        try:
            while self.is_running:
                turn = self.session.receive()
                await self._process_turn(turn)
        except Exception as e:
            self.logger.error(f"响应处理错误: {e}")
    
    async def _process_turn(self, turn):
        """处理一个完整的回合"""
        text_parts = []
        
        async for response in turn:
            # 处理文本响应
            if hasattr(response, 'text') and response.text:
                text_parts.append(response.text)
            
            # 处理服务器内容（工具调用）
            if hasattr(response, 'server_content') and response.server_content:
                await self._handle_server_content(response.server_content)
        
        # 处理完整的文本响应
        if text_parts:
            full_text = ''.join(text_parts).strip()
            if full_text:
                self.dialogue_count += 1
                self.logger.info(f"🤖 [对话 #{self.dialogue_count}] AI响应: {full_text}")
                self._queue_speech_output(full_text)
    
    async def _handle_server_content(self, server_content):
        """处理服务器内容（工具调用）"""
        try:
            if hasattr(server_content, 'model_turn') and server_content.model_turn:
                if hasattr(server_content.model_turn, 'parts'):
                    for part in server_content.model_turn.parts:
                        if hasattr(part, 'function_call') and part.function_call:
                            await self._execute_tool_call(part.function_call)
        except Exception as e:
            self.logger.error(f"处理服务器内容错误: {e}")
    
    async def _execute_tool_call(self, function_call):
        """执行工具调用"""
        try:
            function_name = function_call.name
            parameters = dict(function_call.args) if hasattr(function_call, 'args') else {}
            
            self.tool_calls_count += 1
            self.logger.info(f"🛠️ [工具调用 #{self.tool_calls_count}] {function_name} with {parameters}")
            
            # 执行工具
            result = await self.tool_registry.execute_tool(function_name, parameters)
            
            # 发送结果回Live API（这是关键的callback机制）
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
            
            # 工具结果也进行语音输出
            if result.get("message"):
                self.logger.info(f"🔧 工具结果: {result['message']}")
                self._queue_speech_output(result["message"])
            
        except Exception as e:
            self.logger.error(f"工具调用执行错误: {e}")
    
    def _queue_speech_output(self, text: str):
        """将文本加入语音输出队列"""
        try:
            if text and text.strip():
                # 确保文本有正确的句号结尾
                text_with_punctuation = text.strip()
                if not text_with_punctuation.endswith(('。', '！', '？', '……')):
                    text_with_punctuation += '。'
                
                self.sentence_buffer.add_text(text_with_punctuation)
                
        except Exception as e:
            self.logger.error(f"语音输出队列错误: {e}")
    
    async def stop_dialogue(self):
        """停止对话"""
        if not self.is_running:
            return
        
        self.logger.info("🛑 停止实时音频对话系统...")
        self.is_running = False
        self.stop_event.set()
        
        try:
            # 停止音频流
            await self.audio_streamer.stop_streaming()
            
            # 刷新语音缓冲区
            self.sentence_buffer.flush()
            await asyncio.sleep(2)
            
            # 停止语音组件
            self.sentence_buffer.stop()
            self.speech_system.stop_speech_system()
            
            self.logger.info("✅ 实时音频对话系统已停止")
            
        except Exception as e:
            self.logger.error(f"停止系统错误: {e}")
    
    def get_dialogue_stats(self) -> dict:
        """获取对话统计"""
        uptime = time.time() - self.start_time if self.start_time else 0
        
        return {
            "dialogue_count": self.dialogue_count,
            "tool_calls_count": self.tool_calls_count,
            "uptime_seconds": uptime,
            "is_running": self.is_running,
            "speech_consumer_stats": {
                "sentences_processed": self.speech_consumer.sentence_count,
                "is_running": self.speech_consumer.is_running
            }
        }


class VoiceOutputConsumer:
    """语音输出消费者 - 复用验证的架构"""
    
    def __init__(self, sentence_buffer: SentenceBuffer, speech_system: SpeechSystem):
        self.sentence_buffer = sentence_buffer
        self.speech_system = speech_system
        self.logger = logging.getLogger(__name__)
        self.sentence_count = 0
        self.is_running = False
    
    def start_consuming(self, stop_event: threading.Event):
        """启动语音消费者"""
        self.is_running = True
        self.logger.info("🗣️ [语音消费者] 已启动")
        
        while not stop_event.is_set() and self.is_running:
            sentence = self.sentence_buffer.get_sentence(block=False)
            
            if sentence:
                self.sentence_count += 1
                self.logger.info(f"🗣️ [语音 #{self.sentence_count}] 合成: '{sentence[:30]}...'")
                
                try:
                    import threading as thread_module
                    
                    def run_speech_task(text_to_speak):
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            result = loop.run_until_complete(self.speech_system.say(text_to_speak))
                            loop.close()
                            
                            if result.get("success"):
                                self.logger.debug(f"   语音播放完成: {text_to_speak[:20]}...")
                        except Exception as e:
                            self.logger.error(f"   语音播放错误: {e}")
                    
                    speech_thread = thread_module.Thread(target=run_speech_task, args=(sentence,))
                    speech_thread.daemon = True
                    speech_thread.start()
                    
                except Exception as e:
                    self.logger.error(f"语音合成错误: {e}")
            else:
                time.sleep(0.1)
        
        self.logger.info(f"🗣️ [语音消费者] 已停止 (共处理 {self.sentence_count} 句)")
        self.is_running = False


async def main():
    """主函数 - 实时音频对话系统"""
    print("🎤 实时音频对话系统")
    print("=" * 60)
    print("音频输入：麦克风流 → Live API")
    print("文本输入：工具callback → Live API")  
    print("文本输出：Live API JSON → 工具调用 + TTS")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 创建系统
    dialogue_system = RealTimeAudioDialogueSystem()
    
    try:
        # 启动实时对话
        await dialogue_system.start_dialogue()
        
    except Exception as e:
        print(f"❌ 系统错误: {e}")
        logging.error(f"系统错误: {e}", exc_info=True)
    finally:
        # 显示统计
        stats = dialogue_system.get_dialogue_stats()
        print(f"\n📊 对话统计:")
        print(f"  对话次数: {stats['dialogue_count']}")
        print(f"  工具调用: {stats['tool_calls_count']}")
        print(f"  运行时间: {stats['uptime_seconds']:.1f}秒")
        print(f"  语音句子: {stats['speech_consumer_stats']['sentences_processed']}")
        
        await dialogue_system.stop_dialogue()
        print("\n🎉 实时音频对话系统测试完成！")


if __name__ == "__main__":
    asyncio.run(main())