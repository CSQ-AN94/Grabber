#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Jetson端TCP音频服务器
基于microphone_thread.py和speaker_thread.py
集成Live API和TTS系统
"""

import asyncio
import logging
import sys
import os
import time
import argparse

# 添加项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from intelligence.speech import TTSSystem
from sensors.microphone_thread import MicrophoneThread
from sensors.speaker_thread import SpeakerThread
# from intelligence.gemini_agent import GeminiAgent  # 待实现

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class MockLiveAPI:
    """
    Mock Live API类
    临时替代真实的Gemini Live API，用于测试音频流
    """
    
    def __init__(self):
        self.is_active = False
        self.response_count = 0
        
    async def process_audio(self, audio_data):
        """
        处理音频数据并返回文本回复
        
        Args:
            audio_data: 音频数据（bytes）
            
        Returns:
            dict: {"text": "回复文本", "confidence": 0.95}
        """
        # 模拟处理延迟
        await asyncio.sleep(0.2)  # 200ms模拟Live API延迟
        
        # 模拟语音识别和回复
        self.response_count += 1
        responses = [
            f"收到第{self.response_count}段音频，音频长度{len(audio_data)}字节。",
            f"音频流连接正常，这是第{self.response_count}次回复。",
            f"系统运行良好，正在处理第{self.response_count}个音频块。",
            f"Live API模拟正常，延迟测试进行中。回复序号{self.response_count}。",
            f"音频处理链路已打通，这是测试回复{self.response_count}。"
        ]
        
        import random
        response_text = random.choice(responses)
        
        return {
            "text": response_text,
            "confidence": 0.95,
            "processing_time": 0.2
        }


class TCPAudioServer:
    """
    TCP音频服务器类
    集成MicrophoneThread、SpeakerThread、Live API和TTS系统
    """
    
    def __init__(self, mic_port=9888, speaker_port=9889, config_path="config.ini"):
        """
        初始化TCP音频服务器
        
        Args:
            mic_port: 麦克风端口
            speaker_port: 扬声器端口
            config_path: 配置文件路径
        """
        self.mic_port = mic_port
        self.speaker_port = speaker_port
        
        # 加载配置
        try:
            self.config = load_config(config_path)
        except Exception as e:
            logger.error(f"加载配置失败: {e}")
            self.config = {}
        
        # 初始化组件
        self.microphone = None
        self.speaker = None
        self.tts_system = None
        self.live_api = MockLiveAPI()  # 临时使用Mock
        
        # 状态管理
        self.is_running = False
        self.processing_task = None
        
        # 统计信息
        self.audio_chunks_processed = 0
        self.responses_generated = 0
        
        self._initialize_components()
    
    def _initialize_components(self):
        """初始化系统组件"""
        try:
            # 初始化麦克风线程
            logger.info("初始化麦克风线程...")
            self.microphone = MicrophoneThread(
                port=self.mic_port,
                sample_rate=16000,
                chunk_size=1024
            )
            
            # 初始化扬声器线程
            logger.info("初始化扬声器线程...")
            self.speaker = SpeakerThread(
                port=self.speaker_port,
                sample_rate=16000,
                chunk_size=1024
            )
            
            # 初始化TTS系统
            logger.info("初始化TTS系统...")
            tts_config = self.config.get('TTS', {})
            self.tts_system = TTSSystem(tts_config)
            
            # TODO: 初始化真实的Live API
            # self.live_api = GeminiAgent(...)
            
            logger.info("系统组件初始化完成")
            
        except Exception as e:
            logger.error(f"组件初始化失败: {e}")
            raise
    
    async def start_server(self):
        """启动服务器"""
        logger.info("启动TCP音频服务器...")
        
        try:
            # 启动麦克风线程
            self.microphone.start()
            
            # 启动扬声器线程
            self.speaker.start()
            
            # 设置运行状态
            self.is_running = True
            
            # 启动音频处理任务
            self.processing_task = asyncio.create_task(self._audio_processing_loop())
            
            logger.info("TCP音频服务器启动成功")
            logger.info(f"麦克风端口: {self.mic_port}")
            logger.info(f"扬声器端口: {self.speaker_port}")
            logger.info("等待客户端连接...")
            
            # 等待处理任务完成
            await self.processing_task
            
        except Exception as e:
            logger.error(f"启动服务器失败: {e}")
            raise
    
    async def _audio_processing_loop(self):
        """音频处理主循环"""
        logger.info("音频处理循环启动")
        
        last_stats_time = time.time()
        
        while self.is_running:
            try:
                # 获取音频数据
                audio_chunk = await self.microphone.get_audio_chunk()
                
                if audio_chunk:
                    # 处理音频数据
                    await self._process_audio_chunk(audio_chunk)
                    self.audio_chunks_processed += 1
                    
                    # 定期输出统计信息
                    now = time.time()
                    if now - last_stats_time >= 10:  # 每10秒输出一次
                        await self._log_statistics()
                        last_stats_time = now
                else:
                    # 没有音频数据，短暂休眠
                    await asyncio.sleep(0.01)
                
            except Exception as e:
                logger.error(f"音频处理循环错误: {e}")
                await asyncio.sleep(0.1)
        
        logger.info("音频处理循环结束")
    
    async def _process_audio_chunk(self, audio_chunk):
        """
        处理单个音频块
        
        Args:
            audio_chunk: 音频数据块（bytes）
        """
        try:
            # 记录处理开始时间
            start_time = time.time()
            
            # 使用Live API处理音频
            api_response = await self.live_api.process_audio(audio_chunk)
            api_time = time.time() - start_time
            
            if api_response and api_response.get("text"):
                response_text = api_response["text"]
                logger.info(f"Live API响应: {response_text[:100]}...")
                logger.debug(f"Live API处理时间: {api_time*1000:.1f}ms")
                
                # 文本转语音
                tts_start = time.time()
                audio_output = await self._text_to_speech(response_text)
                tts_time = time.time() - tts_start
                
                if audio_output:
                    # 发送音频到扬声器
                    await self.speaker.put_audio_chunk(audio_output)
                    self.responses_generated += 1
                    
                    logger.debug(f"TTS处理时间: {tts_time*1000:.1f}ms")
                    logger.debug(f"总处理时间: {(time.time() - start_time)*1000:.1f}ms")
                else:
                    logger.warning("TTS合成失败")
            else:
                logger.debug("Live API无响应")
                
        except Exception as e:
            logger.error(f"音频块处理失败: {e}")
    
    async def _text_to_speech(self, text):
        """
        文本转语音
        
        Args:
            text: 要转换的文本
            
        Returns:
            bytes: 音频数据（16kHz, 16bit, 单声道）
        """
        try:
            # 调用TTS系统
            audio_data = await self.tts_system.synthesize_async(text)
            
            if audio_data:
                # 确保音频格式正确
                return self._convert_audio_format(audio_data)
            else:
                logger.warning("TTS合成返回空数据")
                return None
                
        except Exception as e:
            logger.error(f"TTS处理失败: {e}")
            return None
    
    def _convert_audio_format(self, audio_data):
        """
        转换音频格式到目标格式
        
        Args:
            audio_data: 原始音频数据
            
        Returns:
            bytes: 转换后的音频数据（16kHz, 16bit, 单声道）
        """
        try:
            import numpy as np
            
            # 处理不同的输入格式
            if isinstance(audio_data, bytes):
                return audio_data
            elif isinstance(audio_data, np.ndarray):
                # 确保是单声道
                if len(audio_data.shape) > 1:
                    audio_data = audio_data[:, 0]
                
                # 转换为int16
                if audio_data.dtype == np.float32 or audio_data.dtype == np.float64:
                    audio_data = (audio_data * 32767).astype(np.int16)
                elif audio_data.dtype != np.int16:
                    audio_data = audio_data.astype(np.int16)
                
                return audio_data.tobytes()
            else:
                logger.error(f"未知音频数据格式: {type(audio_data)}")
                return None
                
        except Exception as e:
            logger.error(f"音频格式转换失败: {e}")
            return None
    
    async def _log_statistics(self):
        """输出统计信息"""
        try:
            mic_stats = self.microphone.get_stats()
            speaker_stats = self.speaker.get_stats()
            
            logger.info("=" * 50)
            logger.info("系统统计信息:")
            logger.info(f"  音频块处理: {self.audio_chunks_processed}")
            logger.info(f"  响应生成: {self.responses_generated}")
            logger.info(f"  麦克风状态: {mic_stats}")
            logger.info(f"  扬声器状态: {speaker_stats}")
            logger.info("=" * 50)
            
        except Exception as e:
            logger.error(f"统计信息输出失败: {e}")
    
    def stop_server(self):
        """停止服务器"""
        logger.info("正在停止TCP音频服务器...")
        
        # 设置停止标志
        self.is_running = False
        
        # 取消处理任务
        if self.processing_task and not self.processing_task.done():
            self.processing_task.cancel()
        
        # 停止麦克风线程
        if self.microphone:
            self.microphone.stop()
        
        # 停止扬声器线程
        if self.speaker:
            self.speaker.stop()
        
        logger.info("TCP音频服务器已停止")
    
    def get_server_stats(self):
        """获取服务器统计信息"""
        stats = {
            "is_running": self.is_running,
            "audio_chunks_processed": self.audio_chunks_processed,
            "responses_generated": self.responses_generated,
            "mic_port": self.mic_port,
            "speaker_port": self.speaker_port
        }
        
        if self.microphone:
            stats["microphone"] = self.microphone.get_stats()
        
        if self.speaker:
            stats["speaker"] = self.speaker.get_stats()
        
        return stats


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="TCP音频服务器")
    parser.add_argument("--mic-port", type=int, default=9888, help="麦克风端口")
    parser.add_argument("--speaker-port", type=int, default=9889, help="扬声器端口")
    parser.add_argument("--config", default="config.ini", help="配置文件路径")
    
    args = parser.parse_args()
    
    # 创建服务器
    server = TCPAudioServer(args.mic_port, args.speaker_port, args.config)
    
    try:
        # 启动服务器
        await server.start_server()
        
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"服务器错误: {e}")
    finally:
        server.stop_server()


if __name__ == "__main__":
    asyncio.run(main())