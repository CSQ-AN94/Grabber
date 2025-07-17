#!/usr/bin/env python3
"""
简化的麦克风线程 - 专为Gemini Live API提供网络音频流输入
"""

import asyncio
import logging
import socket
import threading
import time
from typing import Optional
import numpy as np


class MicrophoneThread:
    """
    简化的麦克风线程，通过网络接收音频流并提供给Gemini Agent
    
    设计理念：
    1. 只支持网络音频流输入（避免麦克风硬件依赖）
    2. 固定16kHz单声道格式（Gemini Live API要求）
    3. 线程安全的音频队列
    4. 简单的网络协议（TCP原始音频数据）
    """
    
    def __init__(self, port: int = 8888, sample_rate: int = 16000, chunk_size: int = 1024):
        """
        初始化麦克风线程
        
        Args:
            port: 监听端口
            sample_rate: 采样率（固定16kHz for Gemini）
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
        self.bytes_received = 0
        self.chunks_received = 0
        
    def start(self):
        """启动麦克风线程"""
        if self.is_running:
            self.logger.warning("麦克风线程已在运行")
            return
        
        self.is_running = True
        self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self.server_thread.start()
        
        self.logger.info(f"麦克风线程启动，监听端口: {self.port}")
        self.logger.info(f"音频格式: {self.sample_rate}Hz, 单声道, 16位PCM")
        self.logger.info(f"发送音频命令示例:")
        self.logger.info(f"  ffmpeg -f alsa -i default -ar {self.sample_rate} -ac 1 -f s16le tcp://localhost:{self.port}")
        self.logger.info(f"  gstreamer: gst-launch-1.0 autoaudiosrc ! audioconvert ! audioresample ! audio/x-raw,rate={self.sample_rate},channels=1,format=S16LE ! tcpclientsink host=localhost port={self.port}")
    
    def stop(self):
        """停止麦克风线程"""
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
        
        self.logger.info("麦克风线程已停止")
    
    def _server_loop(self):
        """服务器主循环"""
        try:
            # 创建服务器Socket
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind(('0.0.0.0', self.port))
            self.server_socket.listen(1)
            self.server_socket.settimeout(1.0)  # 1秒超时用于检查停止信号
            
            self.logger.info(f"音频服务器监听中...")
            
            while self.is_running:
                try:
                    # 接受客户端连接
                    client_socket, addr = self.server_socket.accept()
                    self.logger.info(f"音频客户端连接: {addr}")
                    
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
            
            buffer = b''
            last_stats_time = time.time()
            
            while self.is_running:
                try:
                    # 接收音频数据
                    data = client_socket.recv(4096)
                    if not data:
                        self.logger.info("客户端断开连接")
                        break
                    
                    # 添加到缓冲区
                    buffer += data
                    self.bytes_received += len(data)
                    
                    # 处理完整的音频块
                    while len(buffer) >= self.chunk_size * 2:  # 16位 = 2字节
                        chunk = buffer[:self.chunk_size * 2]
                        buffer = buffer[self.chunk_size * 2:]
                        
                        # 验证音频数据
                        if self._validate_audio_chunk(chunk):
                            try:
                                # 非阻塞放入队列
                                loop = asyncio.new_event_loop()
                                asyncio.set_event_loop(loop)
                                loop.run_until_complete(self._put_audio_chunk(chunk))
                                loop.close()
                                
                                self.chunks_received += 1
                            except Exception as e:
                                self.logger.debug(f"队列满，丢弃音频块: {e}")
                    
                    # 定期输出统计信息
                    now = time.time()
                    if now - last_stats_time >= 10:  # 每10秒输出一次
                        self.logger.info(f"音频统计: {self.bytes_received} 字节, {self.chunks_received} 块, 队列大小: {self.audio_queue.qsize()}")
                        last_stats_time = now
                
                except socket.timeout:
                    continue  # 超时继续
                except ConnectionResetError:
                    self.logger.info("客户端重置连接")
                    break
                except Exception as e:
                    self.logger.error(f"接收音频数据错误: {e}")
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
    
    async def _put_audio_chunk(self, chunk: bytes):
        """非阻塞放入音频块到队列"""
        try:
            self.audio_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            # 队列满时，移除最老的块，添加新块
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.put_nowait(chunk)
            except:
                pass  # 如果操作失败就放弃这个块
    
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
    
    def get_audio_chunk_sync(self) -> Optional[bytes]:
        """
        获取音频块（同步接口）
        
        Returns:
            bytes: 音频数据块，如果没有数据则返回None
        """
        try:
            # 创建临时事件循环来获取数据
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                chunk = loop.run_until_complete(
                    asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
                )
                return chunk
            except asyncio.TimeoutError:
                return None
            finally:
                loop.close()
        except Exception as e:
            self.logger.debug(f"同步获取音频块失败: {e}")
            return None
    
    def is_audio_available(self) -> bool:
        """检查是否有音频数据可用"""
        return not self.audio_queue.empty()
    
    def get_stats(self) -> dict:
        """获取统计信息"""
        return {
            "is_running": self.is_running,
            "port": self.port,
            "bytes_received": self.bytes_received,
            "chunks_received": self.chunks_received,
            "queue_size": self.audio_queue.qsize(),
            "client_connected": self.client_socket is not None
        }


# 测试函数
async def test_microphone_thread():
    """测试麦克风线程"""
    logging.basicConfig(level=logging.INFO)
    
    mic = MicrophoneThread(port=9888)
    
    try:
        # 启动麦克风线程
        mic.start()
        
        print("麦克风线程已启动，等待音频数据...")
        print("可以用以下命令发送音频:")
        print("  ffmpeg -f alsa -i default -ar 16000 -ac 1 -f s16le tcp://localhost:8888")
        print("按Ctrl+C停止...")
        
        # 接收和处理音频数据
        chunk_count = 0
        while True:
            chunk = await mic.get_audio_chunk()
            if chunk:
                chunk_count += 1
                print(f"收到音频块 {chunk_count}: {len(chunk)} 字节")
                
                # 每100个块输出一次统计
                if chunk_count % 100 == 0:
                    stats = mic.get_stats()
                    print(f"统计: {stats}")
            
            await asyncio.sleep(0.01)
    
    except KeyboardInterrupt:
        print("\n停止测试...")
    
    finally:
        mic.stop()
        print("测试完成")


if __name__ == "__main__":
    asyncio.run(test_microphone_thread())