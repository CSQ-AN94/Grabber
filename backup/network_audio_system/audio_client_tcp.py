#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
笔记本端TCP音频客户端 - [修正版]
此版本仅作为纯粹的麦克风音频发送器。
它捕获本地麦克风的音频，并通过TCP发送给Jetson上的服务。
"""

import socket
import numpy as np
import sounddevice as sd
import threading
import time
import argparse
import logging

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TCPAudioClient:
    """
    TCP音频客户端 (仅发送)
    与Jetson上的MicrophoneThread配套工作。
    """
    
    def __init__(self, jetson_host: str, mic_port: int = 8888):
        """
        初始化TCP音频客户端
        
        Args:
            jetson_host: Jetson IP地址
            mic_port: 麦克风服务端口 (固定为8888)
        """
        self.jetson_host = jetson_host
        self.mic_port = mic_port
        
        # 音频参数（与Gemini Agent的MicrophoneThread保持一致）
        self.sample_rate = 16000
        self.channels = 1
        self.dtype = np.int16
        self.chunk_size = 1024
        
        self.input_device = None
        self.mic_socket = None
        self.input_stream = None
        self.is_running = False
        self.bytes_sent = 0
        
    def find_audio_devices(self):
        """查找并选择最佳的音频输入设备"""
        try:
            devices = sd.query_devices()
            logger.info("可用的音频输入设备:")
            input_devices = [(i, dev['name']) for i, dev in enumerate(devices) if dev['max_input_channels'] > 0]
            
            for i, name in input_devices:
                logger.info(f"  ID {i}: {name}")

            # 简单的设备选择逻辑
            self.input_device = sd.default.device[0]
            logger.info(f"已选择默认输入设备: ID {self.input_device} ({sd.query_devices(self.input_device)['name']})")
            return True
            
        except Exception as e:
            logger.error(f"音频设备查找失败: {e}")
            return False
    
    def connect_to_jetson(self):
        """连接到Jetson上的麦克风服务"""
        try:
            logger.info(f"连接到Jetson麦克风服务: {self.jetson_host}:{self.mic_port}")
            self.mic_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.mic_socket.connect((self.jetson_host, self.mic_port))
            logger.info("✅ 麦克风服务连接成功")
            return True
        except Exception as e:
            logger.error(f"连接Jetson失败: {e}")
            self.disconnect()
            return False
    
    def disconnect(self):
        """断开连接"""
        self.is_running = False
        if self.mic_socket:
            try:
                self.mic_socket.close()
            except:
                pass
            self.mic_socket = None
        logger.info("已断开连接")
    
    def _audio_input_callback(self, indata, frames, time, status):
        """音频输入回调函数，用于捕获并发送数据"""
        if status:
            logger.warning(f"音频输入状态警告: {status}")
        
        if self.is_running and self.mic_socket:
            try:
                # 将音频数据转换为bytes并发送
                audio_bytes = indata.astype(self.dtype).tobytes()
                self.mic_socket.sendall(audio_bytes)
                self.bytes_sent += len(audio_bytes)
            except Exception as e:
                logger.error(f"发送音频数据失败: {e}")
                self.is_running = False
    
    def start_audio_stream(self):
        """启动音频流"""
        try:
            self.input_stream = sd.InputStream(
                device=self.input_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                dtype=np.float32, # sounddevice 使用 float32
                callback=self._audio_input_callback
            )
            self.input_stream.start()
            logger.info("音频流启动，正在捕获麦克风...")
            return True
        except Exception as e:
            logger.error(f"启动音频流失败: {e}")
            return False
    
    def stop_audio_stream(self):
        """停止音频流"""
        if self.input_stream:
            try:
                self.input_stream.stop()
                self.input_stream.close()
            except Exception as e:
                logger.error(f"停止音频流时出错: {e}")
            self.input_stream = None
            logger.info("音频流已停止")
    
    def start(self):
        """启动客户端"""
        if not self.find_audio_devices():
            return False
        if not self.connect_to_jetson():
            return False
        if not self.start_audio_stream():
            return False
        
        self.is_running = True
        logger.info("✅ TCP音频客户端启动成功，正在发送音频...")
        return True
    
    def stop(self):
        """停止客户端"""
        logger.info("正在停止TCP音频客户端...")
        self.is_running = False
        self.stop_audio_stream()
        self.disconnect()
        logger.info("TCP音频客户端已停止")

def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="TCP音频客户端 (仅发送)")
    parser.add_argument("--host", required=True, help="Jetson主机地址")
    parser.add_argument("--mic-port", type=int, default=8888, help="麦克风服务端口")
    parser.add_argument("--list-devices", action="store_true", help="列出可用音频设备并退出")
    
    args = parser.parse_args()
    
    if args.list_devices:
        try:
            print("可用的音频设备:")
            devices = sd.query_devices()
            for i, device in enumerate(devices):
                print(f"  ID {i}: {device['name']} (输入: {device['max_input_channels']}, 输出: {device['max_output_channels']})")
        except Exception as e:
            print(f"列出设备失败: {e}")
        return
    
    client = TCPAudioClient(args.host, args.mic_port)
    
    try:
        if not client.start():
            logger.error("无法启动客户端")
            return
        
        # 保持运���并显示统计信息
        while True:
            time.sleep(5)
            logger.info(f"已发送 {client.bytes_sent / 1024:.2f} KB")
            
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        client.stop()

if __name__ == "__main__":
    main()
