#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
笔记本端TCP音频客户端
基于microphone_thread.py和speaker_thread.py的设计理念
使用TCP原始音频流，低延迟高效
"""

import socket
import numpy as np
import sounddevice as sd
import threading
import time
import argparse
import logging
from queue import Queue, Empty

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TCPAudioClient:
    """
    TCP音频客户端
    与Jetson的MicrophoneThread和SpeakerThread配套工作
    """
    
    def __init__(self, jetson_host="192.168.3.1", mic_port=9888, speaker_port=9889):
        """
        初始化TCP音频客户端
        
        Args:
            jetson_host: Jetson IP地址
            mic_port: 麦克风端口（发送到Jetson）
            speaker_port: 扬声器端口（从Jetson接收）
        """
        self.jetson_host = jetson_host
        self.mic_port = mic_port
        self.speaker_port = speaker_port
        
        # 音频参数（与microphone_thread.py保持一致）
        self.sample_rate = 16000  # Live API标准
        self.channels = 1  # 单声道
        self.dtype = np.int16
        self.chunk_size = 1024  # 64ms的音频块
        
        # 音频设备
        self.input_device = None
        self.output_device = None
        
        # 网络连接
        self.mic_socket = None
        self.speaker_socket = None
        
        # 音频流
        self.input_stream = None
        self.output_stream = None
        
        # 状态管理
        self.is_running = False
        self.is_recording = False
        self.is_playing = False
        
        # 音频队列
        self.output_queue = Queue(maxsize=100)
        
        # 线程
        self.speaker_thread = None
        
        # 统计
        self.bytes_sent = 0
        self.bytes_received = 0
        
    def find_audio_devices(self):
        """查找并配置音频设备"""
        try:
            devices = sd.query_devices()
            logger.info("可用音频设备:")
            
            input_devices = []
            output_devices = []
            
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    input_devices.append((i, device['name']))
                    logger.info(f"  输入设备 {i}: {device['name']}")
                if device['max_output_channels'] > 0:
                    output_devices.append((i, device['name']))
                    logger.info(f"  输出设备 {i}: {device['name']}")
            
            # 查找最佳输入设备
            for device_id, name in input_devices:
                if 'DMIC16kHz' in name:
                    self.input_device = device_id
                    logger.info(f"选择输入设备: {name} (ID: {device_id})")
                    break
                elif 'DMIC' in name and self.input_device is None:
                    self.input_device = device_id
                    logger.info(f"选择输入设备: {name} (ID: {device_id})")
                elif 'sof-hda-dsp' in name and self.input_device is None:
                    self.input_device = device_id
                    logger.info(f"选择输入设备: {name} (ID: {device_id})")
            
            # 查找最佳输出设备
            for device_id, name in output_devices:
                if 'Analog' in name:
                    self.output_device = device_id
                    logger.info(f"选择输出设备: {name} (ID: {device_id})")
                    break
                elif 'sof-hda-dsp' in name and 'HDMI' not in name and self.output_device is None:
                    self.output_device = device_id
                    logger.info(f"选择输出设备: {name} (ID: {device_id})")
            
            if self.input_device is None:
                self.input_device = sd.default.device[0]
                logger.info(f"使用默认输入设备: {self.input_device}")
            
            if self.output_device is None:
                self.output_device = sd.default.device[1]
                logger.info(f"使用默认输出设备: {self.output_device}")
            
            return True
            
        except Exception as e:
            logger.error(f"音频设备查找失败: {e}")
            return False
    
    def connect_to_jetson(self):
        """连接到Jetson音频服务器"""
        try:
            # 连接麦克风端口（发送音频）
            logger.info(f"连接到Jetson麦克风服务器: {self.jetson_host}:{self.mic_port}")
            self.mic_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.mic_socket.connect((self.jetson_host, self.mic_port))
            logger.info("麦克风连接成功")
            
            # 连接扬声器端口（接收音频）
            logger.info(f"连接到Jetson扬声器服务器: {self.jetson_host}:{self.speaker_port}")
            self.speaker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.speaker_socket.connect((self.jetson_host, self.speaker_port))
            logger.info("扬声器连接成功")
            
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
        
        if self.speaker_socket:
            try:
                self.speaker_socket.close()
            except:
                pass
            self.speaker_socket = None
        
        logger.info("已断开连接")
    
    def _audio_input_callback(self, indata, frames, time, status):
        """音频输入回调函数"""
        if status:
            logger.warning(f"音频输入状态警告: {status}")
        
        if self.is_recording and self.mic_socket:
            try:
                # 转换为int16并发送
                audio_data = (indata[:, 0] * 32767).astype(np.int16)
                audio_bytes = audio_data.tobytes()
                
                # 发送到Jetson
                self.mic_socket.sendall(audio_bytes)
                self.bytes_sent += len(audio_bytes)
                
            except Exception as e:
                logger.error(f"发送音频数据失败: {e}")
                self.is_recording = False
    
    def _audio_output_callback(self, outdata, frames, time, status):
        """音频输出回调函数"""
        if status:
            logger.warning(f"音频输出状态警告: {status}")
        
        try:
            # 从队列获取音频数据
            audio_bytes = self.output_queue.get_nowait()
            audio_data = np.frombuffer(audio_bytes, dtype=np.int16)
            
            # 转换为float32并输出
            if len(audio_data) >= frames:
                outdata[:, 0] = audio_data[:frames].astype(np.float32) / 32767.0
                # 如果有剩余数据，放回队列
                if len(audio_data) > frames:
                    remaining = audio_data[frames:].tobytes()
                    try:
                        self.output_queue.put_nowait(remaining)
                    except:
                        pass  # 队列满就丢弃
            else:
                # 数据不足，输出静音并填充剩余
                outdata[:len(audio_data), 0] = audio_data.astype(np.float32) / 32767.0
                outdata[len(audio_data):, 0] = 0
                
        except Empty:
            # 队列为空，输出静音
            outdata.fill(0)
        except Exception as e:
            logger.debug(f"音频输出错误: {e}")
            outdata.fill(0)
    
    def _speaker_receiver_thread(self):
        """扬声器音频接收线程"""
        try:
            buffer = b''
            while self.is_running and self.speaker_socket:
                try:
                    # 接收音频数据
                    data = self.speaker_socket.recv(4096)
                    if not data:
                        logger.info("扬声器连接断开")
                        break
                    
                    buffer += data
                    self.bytes_received += len(data)
                    
                    # 处理完整的音频块
                    while len(buffer) >= self.chunk_size * 2:  # 16位 = 2字节
                        chunk = buffer[:self.chunk_size * 2]
                        buffer = buffer[self.chunk_size * 2:]
                        
                        # 放入播放队列
                        try:
                            self.output_queue.put_nowait(chunk)
                        except:
                            # 队列满，移除旧数据
                            try:
                                self.output_queue.get_nowait()
                                self.output_queue.put_nowait(chunk)
                            except:
                                pass
                
                except Exception as e:
                    if self.is_running:
                        logger.error(f"接收音频数据失败: {e}")
                    break
        
        except Exception as e:
            logger.error(f"扬声器接收线程错误: {e}")
    
    def start_audio_streams(self):
        """启动音频流"""
        try:
            # 启动输入流（麦克风）
            self.input_stream = sd.InputStream(
                device=self.input_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                dtype=np.float32,
                callback=self._audio_input_callback
            )
            
            # 启动输出流（扬声器）
            self.output_stream = sd.OutputStream(
                device=self.output_device,
                channels=self.channels,
                samplerate=self.sample_rate,
                blocksize=self.chunk_size,
                dtype=np.float32,
                callback=self._audio_output_callback
            )
            
            self.input_stream.start()
            self.output_stream.start()
            
            logger.info("音频流启动成功")
            return True
            
        except Exception as e:
            logger.error(f"启动音频流失败: {e}")
            return False
    
    def stop_audio_streams(self):
        """停止音频流"""
        try:
            if self.input_stream:
                self.input_stream.stop()
                self.input_stream.close()
            if self.output_stream:
                self.output_stream.stop()
                self.output_stream.close()
            logger.info("音频流已停止")
        except Exception as e:
            logger.error(f"停止音频流失败: {e}")
    
    def start(self):
        """启动客户端"""
        self.is_running = True
        
        # 查找音频设备
        if not self.find_audio_devices():
            return False
        
        # 连接到Jetson
        if not self.connect_to_jetson():
            return False
        
        # 启动音频流
        if not self.start_audio_streams():
            return False
        
        # 启动扬声器接收线程
        self.speaker_thread = threading.Thread(target=self._speaker_receiver_thread, daemon=True)
        self.speaker_thread.start()
        
        # 开始录音和播放
        self.is_recording = True
        self.is_playing = True
        
        logger.info("TCP音频客户端启动成功")
        logger.info("开始录音和播放...")
        
        return True
    
    def stop(self):
        """停止客户端"""
        logger.info("正在停止TCP音频客户端...")
        
        self.is_recording = False
        self.is_playing = False
        
        # 停止音频流
        self.stop_audio_streams()
        
        # 断开连接
        self.disconnect()
        
        # 等待线程结束
        if self.speaker_thread and self.speaker_thread.is_alive():
            self.speaker_thread.join(timeout=2)
        
        logger.info("TCP音频客户端已停止")
    
    def get_stats(self):
        """获取统计信息"""
        return {
            "is_running": self.is_running,
            "is_recording": self.is_recording,
            "is_playing": self.is_playing,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
            "output_queue_size": self.output_queue.qsize()
        }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="TCP音频客户端")
    parser.add_argument("--host", default="192.168.3.1", help="Jetson主机地址")
    parser.add_argument("--mic-port", type=int, default=9888, help="麦克风端口")
    parser.add_argument("--speaker-port", type=int, default=9889, help="扬声器端口")
    parser.add_argument("--list-devices", action="store_true", help="列出音频设备")
    
    args = parser.parse_args()
    
    if args.list_devices:
        try:
            devices = sd.query_devices()
            print("可用的音频设备:")
            for i, device in enumerate(devices):
                print(f"  {i}: {device['name']}")
                print(f"      输入通道: {device['max_input_channels']}")
                print(f"      输出通道: {device['max_output_channels']}")
                print(f"      默认采样率: {device['default_samplerate']}")
                print()
        except Exception as e:
            print(f"列出设备失败: {e}")
        return
    
    # 创建客户端
    client = TCPAudioClient(args.host, args.mic_port, args.speaker_port)
    
    try:
        # 启动客户端
        if not client.start():
            logger.error("无法启动客户端")
            return
        
        logger.info("客户端运行中...")
        logger.info("按 Ctrl+C 退出")
        
        # 定期输出统计信息
        last_stats_time = time.time()
        while True:
            time.sleep(1)
            
            # 每10秒输出统计
            now = time.time()
            if now - last_stats_time >= 10:
                stats = client.get_stats()
                logger.info(f"统计: 发送 {stats['bytes_sent']} 字节, "
                           f"接收 {stats['bytes_received']} 字节, "
                           f"队列大小 {stats['output_queue_size']}")
                last_stats_time = now
        
    except KeyboardInterrupt:
        logger.info("用户中断")
    except Exception as e:
        logger.error(f"客户端错误: {e}")
    finally:
        client.stop()


if __name__ == "__main__":
    main()