#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单语音测试 - 找出阻塞的真正原因
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from intelligence.speech import SpeechSystem

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_original_method():
    """测试原始的语音合成方法（不用队列）"""
    print("\n🔍 测试原始语音合成方法...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        # 直接调用内部方法，绕过队列
        print("📢 直接调用 _synthesize_and_play...")
        result = await speech_system._synthesize_and_play("原始方法测试")
        
        print(f"✅ 结果: {result}")
        
    except Exception as e:
        logger.error(f"原始方法测试失败: {e}")


async def test_tts_only():
    """只测试TTS合成，不发送网络"""
    print("\n🔍 测试纯TTS合成...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        # 生成文件名
        import time
        timestamp = int(time.time() * 1000)
        pcm_file = os.path.join(speech_system.output_dir, f"test_{timestamp}.pcm")
        
        print("📢 开始TTS合成...")
        success = await speech_system.tts_engine.synthesize_speech("TTS测试", pcm_file)
        
        print(f"✅ TTS合成结果: {success}")
        
        if success and os.path.exists(pcm_file):
            print(f"📁 文件生成成功: {pcm_file}")
            file_size = os.path.getsize(pcm_file)
            print(f"📊 文件大小: {file_size} 字节")
        else:
            print("❌ 文件生成失败")
        
    except Exception as e:
        logger.error(f"TTS测试失败: {e}")


async def test_network_only():
    """只测试网络发送，使用已存在的音频文件"""
    print("\n🔍 测试纯网络发送...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        # 创建一个小的测试音频文件
        test_audio = b'\x00\x01' * 1000  # 简单的测试数据
        test_file = os.path.join(speech_system.output_dir, "network_test.pcm")
        
        with open(test_file, 'wb') as f:
            f.write(test_audio)
        
        print("📢 开始网络发送...")
        success = await speech_system._send_audio_to_speaker(test_file)
        
        print(f"✅ 网络发送结果: {success}")
        
    except Exception as e:
        logger.error(f"网络发送测试失败: {e}")


async def main():
    """主测试函数"""
    print("🔧 简单语音测试 - 分析阻塞原因")
    print("=" * 50)
    
    # 1. 测试原始方法
    await test_original_method()
    
    # 2. 测试纯TTS
    await test_tts_only()
    
    # 3. 测试纯网络
    await test_network_only()
    
    print("\n🎉 简单测试完成!")


if __name__ == "__main__":
    asyncio.run(main())