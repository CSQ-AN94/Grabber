#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
修复版VAD感知对话系统
基于音频诊断结果调整VAD阈值和采样率配置
解决"永远检测到静音"的问题
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


class FixedVADAudioStreamer:
    """修复版VAD感知音频流处理器"""
    
    def __init__(self, sample_rate: int = 48000, chunk_size: int = 1024):
        # 使用诊断发现的最佳配置
        self.sample_rate = sample_rate  # 使用48kHz（设备原生支持）
        self.chunk_size = chunk_size
        self.is_streaming = False
        self.audio_queue = asyncio.Queue(maxsize=50)
        self.logger = logging.getLogger(__name__)
        
        # 修复后的VAD参数
        self.silence_start_time = None
        self.silence_threshold = 1.0  # 减少到1秒，更快响应
        
        # 基于诊断结果的动态阈值
        self.base_speech_threshold = 800  # 基础阈值，约为中位数
        self.adaptive_threshold = self.base_speech_threshold
        self.energy_history = []
        self.max_history_length = 100
        
        self._setup_audio_device()
    
    def _setup_audio_device(self):
        """配置音频设备 - 使用诊断发现的设备"""
        if not sd:
            self.logger.error("sounddevice 未安装")
            self.input_device = None
            return
            
        try:
            devices = sd.query_devices()
            self.input_device = None
            
            # 寻找诊断中发现的设备 sof-hda-dsp
            for device_id, device in enumerate(devices):
                if device['max_input_channels'] > 0 and 'sof-hda-dsp' in device['name']:
                    try:
                        sd.check_input_settings(
                            device=device_id, 
                            samplerate=48000,  # 使用设备原生支持的48kHz
                            channels=1
                        )
                        self.input_device = device_id
                        self.sample_rate = 48000
                        self.logger.info(f"✅ 使用音频设备: [{device_id}] {device['name']} @ 48kHz")
                        return
                    except Exception as e:
                        self.logger.debug(f"设备 {device_id} 配置失败: {e}")
            
            # 如果没找到，使用任何可用的输入设备
            for device_id, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    try:
                        sd.check_input_settings(device=device_id, samplerate=48000, channels=1)
                        self.input_device = device_id
                        self.sample_rate = 48000
                        self.logger.info(f"✅ 备选音频设备: [{device_id}] {device['name']} @ 48kHz")
                        return
                    except:
                        continue
            
            self.logger.warning("未找到合适的音频设备，使用模拟音频")
                
        except Exception as e:
            self.logger.error(f"音频设备配置失败: {e}")
            self.input_device = None
    
    def _audio_callback(self, indata, frames, time, status):
        """音频输入回调 - 改进的VAD检测"""
        if status:
            self.logger.debug(f"音频状态: {status}")
        
        if self.is_streaming:
            try:
                # 转换为16位PCM（Live API要求）
                audio_data = (indata.flatten() * 32767).astype(np.int16)
                
                # 重采样到16kHz（Live API推荐）
                if self.sample_rate != 16000:
                    audio_data = self._resample_audio(audio_data)
                
                audio_bytes = audio_data.tobytes()
                
                # 改进的VAD检测
                has_speech = self._detect_speech_activity_improved(audio_data)
                
                if has_speech:
                    # 有语音活动，重置静音计时器
                    self.silence_start_time = None
                    
                    # 发送音频数据
                    try:
                        self.audio_queue.put_nowait(('audio', audio_bytes))
                    except asyncio.QueueFull:
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
    
    def _resample_audio(self, audio_data: np.ndarray) -> np.ndarray:
        """简单重采样到16kHz"""
        if self.sample_rate == 16000:
            return audio_data
        
        # 简单降采样：48kHz -> 16kHz (3:1)
        if self.sample_rate == 48000:
            return audio_data[::3]
        
        # 其他采样率的处理
        ratio = int(self.sample_rate / 16000)
        if ratio > 1:
            return audio_data[::ratio]
        
        return audio_data
    
    def _detect_speech_activity_improved(self, audio_data: np.ndarray) -> bool:
        """改进的语音活动检测"""
        # 计算音频能量
        energy = np.mean(np.abs(audio_data))
        
        # 更新能量历史用于自适应阈值
        self.energy_history.append(energy)
        if len(self.energy_history) > self.max_history_length:
            self.energy_history.pop(0)
        
        # 自适应阈值计算
        if len(self.energy_history) >= 10:
            median_energy = np.median(self.energy_history)
            # 自适应阈值 = 基础阈值 与 历史中位数的较小值
            self.adaptive_threshold = min(self.base_speech_threshold, median_energy * 1.5)
        
        # 语音检测逻辑
        is_speech = energy > self.adaptive_threshold
        
        # 调试信息（每100个样本输出一次）
        if len(self.energy_history) % 100 == 0:
            self.logger.debug(f"VAD: 能量={energy:.1f}, 阈值={self.adaptive_threshold:.1f}, "
                            f"检测={'语音' if is_speech else '静音'}")
        
        return is_speech
    
    async def start_streaming(self):
        """开始音频流"""
        if self.input_device is None:
            self.logger.warning("使用模拟音频流（包含语音事件）")
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
            self.logger.info(f"🎤 修复版VAD音频流已启动 ({self.sample_rate}Hz -> 16kHz)")
            self.logger.info(f"   基础语音阈值: {self.base_speech_threshold}")
            
        except Exception as e:
            self.logger.error(f"启动音频流失败: {e}")
            await self._start_mock_audio_stream()
    
    async def _start_mock_audio_stream(self):
        """模拟音频流 - 包含真实的语音事件"""
        self.is_streaming = True
        self.logger.info("🎤 模拟VAD感知音频流已启动（包含语音事件）")
        
        # 启动模拟任务
        asyncio.create_task(self._generate_realistic_speech_events())
    
    async def _generate_realistic_speech_events(self):
        """生成逼真的语音事件"""
        speech_intervals = [
            (3, 2),   # 3秒后说话2秒
            (8, 3),   # 8秒后说话3秒
            (15, 4),  # 15秒后说话4秒
            (25, 2),  # 25秒后说话2秒
        ]
        
        start_time = time.time()
        
        for speak_at, duration in speech_intervals:
            # 等待到说话时间
            while time.time() - start_time < speak_at:
                if not self.is_streaming:
                    return
                
                # 在静音期间发送低能量音频
                silence_data = np.random.randint(-100, 100, self.chunk_size, dtype=np.int16)
                silence_bytes = silence_data.tobytes()
                
                try:
                    self.audio_queue.put_nowait(('audio', silence_bytes))
                except asyncio.QueueFull:
                    pass
                
                await asyncio.sleep(0.1)
            
            self.logger.info(f"🗣️ 模拟用户开始说话 ({duration}秒)")
            
            # 模拟说话期间发送高能量音频
            speak_end = time.time() + duration
            while time.time() < speak_end and self.is_streaming:
                # 生成有"语音能量"的音频数据（能量 > 800）
                speech_data = np.random.randint(-5000, 5000, self.chunk_size, dtype=np.int16)
                speech_bytes = speech_data.tobytes()
                
                try:
                    self.audio_queue.put_nowait(('audio', speech_bytes))
                except asyncio.QueueFull:
                    pass
                
                await asyncio.sleep(self.chunk_size / 16000)  # 按16kHz计算间隔
            
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
        
        self.logger.info("🎤 修复版VAD音频流已停止")


class FixedVADDialogueSystem:
    """修复版VAD感知对话系统"""
    
    def __init__(self, config_path: str = "config.ini"):
        self.config = load_config(config_path)
        self.logger = logging.getLogger(__name__)
        
        # Live API组件
        self.client = genai.Client(api_key=self.config.llm.gemini_api_key)
        self.model = "gemini-2.0-flash-live-001"
        self.session = None
        
        # 修复版VAD音频流
        self.audio_streamer = FixedVADAudioStreamer(
            sample_rate=48000,  # 使用设备原生支持的48kHz
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
        self.silence_events_sent = 0
        self.start_time = None
        
        # 初始化
        self.world_state.initialize_world_map(mock_data=True)
        self.logger.info("修复版VAD感知对话系统初始化完成")
    
    def _create_live_config(self) -> types.LiveConnectConfig:
        """创建Live API配置"""
        config_dict = {
            "response_modalities": ["TEXT"],
            "system_instruction": """你是一个智能零售机器人助手。
当用户明确发出语音指令时，请简洁回复并执行相应的工具函数。
不要主动询问用户需要什么帮助。
保持回复简短且专注于用户的具体请求。""",
            "tools": self.tool_registry.get_tool_definitions(),
            
            # 优化后的VAD配置
            "realtime_input_config": {
                "automatic_activity_detection": {
                    "disabled": False,
                    "start_of_speech_sensitivity": "START_SENSITIVITY_LOW",
                    "end_of_speech_sensitivity": "END_SENSITIVITY_LOW",
                }
            },
            
            "generation_config": {
                "temperature": 0.7,
                "candidate_count": 1,
            }
        }
        
        return types.LiveConnectConfig(**config_dict)
    
    async def start_dialogue(self):
        """启动修复版VAD对话"""
        if self.is_running:
            self.logger.warning("对话系统已在运行")
            return
        
        self.is_running = True
        self.start_time = time.time()
        
        self.logger.info("=" * 60)
        self.logger.info("🔧 启动修复版VAD感知对话系统")
        self.logger.info("🎯 VAD阈值已根据音频诊断结果优化")
        self.logger.info("🎤 使用48kHz采样 -> 16kHz Live API")
        self.logger.info("🧠 自适应语音检测阈值")
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
            
            # 启动修复版音频流
            await self.audio_streamer.start_streaming()
            
            # 连接Live API
            config = self._create_live_config()
            async with self.client.aio.live.connect(model=self.model, config=config) as session:
                self.session = session
                self.logger.info("✅ 已连接到Gemini Live API")
                
                # 发送初始问候
                await self._send_initial_greeting()
                
                # 运行并发任务
                audio_task = asyncio.create_task(self._audio_loop())
                response_task = asyncio.create_task(self._response_processing_loop())
                
                # 等待任务完成
                await asyncio.gather(audio_task, response_task, return_exceptions=True)
                
        except KeyboardInterrupt:
            self.logger.info("\n🛑 用户请求停止对话...")
        except Exception as e:
            self.logger.error(f"修复版VAD对话错误: {e}")
            raise
        finally:
            await self.stop_dialogue()
    
    async def _send_initial_greeting(self):
        """发送初始问候"""
        greeting = "修复版智能助手已准备就绪。VAD检测已优化，请正常说话。"
        self.logger.info(f"🤖 系统: {greeting}")
        self._queue_speech_output(greeting)
    
    async def _audio_loop(self):
        """音频处理循环"""
        self.logger.info("🎤 开始修复版音频处理...")
        
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
                                mime_type="audio/pcm;rate=16000"  # 标记为16kHz
                            )
                        )
                        
                        if self.audio_events_sent % 200 == 0:
                            self.logger.debug(f"已发送 {self.audio_events_sent} 个音频包")
                    
                    elif event_type == 'silence_end':
                        # 发送音频流结束信号
                        self.silence_events_sent += 1
                        self.logger.info(f"🤫 检测到静音结束 (#{self.silence_events_sent})，发送audioStreamEnd")
                        try:
                            await self.session.send_client_content(
                                turns={"role": "user", "parts": [{"audio_stream_end": {}}]},
                                turn_complete=True
                            )
                        except Exception as e:
                            self.logger.debug(f"audioStreamEnd发送错误: {e}")
                
                await asyncio.sleep(0.01)
                
            except Exception as e:
                self.logger.error(f"音频处理错误: {e}")
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
        
        self.logger.info("🛑 停止修复版VAD对话系统...")
        self.is_running = False
        self.stop_event.set()
        
        try:
            await self.audio_streamer.stop_streaming()
            self.sentence_buffer.flush()
            await asyncio.sleep(2)
            self.sentence_buffer.stop()
            self.speech_system.stop_speech_system()
            
            self.logger.info("✅ 修复版VAD对话系统已停止")
            
        except Exception as e:
            self.logger.error(f"停止系统错误: {e}")
    
    def get_dialogue_stats(self) -> dict:
        """获取对话统计"""
        uptime = time.time() - self.start_time if self.start_time else 0
        
        return {
            "dialogue_count": self.dialogue_count,
            "tool_calls_count": self.tool_calls_count,
            "audio_events_sent": self.audio_events_sent,
            "silence_events_sent": self.silence_events_sent,
            "uptime_seconds": uptime,
            "is_running": self.is_running,
            "vad_threshold": self.audio_streamer.adaptive_threshold,
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
    """主函数 - 修复版VAD对话系统"""
    print("🔧 修复版VAD感知对话系统")
    print("=" * 60)
    print("🎯 基于音频诊断结果优化VAD阈值")
    print("🎤 使用48kHz采样 -> 16kHz Live API")
    print("🧠 自适应语音检测算法")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 创建修复版系统
    dialogue_system = FixedVADDialogueSystem()
    
    try:
        # 启动修复版VAD对话
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
        print(f"  静音事件: {stats['silence_events_sent']}")
        print(f"  VAD阈值: {stats['vad_threshold']:.1f}")
        print(f"  运行时间: {stats['uptime_seconds']:.1f}秒")
        print(f"  语音句子: {stats['speech_consumer_stats']['sentences_processed']}")
        
        await dialogue_system.stop_dialogue()
        print("\n🎉 修复版VAD对话系统测试完成！")


if __name__ == "__main__":
    asyncio.run(main())