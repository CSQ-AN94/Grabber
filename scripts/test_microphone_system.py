#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
麦克风系统测试脚本
用于独立测试音频输入链路：笔记本麦克风 -> Jetson MicrophoneThread
"""

import sys
import os
import time
import logging
import asyncio
import argparse

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from sensors.microphone_thread import MicrophoneThread

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_microphone_server():
    """测试麦克风服务器"""
    print("🎤 启动麦克风服务器测试...")
    
    try:
        # 加载配置
        config = load_config("config.ini")
        
        # 创建麦克风线程
        mic_thread = MicrophoneThread(
            sample_rate=config.agent.audio_sample_rate,
            channels=config.agent.audio_channels,
            chunk_size=config.agent.audio_chunk_size
        )
        
        print(f"启动麦克风服务器，监听端口 8888")
        print("等待笔记本客户端连接...")
        print("请在笔记本上运行：")
        print(f"  python sensors/audio_client_tcp.py --host <JETSON_IP>")
        print("或者:")
        print(f"  python sensors/audio_client_tcp.py --host 192.168.3.10")
        
        # 启动服务器
        await mic_thread.start_server()
        
        # 监控音频数据接收
        last_queue_size = 0
        bytes_received = 0
        
        while True:
            await asyncio.sleep(2)
            
            current_queue_size = mic_thread.audio_queue.qsize()
            new_frames = current_queue_size - last_queue_size
            
            if new_frames > 0:
                # 估算接收的字节数 (16kHz, 单声道, 16bit)
                bytes_per_frame = config.agent.audio_chunk_size * 2  # 16bit = 2 bytes
                bytes_received += new_frames * bytes_per_frame
                
                print(f"✅ 音频队列: {current_queue_size} 帧, "
                      f"新增: {new_frames} 帧, "
                      f"累计: {bytes_received/1024:.2f} KB")
                      
                last_queue_size = current_queue_size
            elif current_queue_size == 0:
                print("⏳ 等待音频数据...")
            else:
                print(f"📊 音频队列稳定在: {current_queue_size} 帧")
    
    except KeyboardInterrupt:
        print("\n用户中断测试")
    except Exception as e:
        logger.error(f"麦克风服务器测试失败: {e}")
    finally:
        if 'mic_thread' in locals():
            await mic_thread.stop_server()
        print("🎤 麦克风服务器测试结束")


async def test_audio_data_quality():
    """测试音频数据质量"""
    print("🔍 音频数据质量测试...")
    
    try:
        config = load_config("config.ini")
        mic_thread = MicrophoneThread(
            sample_rate=config.agent.audio_sample_rate,
            channels=config.agent.audio_channels,
            chunk_size=config.agent.audio_chunk_size
        )
        
        await mic_thread.start_server()
        print("等待音频数据进行质量分析...")
        
        # 等待一些音频数据
        while mic_thread.audio_queue.qsize() < 10:
            await asyncio.sleep(0.5)
            
        # 分析音频数据
        sample_count = 0
        total_samples = 5
        
        while sample_count < total_samples:
            if not mic_thread.audio_queue.empty():
                audio_data = await mic_thread.audio_queue.get()
                
                if audio_data:
                    import numpy as np
                    
                    # 将bytes转换为numpy数组进行分析
                    audio_array = np.frombuffer(audio_data, dtype=np.int16)
                    
                    # 计算音频统计信息
                    rms = np.sqrt(np.mean(audio_array**2))
                    peak = np.max(np.abs(audio_array))
                    
                    print(f"样本 {sample_count+1}: "
                          f"长度={len(audio_data)}字节, "
                          f"RMS={rms:.2f}, "
                          f"峰值={peak}, "
                          f"范围=[{np.min(audio_array)}, {np.max(audio_array)}]")
                    
                    sample_count += 1
            else:
                await asyncio.sleep(0.1)
        
        print("✅ 音频数据质量分析完成")
        
    except Exception as e:
        logger.error(f"音频质量测试失败: {e}")
    finally:
        if 'mic_thread' in locals():
            await mic_thread.stop_server()


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="麦克风系统测试")
    parser.add_argument("--quality", action="store_true", help="进行音频质量测试")
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("麦克风系统测试")
    print("=" * 50)
    
    if args.quality:
        asyncio.run(test_audio_data_quality())
    else:
        asyncio.run(test_microphone_server())


if __name__ == "__main__":
    main()