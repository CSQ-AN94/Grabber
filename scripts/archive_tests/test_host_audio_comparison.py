#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
宿主机vs容器音频对比测试
"""

import sys
import os
import sounddevice as sd
import numpy as np
import asyncio
import logging

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from intelligence.speech_local import LocalSpeechSystem

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_host_audio():
    """在宿主机上测试音频"""
    print("=== 宿主机音频测试 ===\n")
    
    config = load_config("config.ini")
    speech_system = LocalSpeechSystem(config.speech)
    
    test_text = "宿主机音频测试"
    print(f"🎵 合成并播放: {test_text}")
    
    result = await speech_system.say(test_text)
    
    if result["success"]:
        print("✅ 宿主机音频播放成功")
        print("👂 你应该能听到这个音频")
    else:
        print(f"❌ 宿主机音频播放失败: {result['message']}")


def test_device_priorities():
    """测试设备优先级"""
    print("\n=== 设备优先级分析 ===\n")
    
    devices = sd.query_devices()
    
    print("所有输出设备:")
    for i, device in enumerate(devices):
        if device['max_output_channels'] > 0:
            print(f"  [{i}] {device['name']}")
            print(f"      通道: {device['max_output_channels']}, 采样率: {device['default_samplerate']}")
            
            # 检查设备名称模式
            is_hdmi = "HDMI" in device['name']
            is_hda = "sof-hda-dsp" in device['name']
            is_pulse = "pulse" in device['name']
            is_default = "default" in device['name']
            
            priority = "低" if is_hdmi else "高" if (is_pulse or is_default or is_hda) else "中"
            print(f"      优先级: {priority}")
            
            if is_hdmi:
                print(f"      注意: HDMI设备可能没有连接音频输出")
            
            print()


async def main():
    """主函数"""
    print("🔧 宿主机vs容器音频对比测试")
    print("=" * 50)
    
    try:
        # 1. 设备分析
        test_device_priorities()
        
        # 2. 宿主机测试
        await test_host_audio()
        
        print("\n🎯 建议:")
        print("1. 如果宿主机音频正常，说明设备选择有问题")
        print("2. Docker容器应该优先选择非HDMI设备")
        print("3. 可能需要配置PulseAudio转发")
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")
        print(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())