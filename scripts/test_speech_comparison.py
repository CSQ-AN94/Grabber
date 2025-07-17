#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比较原始语音系统和修复版语音系统
找出阻塞问题的根本原因
"""

import sys
import os
import asyncio
import logging
import time

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from intelligence.speech import SpeechSystem
from intelligence.speech_fixed import FixedSpeechSystem

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_original_system():
    """测试原始语音系统"""
    print("\n🔍 测试原始语音系统...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        test_texts = ["第一条测试", "第二条测试"]
        
        for i, text in enumerate(test_texts, 1):
            print(f"📢 原始系统 - 第{i}条: {text}")
            start_time = time.time()
            
            # 这里可能会阻塞
            result = await speech_system.say(text)
            
            end_time = time.time()
            elapsed = end_time - start_time
            
            print(f"✅ 原始系统 - 第{i}条完成: {result.get('success', False)}, 耗时: {elapsed:.2f}秒")
            
            if not result.get('success', False):
                print(f"❌ 错误: {result.get('message', '未知错误')}")
                break
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"原始系统测试失败: {e}")


async def test_fixed_system():
    """测试修复版语音系统"""
    print("\n🔍 测试修复版语音系统...")
    
    try:
        config = load_config("config.ini")
        speech_system = FixedSpeechSystem(config.speech)
        
        test_texts = ["第一条测试", "第二条测试"]
        
        for i, text in enumerate(test_texts, 1):
            print(f"📢 修复系统 - 第{i}条: {text}")
            start_time = time.time()
            
            result = await speech_system.say(text)
            
            end_time = time.time()
            elapsed = end_time - start_time
            
            print(f"✅ 修复系统 - 第{i}条完成: {result.get('success', False)}, 耗时: {elapsed:.2f}秒")
            
            if not result.get('success', False):
                print(f"❌ 错误: {result.get('message', '未知错误')}")
                break
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"修复系统测试失败: {e}")


async def test_parallel_original():
    """测试原始系统的并行处理"""
    print("\n🔍 测试原始系统并行处理...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        # 并行发送多个任务
        tasks = []
        for i in range(3):
            task = asyncio.create_task(speech_system.say(f"并行测试第{i+1}条"))
            tasks.append(task)
        
        print("📢 原始系统 - 并行发送3个任务...")
        start_time = time.time()
        
        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"✅ 原始系统 - 并行任务完成，总耗时: {elapsed:.2f}秒")
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"❌ 任务{i+1}异常: {result}")
            else:
                print(f"✅ 任务{i+1}结果: {result.get('success', False)}")
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"原始系统并行测试失败: {e}")


async def test_parallel_fixed():
    """测试修复版系统的并行处理"""
    print("\n🔍 测试修复版系统并行处理...")
    
    try:
        config = load_config("config.ini")
        speech_system = FixedSpeechSystem(config.speech)
        
        # 并行发送多个任务
        tasks = []
        for i in range(3):
            task = asyncio.create_task(speech_system.say(f"并行测试第{i+1}条"))
            tasks.append(task)
        
        print("📢 修复系统 - 并行发送3个任务...")
        start_time = time.time()
        
        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        end_time = time.time()
        elapsed = end_time - start_time
        
        print(f"✅ 修复系统 - 并行任务完成，总耗时: {elapsed:.2f}秒")
        
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                print(f"❌ 任务{i+1}异常: {result}")
            else:
                print(f"✅ 任务{i+1}结果: {result.get('success', False)}")
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"修复系统并行测试失败: {e}")


async def main():
    """主测试函数"""
    print("🔧 语音系统比较测试")
    print("=" * 50)
    print("目标: 找出阻塞问题的根本原因")
    print("=" * 50)
    
    # 测试顺序
    print("\n1. 测试原始系统顺序播放")
    await test_original_system()
    
    print("\n2. 测试修复版系统顺序播放") 
    await test_fixed_system()
    
    print("\n3. 测试原始系统并行处理")
    await test_parallel_original()
    
    print("\n4. 测试修复版系统并行处理")
    await test_parallel_fixed()
    
    print("\n🎉 比较测试完成!")
    print("\n📊 分析:")
    print("- 如果原始系统在第一条就阻塞，问题在于队列机制")
    print("- 如果修复版系统正常工作，说明简化的锁机制更有效")
    print("- 比较并行处理的耗时可以看出哪种方式更高效")


if __name__ == "__main__":
    asyncio.run(main())