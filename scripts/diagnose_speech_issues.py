#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
诊断语音系统问题
分析阻塞和连接问题
"""

import sys
import os
import asyncio
import logging
import time
import threading

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from intelligence.speech import SpeechSystem

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_single_speech():
    """测试单个语音合成流程"""
    print("\n🔍 测试单个语音合成流程...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        print("📢 开始语音合成...")
        start_time = time.time()
        
        # 测试单个语音
        result = await speech_system.say("这是一个测试语音")
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"✅ 语音合成完成，耗时: {elapsed:.2f}秒")
        print(f"📊 结果: {result}")
        
        # 检查工作线程状态
        if hasattr(speech_system, 'speech_worker_thread') and speech_system.speech_worker_thread:
            print(f"🔧 工作线程存活: {speech_system.speech_worker_thread.is_alive()}")
            print(f"🔧 队列大小: {speech_system.speech_queue.qsize()}")
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"单个语音测试失败: {e}")


async def test_speech_without_network():
    """测试不连接网络的语音合成"""
    print("\n🔍 测试不连接网络的语音合成...")
    
    try:
        # 创建无网络配置
        class MockSpeechConfig:
            def __init__(self):
                self.app_id = "aeb60378"
                self.api_key = "e248b59b7b21d7291702b7808ba07257"
                self.api_secret = "MjQ1ZmM3MjkwNmEzZTQyN2ZiNTYxN2Ey"
                self.notebook_ip = "192.168.999.999"  # 错误的IP
                self.speaker_port = 9889
        
        mock_config = MockSpeechConfig()
        speech_system = SpeechSystem(mock_config)
        
        print("📢 开始语音合成（无网络）...")
        start_time = time.time()
        
        # 测试单个语音
        result = await speech_system.say("这是一个无网络测试语音")
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"✅ 语音合成完成，耗时: {elapsed:.2f}秒")
        print(f"📊 结果: {result}")
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"无网络语音测试失败: {e}")


async def test_queue_directly():
    """直接测试语音队列系统"""
    print("\n🔍 直接测试语音队列系统...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        # 检查队列初始状态
        print(f"🔧 初始队列大小: {speech_system.speech_queue.qsize()}")
        print(f"🔧 工作线程运行: {speech_system.speech_worker_running}")
        print(f"🔧 工作线程存活: {speech_system.speech_worker_thread.is_alive()}")
        
        # 快速发送多个任务
        tasks = []
        for i in range(3):
            print(f"📤 发送任务 {i+1}")
            task = asyncio.create_task(speech_system.say(f"队列测试第{i+1}条"))
            tasks.append(task)
            print(f"🔧 队列大小: {speech_system.speech_queue.qsize()}")
            
        # 等待所有任务完成
        print("⏳ 等待所有任务完成...")
        start_time = time.time()
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"✅ 所有任务完成，总耗时: {elapsed:.2f}秒")
        
        # 检查结果
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"❌ 任务{i+1}异常: {result}")
            else:
                print(f"✅ 任务{i+1}结果: {result.get('success', False)}")
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"队列测试失败: {e}")


def test_network_connection():
    """测试网络连接"""
    print("\n🔍 测试网络连接...")
    
    try:
        config = load_config("config.ini")
        
        import socket
        
        # 测试连接到扬声器服务器
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        
        try:
            print(f"📡 尝试连接到: {config.speech.notebook_ip}:{config.speech.speaker_port}")
            result = sock.connect_ex((config.speech.notebook_ip, config.speech.speaker_port))
            
            if result == 0:
                print("✅ 网络连接成功")
            else:
                print(f"❌ 网络连接失败，错误码: {result}")
                
        finally:
            sock.close()
            
    except Exception as e:
        logger.error(f"网络连接测试失败: {e}")


async def main():
    """主诊断函数"""
    print("🔧 语音系统问题诊断")
    print("=" * 50)
    
    # 1. 测试网络连接
    test_network_connection()
    
    # 2. 测试单个语音合成
    await test_single_speech()
    
    # 3. 测试无网络语音合成
    await test_speech_without_network()
    
    # 4. 测试队列系统
    await test_queue_directly()
    
    print("\n🎉 诊断完成!")


if __name__ == "__main__":
    asyncio.run(main())