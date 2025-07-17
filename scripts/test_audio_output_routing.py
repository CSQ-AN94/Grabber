#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频输出路由测试
测试不同设备的音频输出路由
"""

import sys
import os
import sounddevice as sd
import numpy as np
import logging

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_audio_output_routing():
    """测试不同设备的音频输出路由"""
    print("=== 音频输出路由测试 ===\n")
    
    # 列出所有输出设备
    devices = sd.query_devices()
    output_devices = []
    
    for i, device in enumerate(devices):
        if device['max_output_channels'] > 0:
            output_devices.append((i, device))
            print(f"输出设备 [{i}]: {device['name']}")
            print(f"  最大输出通道: {device['max_output_channels']}")
            print(f"  默认采样率: {device['default_samplerate']}")
    
    print(f"\n找到 {len(output_devices)} 个输出设备")
    
    # 生成测试音频 (440Hz 正弦波)
    duration = 1.0
    sample_rate = 44100
    frequency = 440
    
    t = np.linspace(0, duration, int(sample_rate * duration))
    test_audio = 0.3 * np.sin(2 * np.pi * frequency * t)
    
    # 测试每个设备
    for device_id, device in output_devices:
        print(f"\n测试设备 [{device_id}]: {device['name']}")
        
        try:
            # 检查设备支持的采样率
            supported_rates = []
            for rate in [16000, 22050, 44100, 48000]:
                try:
                    sd.check_output_settings(device=device_id, samplerate=rate)
                    supported_rates.append(rate)
                except:
                    pass
            
            print(f"  支持的采样率: {supported_rates}")
            
            if not supported_rates:
                print("  ❌ 无支持的采样率")
                continue
                
            # 使用支持的采样率播放
            use_rate = supported_rates[0] if 44100 not in supported_rates else 44100
            
            # 重新生成适合采样率的音频
            if use_rate != sample_rate:
                t = np.linspace(0, duration, int(use_rate * duration))
                device_audio = 0.3 * np.sin(2 * np.pi * frequency * t)
            else:
                device_audio = test_audio
            
            print(f"  🔊 播放测试音频到设备 [{device_id}] @ {use_rate}Hz")
            print(f"  请听是否有声音输出...")
            
            # 播放音频
            sd.play(device_audio, samplerate=use_rate, device=device_id)
            sd.wait()
            
            print(f"  ✅ 播放完成")
            
        except Exception as e:
            print(f"  ❌ 播放失败: {e}")
    
    print("\n=== 测试完成 ===")
    print("如果你听到了音频，说明对应的设备是正确的输出设备")


def test_current_speech_system_routing():
    """测试当前语音系统使用的设备路由"""
    print("\n=== 当前语音系统路由测试 ===\n")
    
    from intelligence.speech_local import LocalAudioPlayer
    
    # 创建音频播放器
    player = LocalAudioPlayer()
    
    print(f"当前选择的输出设备: [{player.output_device}]")
    print(f"当前使用的采样率: {player.output_sample_rate}Hz")
    
    # 获取设备信息
    devices = sd.query_devices()
    device_info = devices[player.output_device]
    print(f"设备名称: {device_info['name']}")
    print(f"设备通道数: {device_info['max_output_channels']}")
    print(f"设备默认采样率: {device_info['default_samplerate']}")
    
    # 创建测试音频文件
    duration = 1.0
    sample_rate = 16000  # TTS使用的采样率
    frequency = 440
    
    t = np.linspace(0, duration, int(sample_rate * duration))
    test_audio = 0.3 * np.sin(2 * np.pi * frequency * t)
    
    # 转换为16位PCM并保存
    audio_int16 = (test_audio * 32767).astype(np.int16)
    test_file = "/tmp/test_audio.pcm"
    
    with open(test_file, 'wb') as f:
        f.write(audio_int16.tobytes())
    
    print(f"\n🔊 使用当前语音系统播放测试音频...")
    print(f"请听是否有声音输出...")
    
    # 使用当前语音系统播放
    success = player.play_pcm_file_sync(test_file)
    
    if success:
        print("✅ 播放成功")
    else:
        print("❌ 播放失败")
    
    # 清理
    os.remove(test_file)


def main():
    """主函数"""
    print("🔧 音频输出路由测试")
    print("=" * 50)
    
    try:
        # 1. 测试所有设备的路由
        test_audio_output_routing()
        
        # 2. 测试当前语音系统的路由
        test_current_speech_system_routing()
        
        print("\n🎯 测试完成！")
        print("根据测试结果，我们可以确定哪个设备能够正确输出音频")
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")
        print(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    main()