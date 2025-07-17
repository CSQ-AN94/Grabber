#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
扬声器系统测试脚本
用于独立测试语音输出链路：Jetson SpeechSystem -> 笔记本扬声器
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
from intelligence.speech import SpeechSystem

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_speech_synthesis():
    """测试语音合成功能（不发送网络）"""
    print("🗣️ 测试语音合成功能...")
    
    try:
        # 加载配置
        config = load_config("config.ini")
        
        # 创建语音系统（不发送到网络）
        speech_system = SpeechSystem(config.speech)
        
        test_texts = [
            "语音合成系统测试开始",
            "这是第二条测试语音",
            "语音合成系统工作正常"
        ]
        
        for i, text in enumerate(test_texts, 1):
            print(f"\n测试 {i}: {text}")
            
            # 语音合成但不发送到网络扬声器
            result = await speech_system.say(text, send_to_speaker=False)
            
            if result["success"]:
                print("✅ 语音合成成功")
            else:
                print(f"❌ 语音合成失败: {result['message']}")
            
            await asyncio.sleep(1)
        
        print("\n🗣️ 语音合成测试完成")
        
    except Exception as e:
        logger.error(f"语音合成测试失败: {e}")


async def test_network_speaker():
    """测试网络扬声器功能"""
    print("🔊 测试网络扬声器功能...")
    
    try:
        # 加载配置
        config = load_config("config.ini")
        
        print(f"目标扬声器: {config.speech.notebook_ip}:{config.speech.speaker_port}")
        print("请确保在笔记本上运行扬声器服务器:")
        print("  python sensors/speaker_thread.py")
        print("或者运行完整的音频服务器:")
        print("  python sensors/audio_server_tcp.py")
        
        # 创建语音系统
        speech_system = SpeechSystem(config.speech)
        
        test_texts = [
            "网络扬声器测试开始",
            "正在通过网络发送语音",
            "网络扬声器测试完成"
        ]
        
        for i, text in enumerate(test_texts, 1):
            print(f"\n测试 {i}: {text}")
            
            # 语音合成并发送到网络扬声器
            result = await speech_system.say(text, send_to_speaker=True)
            
            if result["success"]:
                print("✅ 网络语音发送成功")
            else:
                print(f"❌ 网络语音发送失败: {result['message']}")
            
            await asyncio.sleep(2)
        
        print("\n🔊 网络扬声器测试完成")
        
    except Exception as e:
        logger.error(f"网络扬声器测试失败: {e}")


async def test_tts_api():
    """测试TTS API连接"""
    print("🌐 测试TTS API连接...")
    
    try:
        # 加载配置
        config = load_config("config.ini")
        
        print(f"使用TTS API配置:")
        print(f"  App ID: {config.speech.app_id}")
        print(f"  API Key: {config.speech.api_key[:8]}...")
        
        # 创建语音系统
        speech_system = SpeechSystem(config.speech)
        
        # 简单的API测试
        result = await speech_system.say("TTS API连接测试", send_to_speaker=False)
        
        if result["success"]:
            print("✅ TTS API连接正常")
        else:
            print(f"❌ TTS API连接失败: {result['message']}")
            
    except Exception as e:
        logger.error(f"TTS API测试失败: {e}")


async def test_complete_pipeline():
    """测试完整的语音输出流水线"""
    print("🔄 测试完整语音输出流水线...")
    
    try:
        config = load_config("config.ini")
        speech_system = SpeechSystem(config.speech)
        
        print("开始完整流水线测试:")
        print("1. TTS API语音合成")
        print("2. 网络传输到笔记本扬声器")
        print("3. 笔记本播放音频")
        
        result = await speech_system.say("完整语音流水线测试成功")
        
        if result["success"]:
            print("✅ 完整流水线测试成功")
            return True
        else:
            print(f"❌ 完整流水线测试失败: {result['message']}")
            return False
            
    except Exception as e:
        logger.error(f"完整流水线测试失败: {e}")
        return False


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="扬声器系统测试")
    parser.add_argument("--synthesis-only", action="store_true", help="仅测试语音合成")
    parser.add_argument("--network-only", action="store_true", help="仅测试网络扬声器")
    parser.add_argument("--api-only", action="store_true", help="仅测试TTS API")
    parser.add_argument("--complete", action="store_true", help="完整流水线测试")
    
    args = parser.parse_args()
    
    print("=" * 50)
    print("扬声器系统测试")
    print("=" * 50)
    
    async def run_tests():
        if args.synthesis_only:
            await test_speech_synthesis()
        elif args.network_only:
            await test_network_speaker()
        elif args.api_only:
            await test_tts_api()
        elif args.complete:
            await test_complete_pipeline()
        else:
            # 默认运行所有测试
            await test_tts_api()
            await asyncio.sleep(1)
            await test_speech_synthesis()
            await asyncio.sleep(1)
            await test_network_speaker()
    
    asyncio.run(run_tests())


if __name__ == "__main__":
    main()