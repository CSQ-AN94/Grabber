#!/usr/bin/env python3
"""
音频输出线程 - 与麦克风线程配套，将TTS音频发送到笔记本扬声器
"""

import asyncio
import logging
import socket
import threading
import time
from typing import Optional
import numpy as np


class SpeakerThread:
    """
    音频输出线程，将音频数据发送到网络客户端进行播放
    
    设计理念：
    1. 与MicrophoneThread配套使用
    2. 固定16kHz单声道格式（与输入保持一致）
    3. TCP原始音频数据传输（高效低延迟）
    4. 线程安全的音频队列
    """
    
    def __init__(self, port: int = 8889, sample_rate: int = 16000, chunk_size: int = 1024):
        """
        初始化音频输出线程
        
        Args:
            port: 监听端口（建议与MicrophoneThread使用不同端口）
            sample_rate: 采样率（固定16kHz）
            chunk_size: 音频块大小
        """
        self.port = port
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        
        # 线程和网络
        self.server_thread = None
        self.server_socket = None
        self.client_socket = None
        self.is_running = False
        
        # 音频队列
        self.audio_queue = asyncio.Queue(maxsize=100)
        
        # 日志
        self.logger = logging.getLogger(__name__)
        
        # 统计
        self.bytes_sent = 0
        self.chunks_sent = 0
        
    def start(self):
        """启动音频输出线程"""
        if self.is_running:
            self.logger.warning("音频输出线程已在运行")
            return
        
        self.is_running = True
        self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self.server_thread.start()
        
        self.logger.info(f"音频输出线程启动，监听端口: {self.port}")
        self.logger.info(f"音频格式: {self.sample_rate}Hz, 单声道, 16位PCM")
        self.logger.info(f"接收音频命令示例:")
        self.logger.info(f"  ffmpeg -f s16le -ar {self.sample_rate} -ac 1 -i tcp://localhost:{self.port} output.wav")
        self.logger.info(f"  或使用配套的音频客户端连接")
    
    def stop(self):
        """停止音频输出线程"""
        self.is_running = False
        
        # 关闭客户端连接
        if self.client_socket:
            try:
                self.client_socket.close()
            except:
                pass
            self.client_socket = None
        
        # 关闭服务器Socket
        if self.server_socket:
            try:
                self.server_socket.close()
            except:
                pass
            self.server_socket = None
        
        # 等待线程结束
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=2)
        
        self.logger.info("音频输出线程已停止")
    
    def _server_loop(self):
        """服务器主循环"""
        try:
            # 创建服务器Socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(1)
            self.server_socket.settimeout(1.0)  # 1秒超时用于检查停止信号
            
            self.logger.info(f"音频输出服务器监听中...")
            
            while self.is_running:
                try:
                    # 接受客户端连接
                    client_socket, addr = self.server_socket.accept()
                    self.logger.info(f"音频播放客户端连接: {addr}")
                    
                    # 处理客户端音频流
                    self._handle_client(client_socket)
                    
                except socket.timeout:
                    continue  # 超时继续检查停止信号
                except OSError:
                    if self.is_running:
                        self.logger.error("服务器Socket错误")
                    break
                except Exception as e:
                    if self.is_running:
                        self.logger.error(f"服务器循环错误: {e}")
                    break
        
        except Exception as e:
            self.logger.error(f"服务器启动失败: {e}")
        
        finally:
            if self.server_socket:
                try:
                    self.server_socket.close()
                except:
                    pass
    
    def _handle_client(self, client_socket):
        """处理客户端音频流"""
        self.client_socket = client_socket
        
        try:
            # 设置Socket为非阻塞（但用超时来控制）
            client_socket.settimeout(0.5)
            
            last_stats_time = time.time()
            
            while self.is_running:
                try:
                    # 从队列获取音频数据
                    try:
                        # 创建临时事件循环来获取数据
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        try:
                            chunk = loop.run_until_complete(
                                asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
                            )
                        except asyncio.TimeoutError:
                            chunk = None
                        finally:
                            loop.close()
                        
                        if chunk:
                            # 发送音频数据
                            client_socket.sendall(chunk)
                            self.bytes_sent += len(chunk)
                            self.chunks_sent += 1
                            
                            # 定期输出统计信息
                            now = time.time()
                            if now - last_stats_time >= 10:  # 每10秒输出一次
                                self.logger.info(f"音频输出统计: {self.bytes_sent} 字节, {self.chunks_sent} 块, 队列大小: {self.audio_queue.qsize()}")
                                last_stats_time = now
                    
                    except Exception as e:
                        self.logger.debug(f"获取音频数据失败: {e}")
                    
                    # 避免CPU占用过高
                    time.sleep(0.01)
                
                except ConnectionResetError:
                    self.logger.info("客户端重置连接")
                    break
                except BrokenPipeError:
                    self.logger.info("客户端断开连接")
                    break
                except Exception as e:
                    if self.is_running:
                        self.logger.error(f"发送音频数据错误: {e}")
                    break
        
        except Exception as e:
            self.logger.error(f"客户端处理错误: {e}")
        
        finally:
            try:
                client_socket.close()
            except:
                pass
            self.client_socket = None
            self.logger.info("客户端连接已关闭")
    
    async def put_audio_chunk(self, chunk: bytes):
        """
        放入音频块到队列（异步接口）
        
        Args:
            chunk: 音频数据块（16位PCM格式）
        """
        try:
            self.audio_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            # 队列满时，移除最老的块，添加新块
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.put_nowait(chunk)
                self.logger.debug("音频队列满，丢弃旧数据")
            except:
                self.logger.debug("无法添加音频数据到队列")
    
    def put_audio_chunk_sync(self, chunk: bytes):
        """
        放入音频块到队列（同步接口）
        
        Args:
            chunk: 音频数据块（16位PCM格式）
        """
        try:
            # 创建临时事件循环来放入数据
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                loop.run_until_complete(self.put_audio_chunk(chunk))
            finally:
                loop.close()
        except Exception as e:
            self.logger.debug(f"同步放入音频块失败: {e}")
    
    def put_audio_data(self, audio_data: np.ndarray):
        """
        放入音频数据（numpy数组格式）
        
        Args:
            audio_data: numpy音频数组（float32格式，范围-1.0到1.0）
        """
        try:
            # 转换为int16格式
            if audio_data.dtype == np.float32 or audio_data.dtype == np.float64:
                # 从float转换为int16
                audio_int16 = (audio_data * 32767).astype(np.int16)
            elif audio_data.dtype == np.int16:
                audio_int16 = audio_data
            else:
                self.logger.warning(f"不支持的音频数据格式: {audio_data.dtype}")
                return
            
            # 确保是单声道
            if len(audio_int16.shape) > 1:
                audio_int16 = audio_int16[:, 0]  # 取第一个声道
            
            # 转换为字节
            chunk = audio_int16.tobytes()
            self.put_audio_chunk_sync(chunk)
            
        except Exception as e:
            self.logger.error(f"音频数据转换失败: {e}")
    
    def is_client_connected(self) -> bool:
        """检查是否有客户端连接"""
        return self.client_socket is not None
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "is_running": self.is_running,
            "port": self.port,
            "bytes_sent": self.bytes_sent,
            "chunks_sent": self.chunks_sent,
            "queue_size": self.audio_queue.qsize(),
            "client_connected": self.client_socket is not None
        }


# 测试函数
async def test_speaker_thread():
    """测试音频输出线程"""
    logging.basicConfig(level=logging.INFO)
    
    speaker = SpeakerThread(port=8889)
    
    try:
        # 启动音频输出线程
        speaker.start()
        
        print("音频输出线程已启动，生成测试音频...")
        print("可以用以下命令接收音频:")
        print("  ffmpeg -f s16le -ar 16000 -ac 1 -i tcp://localhost:8889 -f pulse default")
        print("按Ctrl+C停止...")
        
        # 生成测试音频（正弦波）
        sample_rate = 16000
        duration = 0.1  # 每块100ms
        samples_per_chunk = int(sample_rate * duration)
        frequency = 440  # A4音符
        
        chunk_count = 0
        while True:
            # 生成正弦波
            t = np.linspace(0, duration, samples_per_chunk, False)
            audio_data = np.sin(2 * np.pi * frequency * t).astype(np.float32) * 0.3
            
            # 发送音频数据
            speaker.put_audio_data(audio_data)
            chunk_count += 1
            
            if chunk_count % 50 == 0:  # 每5秒输出一次统计
                stats = speaker.get_stats()
                print(f"统计: {stats}")
            
            await asyncio.sleep(duration)
    
    except KeyboardInterrupt:
        print("\n停止测试...")
    
    finally:
        speaker.stop()
        print("测试完成")


if __name__ == "__main__":
    asyncio.run(test_speaker_thread())