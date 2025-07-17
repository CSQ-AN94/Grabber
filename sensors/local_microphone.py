#!/usr/bin/env python3
"""
本地麦克风输入 - 替代网络音频输入
用于Gemini Live API的本地音频采集
"""

import asyncio
import logging
import time
from typing import Optional
import numpy as np
import sounddevice as sd


class LocalMicrophoneInput:
    """
    本地麦克风输入，直接从系统麦克风采集音频
    
    设计理念：
    1. 直接本地音频采集，无网络传输
    2. 固定16kHz单声道格式（Gemini Live API要求）
    3. 异步安全的音频队列
    4. 简单的本地音频处理
    """
    
    def __init__(self, sample_rate: int = 16000, chunk_size: int = 1024):
        """
        初始化本地麦克风输入
        
        Args:
            sample_rate: 采样率（固定16kHz for Gemini）
            chunk_size: 音频块大小
        """
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        
        # 音频流和队列
        self.audio_stream = None
        self.audio_queue = asyncio.Queue(maxsize=100)
        self.is_running = False
        
        # 日志
        self.logger = logging.getLogger(__name__)
        
        # 统计信息
        self.bytes_received = 0
        self.chunks_received = 0
        self.start_time = None
        
        # 配置最佳输入设备
        self._configure_input_device()
    
    def _configure_input_device(self):
        """配置最佳输入设备"""
        try:
            devices = sd.query_devices()
            
            # 寻找支持16000Hz的输入设备
            best_input_device = None
            
            for device_id, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    try:
                        sd.check_input_settings(device=device_id, samplerate=16000)
                        best_input_device = device_id
                        self.logger.info(f"选择输入设备: [{device_id}] {device['name']} @ 16000Hz")
                        break
                    except:
                        continue
            
            if best_input_device is None:
                self.logger.warning("未找到支持16000Hz的输入设备，使用默认设备")
                best_input_device = sd.default.device[0]
            
            self.input_device = best_input_device
            
        except Exception as e:
            self.logger.error(f"配置输入设备失败: {e}")
            self.input_device = sd.default.device[0]
        
    def _audio_callback(self, indata, frames, time, status):
        """音频输入回调函数"""
        if status:
            self.logger.warning(f"音频输入状态警告: {status}")
        
        if self.is_running:
            try:
                # 转换为16位PCM格式
                audio_data = (indata.flatten() * 32767).astype(np.int16)
                audio_bytes = audio_data.tobytes()
                
                # 验证音频数据
                if self._validate_audio_chunk(audio_bytes):
                    try:
                        # 非阻塞放入队列
                        self.audio_queue.put_nowait(audio_bytes)
                        self.bytes_received += len(audio_bytes)
                        self.chunks_received += 1
                    except asyncio.QueueFull:
                        # 队列满时，移除最老的块
                        try:
                            self.audio_queue.get_nowait()
                            self.audio_queue.put_nowait(audio_bytes)
                        except asyncio.QueueEmpty:
                            pass
                            
            except Exception as e:
                self.logger.error(f"音频回调错误: {e}")
    
    def _validate_audio_chunk(self, chunk: bytes) -> bool:
        """验证音频块"""
        # 检查长度
        if len(chunk) < 64 or len(chunk) % 2 != 0:
            return False
        
        # 检查是否为静音（可选）
        audio_data = np.frombuffer(chunk, dtype=np.int16)
        
        # 检查音频幅度（避免完全静音）
        max_amplitude = np.max(np.abs(audio_data))
        if max_amplitude < 10:  # 太小的音频可能是噪音
            return False
        
        return True
    
    async def start_recording(self):
        """开始录音"""
        if self.is_running:
            self.logger.warning("麦克风已在录音")
            return
        
        try:
            # 创建音频流
            self.audio_stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,  # 单声道
                dtype=np.float32,
                blocksize=self.chunk_size,
                callback=self._audio_callback,
                device=self.input_device
            )
            
            # 启动录音
            self.audio_stream.start()
            self.is_running = True
            self.start_time = time.time()
            
            self.logger.info(f"本地麦克风录音已启动")
            self.logger.info(f"音频格式: {self.sample_rate}Hz, 单声道, 16位PCM")
            
        except Exception as e:
            self.logger.error(f"启动麦克风录音失败: {e}")
            raise
    
    async def stop_recording(self):
        """停止录音"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # 停止音频流
        if self.audio_stream:
            try:
                self.audio_stream.stop()
                self.audio_stream.close()
            except Exception as e:
                self.logger.debug(f"停止音频流时出错: {e}")
            self.audio_stream = None
        
        # 清空音频队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        self.logger.info("本地麦克风录音已停止")
    
    async def get_audio_chunk(self) -> Optional[bytes]:
        """
        获取音频块（异步接口）
        
        Returns:
            bytes: 音频数据块，如果没有数据则返回None
        """
        try:
            return await asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            return None
    
    def is_audio_available(self) -> bool:
        """检查是否有音频数据可用"""
        return not self.audio_queue.empty()
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        uptime = time.time() - self.start_time if self.start_time else 0
        return {
            "is_running": self.is_running,
            "sample_rate": self.sample_rate,
            "bytes_received": self.bytes_received,
            "chunks_received": self.chunks_received,
            "queue_size": self.audio_queue.qsize(),
            "uptime_seconds": uptime,
            "bytes_per_second": self.bytes_received / uptime if uptime > 0 else 0
        }


# 测试函数
async def test_local_microphone():
    """测试本地麦克风输入"""
    logging.basicConfig(level=logging.INFO)
    
    mic = LocalMicrophoneInput()
    
    try:
        # 启动麦克风录音
        await mic.start_recording()
        
        print("本地麦克风录音已启动，开始接收音频数据...")
        print("请对着麦克风说话...")
        print("按Ctrl+C停止...")
        
        # 接收和处理音频数据
        chunk_count = 0
        while True:
            chunk = await mic.get_audio_chunk()
            if chunk:
                chunk_count += 1
                print(f"收到音频块 {chunk_count}: {len(chunk)} 字节")
                
                # 每50个块输出一次统计
                if chunk_count % 50 == 0:
                    stats = mic.get_stats()
                    print(f"统计: {stats}")
            
            await asyncio.sleep(0.01)
    
    except KeyboardInterrupt:
        print("\n停止测试...")
    
    finally:
        await mic.stop_recording()
        print("测试完成")


if __name__ == "__main__":
    asyncio.run(test_local_microphone())