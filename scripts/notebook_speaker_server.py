#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
笔记本端扬声器服务器
在笔记本上运行此脚本，接收来自Jetson的音频数据并播放
"""

import socket
import threading
import logging
import time
import wave
import tempfile
import os
import argparse
try:
    import sounddevice as sd
    import numpy as np
    SOUNDDEVICE_AVAILABLE = True
except ImportError:
    SOUNDDEVICE_AVAILABLE = False
    print("警告: sounddevice未安装，将尝试使用系统播放器")

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class NotebookSpeakerServer:
    """笔记本扬声器服务器，接收并播放来自Jetson的音频"""
    
    def __init__(self, port: int = 9889):
        self.port = port
        self.is_running = False
        self.server_socket = None
        self.bytes_received = 0
        self.audio_count = 0
        
    def _play_audio_with_sounddevice(self, audio_data: bytes):
        """使用sounddevice播放音频"""
        try:
            # 将PCM数据转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            # 转换为float32格式 (sounddevice要求)
            audio_float = audio_array.astype(np.float32) / 32768.0
            
            # 播放音频
            sd.play(audio_float, samplerate=16000, blocking=True)
            logger.info(f"✅ 播放音频完成: {len(audio_data)} 字节")
            
        except Exception as e:
            logger.error(f"sounddevice播放失败: {e}")
            return False
        return True
    
    def _play_audio_with_system(self, audio_data: bytes):
        """使用系统播放器播放音频"""
        try:
            # 创建临时WAV文件
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                # 写入WAV头部
                with wave.open(tmp_file.name, 'wb') as wav_file:
                    wav_file.setnchannels(1)  # 单声道
                    wav_file.setsampwidth(2)  # 16位 = 2字节
                    wav_file.setframerate(16000)  # 16kHz
                    wav_file.writeframes(audio_data)
                
                # 尝试播放
                import subprocess
                players = ['aplay', 'paplay', 'play', 'afplay']  # afplay for macOS
                
                for player in players:
                    try:
                        result = subprocess.run(
                            [player, tmp_file.name],
                            capture_output=True,
                            timeout=10
                        )
                        if result.returncode == 0:
                            logger.info(f"✅ 使用{player}播放音频完成: {len(audio_data)} 字节")
                            return True
                    except (subprocess.TimeoutExpired, FileNotFoundError):
                        continue
                
                logger.error("所有系统播放器都失败了")
                return False
                
        except Exception as e:
            logger.error(f"系统播放器播放失败: {e}")
            return False
        finally:
            # 清理临时文件
            try:
                os.unlink(tmp_file.name)
            except:
                pass
    
    def _play_audio(self, audio_data: bytes):
        """播放音频数据"""
        if not audio_data:
            return
            
        # 优先使用sounddevice，否则使用系统播放器
        if SOUNDDEVICE_AVAILABLE:
            success = self._play_audio_with_sounddevice(audio_data)
        else:
            success = self._play_audio_with_system(audio_data)
            
        if success:
            self.audio_count += 1
    
    def _handle_client(self, client_socket, address):
        """处理客户端连接"""
        logger.info(f"新的音频连接来自: {address}")
        
        try:
            audio_buffer = b''
            
            while self.is_running:
                data = client_socket.recv(4096)
                if not data:
                    break
                    
                audio_buffer += data
                self.bytes_received += len(data)
                
                # 当接收到足够的数据时播放
                # 这里简单地每接收2048字节就播放一次
                if len(audio_buffer) >= 2048:
                    self._play_audio(audio_buffer)
                    audio_buffer = b''
                    
        except Exception as e:
            logger.error(f"处理客户端时出错: {e}")
        finally:
            # 播放剩余的音频
            if audio_buffer:
                self._play_audio(audio_buffer)
            client_socket.close()
            logger.info(f"客户端连接关闭: {address}")
    
    def start(self):
        """启动扬声器服务器"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(5)
            
            self.is_running = True
            logger.info(f"🔊 扬声器服务器启动，监听端口 {self.port}")
            logger.info("等待来自Jetson的音频连接...")
            
            while self.is_running:
                try:
                    client_socket, address = self.server_socket.accept()
                    # 为每个客户端创建新线程
                    client_thread = threading.Thread(
                        target=self._handle_client,
                        args=(client_socket, address)
                    )
                    client_thread.daemon = True
                    client_thread.start()
                    
                except Exception as e:
                    if self.is_running:
                        logger.error(f"接受连接时出错: {e}")
                        
        except Exception as e:
            logger.error(f"启动扬声器服务器失败: {e}")
        finally:
            self.stop()
    
    def stop(self):
        """停止扬声器服务器"""
        self.is_running = False
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
        logger.info(f"🔊 扬声器服务器已停止 (接收: {self.bytes_received/1024:.2f}KB, 播放: {self.audio_count}次)")


def main():
    parser = argparse.ArgumentParser(description="笔记本扬声器服务器")
    parser.add_argument("--port", type=int, default=9889, help="监听端口")
    parser.add_argument("--test-audio", action="store_true", help="测试音频播放功能")
    
    args = parser.parse_args()
    
    if args.test_audio:
        # 测试音频播放
        print("🔊 测试音频播放功能...")
        
        # 生成测试音频（1秒的440Hz正弦波）
        sample_rate = 16000
        duration = 1.0
        frequency = 440.0
        
        t = np.linspace(0, duration, int(sample_rate * duration))
        audio_data = np.sin(2 * np.pi * frequency * t)
        audio_int16 = (audio_data * 32767).astype(np.int16)
        
        server = NotebookSpeakerServer()
        server._play_audio(audio_int16.tobytes())
        print("✅ 音频测试完成")
        return
    
    server = NotebookSpeakerServer(port=args.port)
    
    try:
        server.start()
    except KeyboardInterrupt:
        logger.info("用户中断")
    finally:
        server.stop()


if __name__ == "__main__":
    main()