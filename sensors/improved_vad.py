#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改进的VAD实现 - 解决音频分割问题
通过语音片段缓冲和智能合并，确保完整语句的连续性
"""

import asyncio
import logging
import time
import threading
from typing import Optional, Tuple, Callable, List
import numpy as np
import sounddevice as sd
import subprocess
import select
import os
import scipy.signal


class ImprovedVAD:
    """
    改进的语音活动检测，解决音频分割问题
    
    主要改进：
    1. 语音片段缓冲机制
    2. 智能语句结束检测
    3. 自适应超时调整
    4. 更稳定的VAD算法
    """
    
    def __init__(self, 
                 sample_rate: int = 16000,
                 chunk_size: int = 1024,
                 speech_timeout: float = 2.0,  # 语音结束超时
                 min_speech_duration: float = 0.3,  # 最小语音长度
                 speech_threshold: float = 100):
        """
        初始化改进的VAD
        
        Args:
            sample_rate: 采样率
            chunk_size: 音频块大小
            speech_timeout: 语音结束超时时间（秒）
            min_speech_duration: 最小语音持续时间（秒）
            speech_threshold: 语音检测阈值
        """
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        self.speech_timeout = speech_timeout
        self.min_speech_duration = min_speech_duration
        self.speech_threshold = speech_threshold
        
        # 硬件采样率检测
        self.hardware_sample_rate = None
        self.resample_ratio = None
        self.input_device = None
        
        # 音频流和队列
        self.audio_queue = asyncio.Queue(maxsize=100)
        self.is_running = False
        self.audio_source = None
        self.audio_thread = None
        
        # 改进的VAD状态
        self.speech_buffer = []  # 语音数据缓冲
        self.last_speech_time = 0  # 最后检测到语音的时间
        self.speech_start_time = 0  # 语音开始时间
        self.is_in_speech = False  # 是否在语音状态中
        
        # VAD算法参数
        self.energy_history = []
        self.energy_window_size = 50  # 能量历史窗口大小
        
        # 事件回调
        self.speech_start_callback: Optional[Callable] = None
        self.complete_utterance_callback: Optional[Callable[[bytes, float], None]] = None
        
        # 统计信息
        self.utterance_count = 0
        self.total_speech_duration = 0
        
        # 日志
        self.logger = logging.getLogger(__name__)
        
        # 初始化音频源
        self._initialize_audio_source()
    
    def _initialize_audio_source(self):
        """初始化音频源"""
        if self._try_sounddevice():
            self.audio_source = "sounddevice"
            self.logger.info("使用sounddevice作为音频源")
        elif self._try_pulseaudio():
            if self._test_pulseaudio_recording():
                self.audio_source = "pulseaudio"
                self.logger.info("使用PulseAudio作为音频源")
            else:
                self.audio_source = None
                self.logger.error("PulseAudio不可用")
        else:
            self.audio_source = None
            self.logger.error("无可用音频源")
    
    def _try_sounddevice(self) -> bool:
        """尝试使用sounddevice"""
        try:
            devices = sd.query_devices()
            for device_id, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    test_rates = [self.sample_rate, 48000, 44100, 22050]
                    
                    for test_rate in test_rates:
                        try:
                            sd.check_input_settings(
                                device=device_id,
                                samplerate=test_rate,
                                channels=1
                            )
                            self.input_device = device_id
                            self.hardware_sample_rate = test_rate
                            
                            if test_rate != self.sample_rate:
                                self.resample_ratio = self.sample_rate / test_rate
                                self.logger.info(f"音频设备: [{device_id}] {device['name']}")
                                self.logger.info(f"硬件采样率: {test_rate}Hz, 目标: {self.sample_rate}Hz")
                                self.logger.info(f"重采样比例: {self.resample_ratio:.3f}")
                            else:
                                self.resample_ratio = 1.0
                                self.logger.info(f"音频设备: [{device_id}] {device['name']}")
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
            result = subprocess.run(['which', 'pactl'], capture_output=True, text=True)
            if result.returncode != 0:
                return False
            
            result = subprocess.run(['pactl', 'list', 'short', 'sources'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return False
            
            for line in result.stdout.strip().split('\n'):
                if line.strip() and '.monitor' not in line:
                    parts = line.split('\t')
                    if len(parts) >= 2:
                        self.pulse_source = parts[1]
                        self.logger.info(f"PulseAudio源: {self.pulse_source}")
                        return True
            
            return False
        except Exception as e:
            self.logger.debug(f"PulseAudio初始化失败: {e}")
            return False
    
    def _test_pulseaudio_recording(self) -> bool:
        """测试PulseAudio录音"""
        try:
            result = subprocess.run(['pactl', 'list', 'short', 'sources'], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode != 0:
                return False
            
            for line in result.stdout.strip().split('\n'):
                if self.pulse_source in line and 'SUSPENDED' in line:
                    self.logger.debug(f"PulseAudio源 {self.pulse_source} 处于SUSPENDED状态")
                    return False
            
            return True
        except Exception as e:
            self.logger.debug(f"PulseAudio测试失败: {e}")
            return False
    
    def _detect_speech_activity(self, audio_data: np.ndarray) -> bool:
        """改进的语音活动检测"""
        # 计算RMS能量
        energy = np.sqrt(np.mean(audio_data.astype(np.float32) ** 2))
        
        # 更新能量历史
        self.energy_history.append(energy)
        if len(self.energy_history) > self.energy_window_size:
            self.energy_history.pop(0)
        
        # 动态阈值计算
        if len(self.energy_history) >= 10:
            median_energy = np.median(self.energy_history)
            percentile_75 = np.percentile(self.energy_history, 75)
            
            # 使用更稳定的阈值策略
            base_threshold = max(800, percentile_75 * 1.3)
            
            # 如果正在语音中，降低阈值以保持连续性
            if self.is_in_speech:
                adaptive_threshold = base_threshold * 0.7  # 降低30%
            else:
                adaptive_threshold = base_threshold
        else:
            adaptive_threshold = 900  # 初始阈值
        
        is_speech = energy > adaptive_threshold
        
        # 调试输出（降低频率）
        if len(self.energy_history) % 30 == 0:
            self.logger.debug(f"VAD: 能量={energy:.1f}, 阈值={adaptive_threshold:.1f}, "
                           f"检测={'语音' if is_speech else '静音'}, 状态={'进行中' if self.is_in_speech else '等待'}")
        
        return is_speech
    
    def _process_audio_chunk(self, audio_data: np.ndarray):
        """改进的音频块处理"""
        has_speech = self._detect_speech_activity(audio_data)
        current_time = time.time()
        
        if has_speech:
            # 检测到语音
            if not self.is_in_speech:
                # 语音开始
                self.is_in_speech = True
                self.speech_start_time = current_time
                self.speech_buffer.clear()
                
                self.logger.debug("🎤 语音开始")
                if self.speech_start_callback:
                    try:
                        self.speech_start_callback()
                    except Exception as e:
                        self.logger.error(f"语音开始回调错误: {e}")
            
            # 累积语音数据
            self.speech_buffer.append(audio_data.tobytes())
            self.last_speech_time = current_time
            
        else:
            # 检测到静音
            if self.is_in_speech:
                # 检查是否应该结束语音
                silence_duration = current_time - self.last_speech_time
                
                if silence_duration > self.speech_timeout:
                    # 语音结束
                    self._finalize_utterance(current_time)
    
    def _finalize_utterance(self, current_time: float):
        """完成语句处理"""
        if not self.speech_buffer:
            return
        
        # 计算语音持续时间
        speech_duration = current_time - self.speech_start_time
        
        # 检查最小语音长度
        if speech_duration < self.min_speech_duration:
            self.logger.debug(f"语音太短 ({speech_duration:.2f}s)，忽略")
            self.speech_buffer.clear()
            self.is_in_speech = False
            return
        
        # 合并音频数据
        complete_audio = b''.join(self.speech_buffer)
        
        # 统计信息
        self.utterance_count += 1
        self.total_speech_duration += speech_duration
        
        self.logger.info(f"🤫 语音结束 #{self.utterance_count}: "
                        f"时长={speech_duration:.2f}s, "
                        f"大小={len(complete_audio)/1024:.1f}KB")
        
        # 触发完整语句回调
        if self.complete_utterance_callback:
            try:
                self.complete_utterance_callback(complete_audio, speech_duration)
            except Exception as e:
                self.logger.error(f"完整语句回调错误: {e}")
        
        # 重置状态
        self.speech_buffer.clear()
        self.is_in_speech = False
    
    def _sounddevice_callback(self, indata, frames, time, status):
        """sounddevice音频回调"""
        if status:
            self.logger.debug(f"音频状态: {status}")
        
        if self.is_running:
            try:
                # 转换为16位PCM
                audio_data = (indata.flatten() * 32767).astype(np.int16)
                
                # 重采样
                if self.resample_ratio != 1.0:
                    num_samples = int(len(audio_data) * self.resample_ratio)
                    resampled_data = scipy.signal.resample(audio_data, num_samples).astype(np.int16)
                    audio_data = resampled_data
                
                # 处理音频块
                if len(audio_data) >= 64:
                    self._process_audio_chunk(audio_data)
                    
            except Exception as e:
                self.logger.error(f"sounddevice回调错误: {e}")
    
    def _pulseaudio_thread(self):
        """PulseAudio音频线程"""
        self.logger.info("启动PulseAudio音频线程")
        
        try:
            cmd = [
                'parec',
                '--device', self.pulse_source,
                '--format', 's16le',
                '--rate', str(self.sample_rate),
                '--channels', '1',
                '--raw'
            ]
            
            self.parec_process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=os.environ.copy(),
                bufsize=0
            )
            
            chunk_bytes = self.chunk_size * 2
            
            while self.is_running and self.parec_process.poll() is None:
                try:
                    ready, _, _ = select.select([self.parec_process.stdout], [], [], 0.1)
                    
                    if ready:
                        chunk = self.parec_process.stdout.read(chunk_bytes)
                        
                        if chunk and len(chunk) == chunk_bytes:
                            audio_data = np.frombuffer(chunk, dtype=np.int16)
                            self._process_audio_chunk(audio_data)
                        
                except Exception as e:
                    self.logger.error(f"PulseAudio线程错误: {e}")
                    break
            
            if self.parec_process:
                self.parec_process.terminate()
                self.parec_process = None
            
        except Exception as e:
            self.logger.error(f"PulseAudio线程启动失败: {e}")
    
    def set_callbacks(self, 
                     speech_start: Optional[Callable] = None,
                     complete_utterance: Optional[Callable[[bytes, float], None]] = None):
        """设置事件回调"""
        self.speech_start_callback = speech_start
        self.complete_utterance_callback = complete_utterance
    
    async def start_recording(self):
        """开始录音"""
        if self.is_running:
            self.logger.warning("已在录音中")
            return
        
        if self.audio_source is None:
            raise RuntimeError("无可用音频源")
        
        self.is_running = True
        
        try:
            if self.audio_source == "sounddevice":
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
                self.audio_thread = threading.Thread(target=self._pulseaudio_thread)
                self.audio_thread.daemon = True
                self.audio_thread.start()
                self.logger.info("PulseAudio录音已启动")
            
            self.logger.info(f"改进VAD录音启动: {self.sample_rate}Hz, "
                           f"语音超时={self.speech_timeout}s, "
                           f"最小时长={self.min_speech_duration}s")
            
        except Exception as e:
            self.logger.error(f"启动录音失败: {e}")
            self.is_running = False
            raise
    
    async def stop_recording(self):
        """停止录音"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # 如果正在语音中，强制结束
        if self.is_in_speech:
            self._finalize_utterance(time.time())
        
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
        
        self.logger.info("改进VAD录音已停止")
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "audio_source": self.audio_source,
            "is_running": self.is_running,
            "sample_rate": self.sample_rate,
            "hardware_sample_rate": self.hardware_sample_rate,
            "resample_ratio": self.resample_ratio,
            "utterance_count": self.utterance_count,
            "total_speech_duration": self.total_speech_duration,
            "average_utterance_length": (self.total_speech_duration / self.utterance_count 
                                       if self.utterance_count > 0 else 0),
            "is_in_speech": self.is_in_speech,
            "speech_buffer_size": len(self.speech_buffer),
            "energy_history_size": len(self.energy_history)
        }