#!/usr/bin/env python3
"""
智能麦克风输入 - 集成VAD和实时音频流处理
专为Gemini Live API设计的智能音频输入模块
"""

import asyncio
import logging
import time
import threading
from typing import Optional, Tuple, Callable
import numpy as np
import sounddevice as sd
import subprocess
import select
import os
import scipy.signal


class SmartMicrophoneInput:
    """
    智能麦克风输入，集成VAD和实时音频流处理
    
    特性：
    1. 实时VAD（语音活动检测）
    2. 自动静音检测和事件通知
    3. 多种音频源支持（sounddevice优先，PulseAudio备选）
    4. 自适应阈值调整
    5. 异步音频事件处理
    """
    
    def __init__(self, 
                 sample_rate: int = 16000, 
                 chunk_size: int = 1024,
                 silence_threshold: float = 1.0,
                 speech_threshold: float = 100):
        """
        初始化智能麦克风输入
        
        Args:
            sample_rate: 目标采样率（固定16kHz for Gemini）
            chunk_size: 音频块大小
            silence_threshold: 静音阈值（秒）
            speech_threshold: 语音检测阈值
        """
        self.target_sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.silence_threshold = silence_threshold
        self.speech_threshold = speech_threshold
        
        # 硬件采样率（通过检测设备确定）
        self.hardware_sample_rate = None
        self.resample_ratio = None
        
        # 音频流和队列
        self.audio_queue = asyncio.Queue(maxsize=100)
        self.is_running = False
        self.audio_source = None
        self.audio_thread = None
        
        # VAD相关
        self.silence_start_time = None
        self.energy_history = []
        self.last_speech_time = None
        
        # 事件回调
        self.speech_start_callback: Optional[Callable] = None
        self.speech_end_callback: Optional[Callable] = None
        self.silence_end_callback: Optional[Callable] = None
        
        # 日志和统计
        self.logger = logging.getLogger(__name__)
        self.bytes_received = 0
        self.chunks_received = 0
        self.speech_events = 0
        self.silence_events = 0
        self.start_time = None
        
        # 初始化音频源
        self._initialize_audio_source()
    
    def _initialize_audio_source(self):
        """初始化音频源（优先sounddevice，备选PulseAudio）"""
        # 尝试sounddevice
        if self._try_sounddevice():
            self.audio_source = "sounddevice"
            self.logger.info("使用sounddevice作为音频源")
        # 备选PulseAudio
        elif self._try_pulseaudio():
            # 检查PulseAudio是否真的可用
            if self._test_pulseaudio_recording():
                self.audio_source = "pulseaudio"
                self.logger.info("使用PulseAudio作为音频源")
            else:
                self.audio_source = None
                self.logger.error("PulseAudio不可用，无法获取音频输入")
        else:
            self.audio_source = None
            self.logger.error("无可用音频源，无法获取音频输入")
    
    def _try_sounddevice(self) -> bool:
        """尝试使用sounddevice并检测合适的采样率"""
        try:
            devices = sd.query_devices()
            for device_id, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    # 尝试不同的采样率
                    test_rates = [self.target_sample_rate, 48000, 44100, 22050]
                    
                    for test_rate in test_rates:
                        try:
                            sd.check_input_settings(
                                device=device_id,
                                samplerate=test_rate,
                                channels=1
                            )
                            self.input_device = device_id
                            self.hardware_sample_rate = test_rate
                            
                            # 计算重采样比例
                            if test_rate != self.target_sample_rate:
                                self.resample_ratio = self.target_sample_rate / test_rate
                                self.logger.info(f"选择音频设备: [{device_id}] {device['name']}")
                                self.logger.info(f"硬件采样率: {test_rate}Hz, 目标采样率: {self.target_sample_rate}Hz")
                                self.logger.info(f"重采样比例: {self.resample_ratio:.3f}")
                            else:
                                self.resample_ratio = 1.0
                                self.logger.info(f"选择音频设备: [{device_id}] {device['name']}")
                                self.logger.info(f"采样率: {test_rate}Hz (无需重采样)")
                            
                            return True
                        except Exception:
                            continue
            return False
        except Exception as e:
            self.logger.debug(f"sounddevice初始化失败: {e}")
            return False
    
    def _try_pulseaudio(self) -> bool:
        """尝试使用PulseAudio"""
        try:
            # 检查pactl可用性
            result = subprocess.run(['which', 'pactl'], capture_output=True, text=True)
            if result.returncode != 0:
                return False
            
            # 获取音频源
            result = subprocess.run(['pactl', 'list', 'short', 'sources'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return False
            
            # 找到合适的音频源
            for line in result.stdout.strip().split('\n'):
                if line.strip() and '.monitor' not in line:
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        self.pulse_source = parts[1]
                        self.logger.info(f"选择PulseAudio源: {self.pulse_source}")
                        return True
            
            return False
        except Exception as e:
            self.logger.debug(f"PulseAudio初始化失败: {e}")
            return False
    
    def _test_pulseaudio_recording(self) -> bool:
        """测试PulseAudio录音是否真的可用"""
        try:
            # 首先检查音频源状态
            result = subprocess.run(['pactl', 'list', 'short', 'sources'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                self.logger.debug("无法获取PulseAudio源状态")
                return False
            
            # 检查选择的音频源是否处于SUSPENDED状态
            for line in result.stdout.strip().split('\n'):
                if self.pulse_source in line and 'SUSPENDED' in line:
                    self.logger.debug(f"PulseAudio源 {self.pulse_source} 处于SUSPENDED状态")
                    return False
            
            cmd = [
                'parec',
                '--device', self.pulse_source,
                '--format', 's16le',
                '--rate', str(self.sample_rate),
                '--channels', '1',
                '--raw'
            ]
            
            # 启动短暂的测试录音
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy()
            )
            
            # 等待一小段时间看是否有数据
            import time
            time.sleep(0.1)
            proc.terminate()
            
            # 检查是否有错误输出
            stdout, stderr = proc.communicate()
            
            if proc.returncode != 0 and stderr:
                self.logger.debug(f"PulseAudio录音测试失败: {stderr.decode()}")
                return False
            
            return True
            
        except Exception as e:
            self.logger.debug(f"PulseAudio录音测试错误: {e}")
            return False
    
    def _detect_speech_activity(self, audio_data: np.ndarray) -> bool:
        """语音活动检测"""
        # 计算RMS能量，更稳定的能量测量
        energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
        
        # 更新历史用于自适应
        self.energy_history.append(energy)
        if len(self.energy_history) > 100:
            self.energy_history.pop(0)
        
        # 自适应阈值 - 修复阈值过高的问题
        if len(self.energy_history) >= 10:
            median_energy = np.median(self.energy_history)
            # 进一步降低阈值，使其更敏感于真实语音
            adaptive_threshold = max(20, median_energy * 1.2)  # 最低20，更敏感
        else:
            # 初始阈值设置为更合理的值
            adaptive_threshold = 30  # 从50进一步降到30
        
        is_speech = energy > adaptive_threshold
        
        # 增加调试信息频率来诊断问题
        if len(self.energy_history) % 100 == 0:
            self.logger.info(f"VAD调试: RMS能量={energy:.1f}, 阈值={adaptive_threshold:.1f}, "
                           f"检测={'语音' if is_speech else '静音'}, 历史中位数={np.median(self.energy_history):.1f}")
        
        return is_speech
    
    def _process_audio_chunk(self, audio_data: np.ndarray):
        """处理音频块并生成事件"""
        has_speech = self._detect_speech_activity(audio_data)
        current_time = time.time()
        
        if has_speech:
            # 检测到语音
            if self.silence_start_time is not None:
                # 从静音转为语音
                self.silence_start_time = None
                self.speech_events += 1
                if self.speech_start_callback:
                    try:
                        self.speech_start_callback()
                    except Exception as e:
                        self.logger.error(f"语音开始回调错误: {e}")
            
            self.last_speech_time = current_time
            
            # 发送音频数据
            audio_bytes = audio_data.tobytes()
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
            if self.silence_start_time is None:
                self.silence_start_time = current_time
            elif current_time - self.silence_start_time > self.silence_threshold:
                # 静音超过阈值
                self.silence_events += 1
                self.logger.debug(f"静音结束事件 #{self.silence_events}")
                
                try:
                    self.audio_queue.put_nowait(('silence_end', None))
                except asyncio.QueueFull:
                    pass
                
                if self.silence_end_callback:
                    try:
                        self.silence_end_callback()
                    except Exception as e:
                        self.logger.error(f"静音结束回调错误: {e}")
                
                self.silence_start_time = None
    
    def _sounddevice_callback(self, indata, frames, time, status):
        """sounddevice音频回调"""
        if status:
            self.logger.debug(f"音频状态: {status}")
        
        if self.is_running:
            try:
                # 转换为16位PCM
                audio_data = (indata.flatten() * 32767).astype(np.int16)
                
                # 重采样到目标采样率
                if self.resample_ratio != 1.0:
                    # 使用scipy进行重采样
                    num_samples = int(len(audio_data) * self.resample_ratio)
                    resampled_data = scipy.signal.resample(audio_data, num_samples).astype(np.int16)
                    audio_data = resampled_data
                
                # 验证音频数据
                if len(audio_data) >= 64:
                    self._process_audio_chunk(audio_data)
                    self.bytes_received += len(audio_data) * 2
                    self.chunks_received += 1
                    
            except Exception as e:
                self.logger.error(f"sounddevice回调错误: {e}")
    
    def _pulseaudio_thread(self):
        """PulseAudio音频线程"""
        self.logger.info("启动PulseAudio音频线程")
        
        try:
            # 构建parec命令
            cmd = [
                'parec',
                '--device', self.pulse_source,
                '--format', 's16le',
                '--rate', str(self.sample_rate),
                '--channels', '1',
                '--raw'
            ]
            
            # 启动parec进程
            self.parec_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy(),
                bufsize=0
            )
            
            chunk_bytes = self.chunk_size * 2  # 16-bit = 2 bytes
            
            while self.is_running and self.parec_process.poll() is None:
                try:
                    ready, _, _ = select.select([self.parec_process.stdout], [], [], 0.1)
                    
                    if ready:
                        chunk = self.parec_process.stdout.read(chunk_bytes)
                        
                        if chunk and len(chunk) == chunk_bytes:
                            # 转换为numpy数组
                            audio_data = np.frombuffer(chunk, dtype=np.int16)
                            self._process_audio_chunk(audio_data)
                            self.bytes_received += len(chunk)
                            self.chunks_received += 1
                        
                except Exception as e:
                    self.logger.error(f"PulseAudio线程错误: {e}")
                    break
            
            # 清理进程
            if self.parec_process:
                self.parec_process.terminate()
                self.parec_process = None
            
        except Exception as e:
            self.logger.error(f"PulseAudio线程启动失败: {e}")
    
    
    def set_event_callbacks(self, 
                          speech_start: Optional[Callable] = None,
                          speech_end: Optional[Callable] = None,
                          silence_end: Optional[Callable] = None):
        """设置事件回调函数"""
        self.speech_start_callback = speech_start
        self.speech_end_callback = speech_end
        self.silence_end_callback = silence_end
    
    async def start_recording(self):
        """开始录音"""
        if self.is_running:
            self.logger.warning("麦克风已在录音")
            return
        
        if self.audio_source is None:
            raise RuntimeError("无可用音频源，无法启动录音")
        
        self.is_running = True
        self.start_time = time.time()
        
        try:
            if self.audio_source == "sounddevice":
                # 使用sounddevice - 使用硬件采样率
                hardware_chunk_size = int(self.chunk_size / self.resample_ratio) if self.resample_ratio != 1.0 else self.chunk_size
                
                self.audio_stream = sd.InputStream(
                    samplerate=self.hardware_sample_rate,
                    channels=1,
                    dtype=np.float32,
                    blocksize=hardware_chunk_size,
                    callback=self._sounddevice_callback,
                    device=self.input_device
                )
                self.audio_stream.start()
                self.logger.info("sounddevice录音已启动")
                
            elif self.audio_source == "pulseaudio":
                # 使用PulseAudio
                self.audio_thread = threading.Thread(target=self._pulseaudio_thread)
                self.audio_thread.daemon = True
                self.audio_thread.start()
                self.logger.info("PulseAudio录音已启动")
                
            else:
                raise RuntimeError(f"不支持的音频源: {self.audio_source}")
            
            self.logger.info(f"智能麦克风录音启动: {self.target_sample_rate}Hz, VAD阈值={self.speech_threshold}")
            
        except Exception as e:
            self.logger.error(f"启动录音失败: {e}")
            self.is_running = False
            raise
    
    async def stop_recording(self):
        """停止录音"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # 停止音频流
        if hasattr(self, 'audio_stream') and self.audio_stream:
            try:
                self.audio_stream.stop()
                self.audio_stream.close()
            except Exception as e:
                self.logger.debug(f"停止音频流错误: {e}")
        
        # 停止音频线程
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=2)
        
        # 清理进程
        if hasattr(self, 'parec_process') and self.parec_process:
            try:
                self.parec_process.terminate()
                self.parec_process.wait(timeout=2)
            except Exception:
                pass
        
        # 清空队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        self.logger.info("智能麦克风录音已停止")
    
    async def get_audio_event(self) -> Optional[Tuple[str, Optional[bytes]]]:
        """
        获取音频事件
        
        Returns:
            tuple: (事件类型, 数据)
            - ('audio', bytes): 音频数据
            - ('silence_end', None): 静音结束事件
        """
        try:
            return await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        uptime = time.time() - self.start_time if self.start_time else 0
        return {
            "audio_source": self.audio_source,
            "is_running": self.is_running,
            "sample_rate": self.target_sample_rate,
            "hardware_sample_rate": self.hardware_sample_rate,
            "resample_ratio": self.resample_ratio,
            "bytes_received": self.bytes_received,
            "chunks_received": self.chunks_received,
            "speech_events": self.speech_events,
            "silence_events": self.silence_events,
            "queue_size": self.audio_queue.qsize(),
            "uptime_seconds": uptime,
            "bytes_per_second": self.bytes_received / uptime if uptime > 0 else 0
        }


