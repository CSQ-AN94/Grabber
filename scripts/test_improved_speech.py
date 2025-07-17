#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试优化后的语音输出系统
解决语音重叠、声音抖动和音频设备错误问题
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

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_sequential_speech():
    """测试顺序语音播放（解决重叠问题）"""
    print("\n🎵 测试顺序语音播放...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        test_texts = [
            "第一条语音测试",
            "第二条语音测试", 
            "第三条语音测试",
            "第四条语音测试"
        ]
        
        print("开始快速连续播放测试（应该顺序播放，不重叠）...")
        start_time = time.time()
        
        for i, text in enumerate(test_texts, 1):
            print(f"📢 发送第{i}条: {text}")
            result = await speech_system.say(text)
            
            if result["success"]:
                print(f"✅ 第{i}条成功")
            else:
                print(f"❌ 第{i}条失败: {result['message']}")
            
            # 不等待，立即发送下一条
        
        elapsed = time.time() - start_time
        print(f"✅ 顺序播放测试完成，总用时: {elapsed:.2f}秒")
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"顺序播放测试失败: {e}")


async def test_interrupt_speech():
    """测试语音中断功能"""
    print("\n⚡ 测试语音中断功能...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        # 先播放一个长语音
        print("📢 播放长语音...")
        long_text = "这是一个很长的语音测试内容，用来测试中断功能是否正常工作。正常情况下这条语音会被下一条紧急语音中断。"
        
        # 不等待，立即发送中断语音
        asyncio.create_task(speech_system.say(long_text))
        
        # 等待一点时间让第一条语音开始
        await asyncio.sleep(1)
        
        # 发送中断语音
        print("🚨 发送中断语音...")
        result = await speech_system.say("紧急中断测试！", interrupt_current=True)
        
        if result["success"]:
            print("✅ 中断测试成功")
        else:
            print(f"❌ 中断测试失败: {result['message']}")
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"中断测试失败: {e}")


async def test_queue_overflow():
    """测试语音队列溢出处理"""
    print("\n🌊 测试语音队列溢出处理...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        # 快速发送超过队列限制的语音
        overflow_texts = [f"溢出测试第{i}条" for i in range(1, 10)]
        
        print("发送超量语音测试队列管理...")
        tasks = []
        
        for text in overflow_texts:
            task = asyncio.create_task(speech_system.say(text))
            tasks.append(task)
        
        # 等待所有任务完成
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        success_count = 0
        for i, result in enumerate(results):
            if isinstance(result, dict) and result.get("success"):
                success_count += 1
            elif isinstance(result, Exception):
                print(f"任务{i+1}异常: {result}")
            else:
                print(f"任务{i+1}失败: {result.get('message', '未知错误')}")
        
        print(f"✅ 队列溢出测试完成，成功播放 {success_count}/{len(overflow_texts)} 条")
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"队列溢出测试失败: {e}")


async def test_network_resilience():
    """测试网络连接异常处理"""
    print("\n🌐 测试网络连接异常处理...")
    
    try:
        # 创建错误的配置来模拟网络错误
        config = load_config("config.ini")
        
        # 创建临时错误配置
        class MockSpeechConfig:
            def __init__(self):
                self.app_id = config.speech.app_id
                self.api_key = config.speech.api_key
                self.api_secret = config.speech.api_secret
                self.notebook_ip = "192.168.999.999"  # 错误的IP
                self.speaker_port = 9889
        
        mock_config = MockSpeechConfig()
        speech_system = SpeechSystem(mock_config)
        
        # 尝试播放语音（应该TTS成功但网络发送失败）
        result = await speech_system.say("网络连接测试")
        
        # 应该TTS成功但网络发送失败
        if result["success"]:
            print("✅ 系统在网络错误情况下仍能正常处理（TTS成功）")
        else:
            print(f"⚠️ 网络错误测试结果: {result['message']}")
        
        # 停止语音系统
        speech_system.stop_speech_system()
        
    except Exception as e:
        logger.error(f"网络异常测试失败: {e}")


async def main():
    """主测试函数"""
    print("🔧 优化后语音输出系统测试")
    print("=" * 50)
    print("测试目标:")
    print("1. 解决语音重叠问题（顺序播放）")
    print("2. 解决声音抖动问题（队列管理）") 
    print("3. 解决音频设备错误（资源管理）")
    print("4. 测试中断功能")
    print("5. 测试队列溢出处理")
    print("6. 测试网络异常处理")
    print("=" * 50)
    
    # 确保笔记本扬声器服务器运行
    print("\n📋 测试前准备:")
    print("1. 确保笔记本上运行: python scripts/notebook_speaker_server.py")
    print("2. 网络连接正常: 192.168.3.7:9889")
    
    input("\n按回车键开始测试...")
    
    # 运行所有测试
    try:
        await test_sequential_speech()
        await asyncio.sleep(2)
        
        await test_interrupt_speech()
        await asyncio.sleep(2)
        
        await test_queue_overflow()
        await asyncio.sleep(2)
        
        await test_network_resilience()
        
        print("\n🎉 所有语音系统测试完成!")
        print("\n📊 测试总结:")
        print("- 如果听到清晰的顺序播放，说明重叠问题已解决")
        print("- 如果声音稳定无抖动，说明缓冲问题已解决")
        print("- 如果没有ALSA/PulseAudio错误，说明资源管理正常")
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")


if __name__ == "__main__":
    asyncio.run(main())