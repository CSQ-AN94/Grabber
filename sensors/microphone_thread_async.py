#!/usr/bin/env python3
"""
异步麦克风线程 - 专为Gemini Live API提供网络音频流输入
完全异步架构，统一的事件循环，无线程切换开销
"""

import asyncio
import logging
import time
from typing import Optional, Tuple
import numpy as np


class MicrophoneThread:
    """
    异步麦克风线程，通过网络接收音频流并提供给Gemini Agent
    
    设计理念：
    1. 完全异步架构，统一事件循环
    2. 固定16kHz单声道格式（Gemini Live API要求）
    3. 异步安全的音频队列
    4. 简单的网络协议（TCP原始音频数据）
    5. 优雅的启动/停止机制
    """
    
    def __init__(self, port: int = 8888, sample_rate: int = 16000, chunk_size: int = 1024):
        """
        初始化异步麦克风线程
        
        Args:
            port: 监听端口
            sample_rate: 采样率（固定16kHz for Gemini）
            chunk_size: 音频块大小
        """
        self.port = port
        self.sample_rate = sample_rate
        self.chunk_size = chunk_size
        
        # 异步服务器和连接
        self.server = None
        self.client_writer = None
        self.is_running = False
        
        # 音频队列
        self.audio_queue = asyncio.Queue(maxsize=100)
        
        # 日志
        self.logger = logging.getLogger(__name__)
        
        # 统计信息
        self.bytes_received = 0
        self.chunks_received = 0
        self.client_address = None
        self.start_time = None
        
    async def start_server(self):
        """启动异步麦克风服务器"""
        if self.is_running:
            self.logger.warning("麦克风服务器已在运行")
            return
        
        try:
            # 创建异步TCP服务器
            self.server = await asyncio.start_server(
                self._handle_client,
                '0.0.0.0',
                self.port,
                reuse_address=True
            )
            
            self.is_running = True
            self.start_time = time.time()
            
            self.logger.info(f"异步麦克风服务器启动，监听端口: {self.port}")
            self.logger.info(f"音频格式: {self.sample_rate}Hz, 单声道, 16位PCM")
            self.logger.info(f"发送音频命令示例:")
            self.logger.info(f"  ffmpeg -f alsa -i default -ar {self.sample_rate} -ac 1 -f s16le tcp://localhost:{self.port}")
            self.logger.info(f"  或使用: python sensors/audio_client_tcp.py --host <SERVER_IP>")
            
            # 开始监听
            await self.server.start_serving()
            
        except Exception as e:
            self.logger.error(f"启动麦克风服务器失败: {e}")
            raise
    
    async def stop_server(self):
        """停止异步麦克风服务器"""
        if not self.is_running:
            return
        
        self.is_running = False
        
        # 关闭客户端连接
        if self.client_writer:
            try:
                self.client_writer.close()
                await self.client_writer.wait_closed()
            except Exception as e:
                self.logger.debug(f"关闭客户端连接时出错: {e}")
            self.client_writer = None
        
        # 关闭服务器
        if self.server:
            try:
                self.server.close()
                await self.server.wait_closed()
            except Exception as e:
                self.logger.debug(f"关闭服务器时出错: {e}")
            self.server = None
        
        # 清空音频队列
        while not self.audio_queue.empty():
            try:
                self.audio_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
        
        self.logger.info("异步麦克风服务器已停止")
    
    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        """异步处理客户端连接"""
        client_address = writer.get_extra_info('peername')
        self.client_address = client_address
        self.client_writer = writer
        
        self.logger.info(f"音频客户端连接: {client_address}")
        
        try:
            buffer = b''
            last_stats_time = time.time()
            
            while self.is_running:
                try:
                    # 异步接收音频数据
                    data = await asyncio.wait_for(reader.read(4096), timeout=0.5)
                    
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
                                await self._put_audio_chunk(chunk)
                                self.chunks_received += 1
                            except Exception as e:
                                self.logger.debug(f"队列满，丢弃音频块: {e}")
                    
                    # 定期输出统计信息
                    now = time.time()
                    if now - last_stats_time >= 10:  # 每10秒输出一次
                        stats = self.get_stats()
                        self.logger.info(f"音频统计: {stats['bytes_received']} 字节, "
                                       f"{stats['chunks_received']} 块, "
                                       f"队列大小: {stats['queue_size']}")
                        last_stats_time = now
                
                except asyncio.TimeoutError:
                    continue  # 超时继续检查
                except asyncio.CancelledError:
                    break
                except Exception as e:
                    self.logger.error(f"接收音频数据错误: {e}")
                    break
        
        except Exception as e:
            self.logger.error(f"客户端处理错误: {e}")
        
        finally:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as e:
                self.logger.debug(f"关闭客户端连接时出错: {e}")
            
            self.client_writer = None
            self.client_address = None
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
        """异步放入音频块到队列"""
        try:
            self.audio_queue.put_nowait(chunk)
        except asyncio.QueueFull:
            # 队列满时，移除最老的块，添加新块
            try:
                self.audio_queue.get_nowait()
                self.audio_queue.put_nowait(chunk)
            except asyncio.QueueEmpty:
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
        获取音频块（同步接口，向后兼容）
        注意：此方法不推荐使用，建议使用异步版本
        
        Returns:
            bytes: 音频数据块，如果没有数据则返回None
        """
        try:
            # 尝试获取当前事件循环
            loop = asyncio.get_running_loop()
            
            # 创建future来获取数据
            future = asyncio.create_task(
                asyncio.wait_for(self.audio_queue.get(), timeout=0.1)
            )
            
            # 如果在异步上下文中，直接抛出异常
            if loop.is_running():
                raise RuntimeError("不能在异步上下文中使用同步方法，请使用 await get_audio_chunk()")
            
        except RuntimeError:
            # 没有运行的事件循环，使用新的事件循环
            try:
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
        uptime = time.time() - self.start_time if self.start_time else 0
        return {
            "is_running": self.is_running,
            "port": self.port,
            "bytes_received": self.bytes_received,
            "chunks_received": self.chunks_received,
            "queue_size": self.audio_queue.qsize(),
            "client_connected": self.client_writer is not None,
            "client_address": self.client_address,
            "uptime_seconds": uptime,
            "bytes_per_second": self.bytes_received / uptime if uptime > 0 else 0
        }
    
    # 向后兼容的方法别名
    def start(self):
        """向后兼容的同步启动方法"""
        raise RuntimeError("请使用 await start_server() 代替 start()")
    
    def stop(self):
        """向后兼容的同步停止方法"""
        raise RuntimeError("请使用 await stop_server() 代替 stop()")


# 测试函数
async def test_microphone_thread():
    """测试异步麦克风线程"""
    logging.basicConfig(level=logging.INFO)
    
    mic = MicrophoneThread(port=8888)
    
    try:
        # 启动麦克风服务器
        await mic.start_server()
        
        print("异步麦克风服务器已启动，等待音频数据...")
        print("可以用以下命令发送音频:")
        print("  python sensors/audio_client_tcp.py --host localhost")
        print("  或: ffmpeg -f alsa -i default -ar 16000 -ac 1 -f s16le tcp://localhost:8888")
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
        await mic.stop_server()
        print("测试完成")


if __name__ == "__main__":
    asyncio.run(test_microphone_thread())