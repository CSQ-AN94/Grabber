#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VAD感知对话系统 - 修复"话唠"问题
利用Live API内置VAD功能，让AI自己决定何时回复
禁用代码执行功能，优化音频流处理
"""

import sys
import os
import asyncio
import logging
import threading
import time
import numpy as np
from typing import Optional, Dict, Any

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google import genai
from google.genai import types

from intelligence.speech import SpeechSystem, SentenceBuffer
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from utils.config import load_config, setup_logging
from utils.state import WorldState

# 音频处理
try:
    import sounddevice as sd
except ImportError:
    sd = None


class VADAwareAudioStreamer:
    """VAD感知音频流处理器"""
    
    def __init__(self, sample_rate: int = 16000, chunk_size: int = 1024):
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.is_streaming = False
        self.audio_queue = asyncio.Queue(maxsize=50)  # 减小队列大小
        self.logger = logging.getLogger(__name__)
        
        # VAD相关
        self.silence_start_time = None
        self.silence_threshold = 0.5  # 0.5秒静音后发送audioStreamEnd，更快检测静音
        
        self._setup_audio_device()
    
    def _setup_audio_device(self):
        """配置音频设备"""
        if not sd:
            self.logger.error("sounddevice 未安装")
            self.input_device = None
            return
            
        try:
            devices = sd.query_devices()
            self.input_device = None
            
            # 查找支持16kHz的设备（Live API推荐）
            for device_id, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    try:
                        # 优先尝试16kHz
                        sd.check_input_settings(
                            device=device_id, 
                            samplerate=16000,
                            channels=1
                        )
                        self.input_device = device_id
                        self.sample_rate = 16000
                        self.logger.info(f"✅ 音频设备: [{device_id}] {device['name']} @ 16kHz")
                        return
                    except:
                        # 尝试其他采样率
                        for rate in [44100, 48000, 22050]:
                            try:
                                sd.check_input_settings(
                                    device=device_id, 
                                    samplerate=rate,
                                    channels=1
                                )
                                self.input_device = device_id
                                self.sample_rate = rate
                                self.logger.info(f"✅ 音频设备: [{device_id}] {device['name']} @ {rate}Hz")
                                return
                            except:
                                continue
            
            self.logger.warning("未找到合适的音频设备，使用模拟音频")
                
        except Exception as e:
            self.logger.error(f"音频设备配置失败: {e}")
            self.input_device = None
    
    def _audio_callback(self, indata, frames, time, status):
        """音频输入回调 - VAD感知"""
        if status:
            self.logger.debug(f"音频状态: {status}")
        
        if self.is_streaming:
            try:
                # 转换为16位PCM
                audio_data = (indata.flatten() * 32767).astype(np.int16)
                audio_bytes = audio_data.tobytes()
                
                # VAD: 检测是否有有意义的音频
                has_speech = self._detect_speech_activity(audio_data)
                
                if has_speech:
                    # 有语音活动，重置静音计时器
                    self.silence_start_time = None
                    
                    # 发送音频数据
                    try:
                        self.audio_queue.put_nowait(('audio', audio_bytes))
                    except asyncio.QueueFull:
                        # 队列满时丢弃最老的数据
                        try:
                            self.audio_queue.get_nowait()
                            self.audio_queue.put_nowait(('audio', audio_bytes))
                        except asyncio.QueueEmpty:
                            pass
                else:
                    # 检测静音
                    current_time = time.inputBufferAdcTime
                    if self.silence_start_time is None:
                        self.silence_start_time = current_time
                    elif current_time - self.silence_start_time > self.silence_threshold:
                        # 静音超过阈值，发送audioStreamEnd信号
                        try:
                            self.audio_queue.put_nowait(('silence_end', None))
                            self.silence_start_time = None  # 重置
                        except asyncio.QueueFull:
                            pass
                        
            except Exception as e:
                self.logger.debug(f"音频处理错误: {e}")
    
    def _detect_speech_activity(self, audio_data: np.ndarray) -> bool:
        """简单的语音活动检测"""
        # 计算音频能量
        energy = np.mean(np.abs(audio_data))
        
        # 设置更高的阈值，减少误识别
        speech_threshold = 2000  # 提高阈值，减少环境噪音触发
        
        return energy > speech_threshold
    
    async def start_streaming(self):
        """开始音频流"""
        if self.input_device is None:
            self.logger.warning("使用模拟音频流")
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
            self.logger.info(f"🎤 VAD感知音频流已启动 ({self.sample_rate}Hz)")
            
        except Exception as e:
            self.logger.error(f"启动音频流失败: {e}")
            await self._start_mock_audio_stream()
    
    async def _start_mock_audio_stream(self):
        """模拟音频流 - 只在有"语音"时发送"""
        self.is_streaming = True
        self.logger.info("🎤 模拟VAD感知音频流已启动")
        
        # 启动模拟任务
        asyncio.create_task(self._generate_mock_speech_events())
    
    async def _generate_mock_speech_events(self):
        """生成模拟语音事件"""
        speech_intervals = [
            (5, 3),   # 5秒后说话3秒
            (15, 2),  # 15秒后说话2秒
            (25, 4),  # 25秒后说话4秒
        ]
        
        start_time = time.time()
        
        for speak_at, duration in speech_intervals:
            # 等待到说话时间
            while time.time() - start_time < speak_at:
                if not self.is_streaming:
                    return
                await asyncio.sleep(0.1)
            
            self.logger.info(f"🗣️ 模拟用户开始说话 ({duration}秒)")
            
            # 模拟说话期间发送音频
            speak_end = time.time() + duration
            while time.time() < speak_end and self.is_streaming:
                # 生成有"能量"的音频数据
                audio_data = np.random.randint(-1000, 1000, self.chunk_size, dtype=np.int16)
                audio_bytes = audio_data.tobytes()
                
                try:
                    self.audio_queue.put_nowait(('audio', audio_bytes))
                except asyncio.QueueFull:
                    pass
                
                await asyncio.sleep(self.chunk_size / self.sample_rate)
            
            # 说话结束，发送静音信号
            self.logger.info(f"🤫 模拟用户停止说话")
            try:
                self.audio_queue.put_nowait(('silence_end', None))
            except asyncio.QueueFull:
                pass
            
            await asyncio.sleep(1)  # 静音间隔
    
    async def get_audio_event(self) -> Optional[tuple]:
        """获取音频事件 (事件类型, 数据)"""
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
        
        self.logger.info("🎤 VAD感知音频流已停止")


class VADAwareDialogueSystem:
    """
    VAD感知对话系统
    利用Live API内置VAD，让AI自己决定何时回复
    """
    
    def __init__(self, config_path: str = "config.ini"):
        self.config = load_config(config_path)
        self.logger = logging.getLogger(__name__)
        
        # Live API组件
        self.client = genai.Client(api_key=self.config.llm.gemini_api_key)
        self.model = "gemini-2.0-flash-live-001"
        self.session = None
        
        # VAD感知音频流
        self.audio_streamer = VADAwareAudioStreamer(
            sample_rate=16000,  # Live API推荐16kHz
            chunk_size=1024
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
        self.audio_events_sent = 0
        self.start_time = None
        
        # 初始化
        self.world_state.initialize_world_map(mock_data=True)
        self.logger.info("VAD感知对话系统初始化完成")
    
    def _create_live_config(self) -> types.LiveConnectConfig:
        """创建Live API配置 - 禁用代码执行"""
        config_dict = {
            "response_modalities": ["TEXT"],  # 只要文本输出
            "system_instruction": """你是一个智能零售机器人助手。
只有在用户明确发出语音指令时才回复。
不要主动询问用户需要什么帮助。
如果用户没有明确要求，请保持安静。
当用户有具体请求时，直接执行相应的工具函数。""",
            "tools": self.tool_registry.get_tool_definitions(),
            
            # VAD配置 - 使用默认的自动VAD
            "realtime_input_config": {
                "automatic_activity_detection": {
                    "disabled": False,  # 启用自动VAD
                    "start_of_speech_sensitivity": "START_SENSITIVITY_LOW",   # 降低语音开始敏感度
                    "end_of_speech_sensitivity": "END_SENSITIVITY_LOW",       # 降低语音结束敏感度
                }
            },
            
            # 尝试禁用代码执行
            "generation_config": {
                "temperature": 0.7,
                "candidate_count": 1,
                # 注意：可能需要不同的参数名
            }
        }
        
        return types.LiveConnectConfig(**config_dict)
    
    async def start_dialogue(self):
        """启动VAD感知对话"""
        if self.is_running:
            self.logger.warning("对话系统已在运行")
            return
        
        self.is_running = True
        self.start_time = time.time()
        
        self.logger.info("=" * 60)
        self.logger.info("启动VAD感知对话系统")
        self.logger.info("音频输入：VAD感知麦克风流 → Live API")
        self.logger.info("文本输入：工具callback → Live API")
        self.logger.info("文本输出：Live API JSON → 工具调用 + TTS")
        self.logger.info("VAD策略：让Live API自己决定何时回复")
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
            
            # 启动VAD感知音频流
            await self.audio_streamer.start_streaming()
            
            # 连接Live API
            config = self._create_live_config()
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                self.session = session
                self.logger.info("✅ 已连接到Gemini Live API (VAD模式)")
                
                # 发送初始问候
                await self._send_initial_greeting()
                
                # 运行并发任务
                audio_task = asyncio.create_task(self._vad_audio_loop())
                response_task = asyncio.create_task(self._response_processing_loop())
                
                # 等待任务完成
                await asyncio.gather(audio_task, response_task, return_exceptions=True)
                
        except KeyboardInterrupt:
            self.logger.info("\n🛑 用户请求停止对话...")
        except Exception as e:
            self.logger.error(f"VAD对话错误: {e}")
            raise
        finally:
            await self.stop_dialogue()
    
    async def _send_initial_greeting(self):
        """发送初始问候"""
        greeting = "智能零售助手已准备就绪。请说话，我会根据您的需求提供帮助。"
        self.logger.info(f"🤖 系统: {greeting}")
        self._queue_speech_output(greeting)
    
    async def _vad_audio_loop(self):
        """VAD感知音频循环"""
        self.logger.info("🎤 开始VAD感知音频处理...")
        
        while self.is_running:
            try:
                audio_event = await self.audio_streamer.get_audio_event()
                
                if audio_event:
                    event_type, data = audio_event
                    
                    if event_type == 'audio' and data:
                        # 发送音频数据到Live API
                        self.audio_events_sent += 1
                        await self.session.send_realtime_input(
                            audio=types.Blob(
                                data=data,
                                mime_type=f"audio/pcm;rate={self.audio_streamer.sample_rate}"
                            )
                        )
                        
                        if self.audio_events_sent % 100 == 0:  # 每100个音频包记录一次
                            self.logger.debug(f"已发送 {self.audio_events_sent} 个音频包")
                    
                    elif event_type == 'silence_end':
                        # 发送音频流结束信号
                        self.logger.info("🤫 检测到静音，发送audioStreamEnd")
                        try:
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"audio_stream_end": {}}]},
                                turn_complete=True
                            )
                        except Exception as e:
                            self.logger.debug(f"audioStreamEnd发送错误: {e}")
                            # 如果audioStreamEnd不工作，尝试其他方法
                            pass
                
                await asyncio.sleep(0.01)
                
            except Exception as e:
                self.logger.error(f"VAD音频处理错误: {e}")
                if "1007" in str(e):
                    self.logger.error("音频格式错误")
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
            
            # 处理可执行代码警告
            if hasattr(response, 'executable_code'):
                self.logger.warning(f"检测到可执行代码，已忽略: {response.executable_code}")
            
            # 处理服务器内容（工具调用）
            if hasattr(response, 'server_content') and response.server_content:
                await self._handle_server_content(response.server_content)
        
        # 处理完整的文本响应
        if text_parts:
            full_text = ''.join(text_parts).strip()
            if full_text:
                self.dialogue_count += 1
                self.logger.info(f"🤖 [对话 #{self.dialogue_count}] AI: {full_text}")
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
            self.logger.info(f"🛠️ [工具 #{self.tool_calls_count}] {function_name} with {parameters}")
            
            # 执行工具
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
            
            # 工具结果语音输出
            if result.get("message"):
                self.logger.info(f"🔧 工具结果: {result['message']}")
                self._queue_speech_output(result["message"])
            
        except Exception as e:
            self.logger.error(f"工具调用错误: {e}")
    
    def _queue_speech_output(self, text: str):
        """语音输出队列"""
        try:
            if text and text.strip():
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
        
        self.logger.info("🛑 停止VAD感知对话系统...")
        self.is_running = False
        self.stop_event.set()
        
        try:
            await self.audio_streamer.stop_streaming()
            self.sentence_buffer.flush()
            await asyncio.sleep(2)
            self.sentence_buffer.stop()
            self.speech_system.stop_speech_system()
            
            self.logger.info("✅ VAD感知对话系统已停止")
            
        except Exception as e:
            self.logger.error(f"停止系统错误: {e}")
    
    def get_dialogue_stats(self) -> dict:
        """获取对话统计"""
        uptime = time.time() - self.start_time if self.start_time else 0
        
        return {
            "dialogue_count": self.dialogue_count,
            "tool_calls_count": self.tool_calls_count,
            "audio_events_sent": self.audio_events_sent,
            "uptime_seconds": uptime,
            "is_running": self.is_running,
            "speech_consumer_stats": {
                "sentences_processed": self.speech_consumer.sentence_count,
                "is_running": self.speech_consumer.is_running
            }
        }


class VoiceOutputConsumer:
    """语音输出消费者"""
    
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
                self.logger.info(f"🗣️ [#{self.sentence_count}] TTS: '{sentence[:30]}...'")
                
                try:
                    import threading as thread_module
                    
                    def run_speech_task(text_to_speak):
                        try:
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            result = loop.run_until_complete(self.speech_system.say(text_to_speak))
                            loop.close()
                        except Exception as e:
                            self.logger.error(f"TTS错误: {e}")
                    
                    speech_thread = thread_module.Thread(target=run_speech_task, args=(sentence,))
                    speech_thread.daemon = True
                    speech_thread.start()
                    
                except Exception as e:
                    self.logger.error(f"语音合成错误: {e}")
            else:
                time.sleep(0.1)
        
        self.logger.info(f"🗣️ [语音消费者] 已停止 (共 {self.sentence_count} 句)")
        self.is_running = False


async def main():
    """主函数 - VAD感知对话系统"""
    print("🎤 VAD感知对话系统")
    print("=" * 60)
    print("利用Live API内置VAD，让AI自己决定何时回复")
    print("解决'话唠'问题，优化音频流处理")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 创建系统
    dialogue_system = VADAwareDialogueSystem()
    
    try:
        # 启动VAD感知对话
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
        print(f"  音频事件: {stats['audio_events_sent']}")
        print(f"  运行时间: {stats['uptime_seconds']:.1f}秒")
        print(f"  语音句子: {stats['speech_consumer_stats']['sentences_processed']}")
        
        await dialogue_system.stop_dialogue()
        print("\n🎉 VAD感知对话系统测试完成！")


if __name__ == "__main__":
    asyncio.run(main())