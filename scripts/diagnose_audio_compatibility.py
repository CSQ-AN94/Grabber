#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频设备兼容性诊断脚本
测试不同音频设备和采样率的兼容性
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


def test_audio_devices():
    """测试所有可用的音频设备"""
    print("=== 音频设备兼容性诊断 ===\n")
    
    # 1. 列出所有设备
    print("1. 可用音频设备:")
    devices = sd.query_devices()
    for i, device in enumerate(devices):
        print(f"   [{i}] {device['name']}")
        print(f"       输入通道: {device['max_input_channels']}")
        print(f"       输出通道: {device['max_output_channels']}")
        print(f"       默认采样率: {device['default_samplerate']}")
        print()
    
    # 2. 获取默认设备
    default_input = sd.default.device[0]
    default_output = sd.default.device[1]
    print(f"2. 默认输入设备: [{default_input}] {devices[default_input]['name']}")
    print(f"   默认输出设备: [{default_output}] {devices[default_output]['name']}\n")
    
    # 3. 测试不同采样率
    test_sample_rates = [8000, 16000, 22050, 44100, 48000]
    print("3. 采样率兼容性测试:")
    
    for sample_rate in test_sample_rates:
        print(f"\n   测试采样率 {sample_rate} Hz:")
        
        # 测试输出
        try:
            test_audio = np.sin(2 * np.pi * 440 * np.linspace(0, 0.1, int(sample_rate * 0.1)))
            sd.check_output_settings(device=default_output, samplerate=sample_rate)
            print(f"     ✅ 输出支持 {sample_rate} Hz")
        except Exception as e:
            print(f"     ❌ 输出不支持 {sample_rate} Hz: {e}")
        
        # 测试输入
        try:
            sd.check_input_settings(device=default_input, samplerate=sample_rate)
            print(f"     ✅ 输入支持 {sample_rate} Hz")
        except Exception as e:
            print(f"     ❌ 输入不支持 {sample_rate} Hz: {e}")
    
    # 4. 测试实际播放和录音
    print(f"\n4. 实际播放测试 (默认设备):")
    try:
        # 生成测试音频 (440Hz 正弦波，0.5秒)
        duration = 0.5
        sample_rate = int(devices[default_output]['default_samplerate'])
        test_audio = 0.3 * np.sin(2 * np.pi * 440 * np.linspace(0, duration, int(sample_rate * duration)))
        
        print(f"   播放 440Hz 测试音频 ({sample_rate} Hz 采样率)...")
        sd.play(test_audio, samplerate=sample_rate)
        sd.wait()
        print("   ✅ 播放测试成功")
        
    except Exception as e:
        print(f"   ❌ 播放测试失败: {e}")
    
    print(f"\n5. 实际录音测试 (默认设备):")
    try:
        sample_rate = int(devices[default_input]['default_samplerate'])
        duration = 1.0
        
        print(f"   录音 {duration} 秒 ({sample_rate} Hz 采样率)...")
        recording = sd.rec(int(duration * sample_rate), 
                         samplerate=sample_rate, 
                         channels=1, 
                         device=default_input)
        sd.wait()
        
        max_amplitude = np.max(np.abs(recording))
        print(f"   ✅ 录音测试成功，最大幅度: {max_amplitude:.4f}")
        
        if max_amplitude < 0.001:
            print("   ⚠️  录音幅度很低，可能没有检测到声音输入")
        
    except Exception as e:
        print(f"   ❌ 录音测试失败: {e}")


def test_specific_device_sample_rate(device_id, sample_rate, test_type='output'):
    """测试特定设备和采样率的组合"""
    try:
        if test_type == 'output':
            sd.check_output_settings(device=device_id, samplerate=sample_rate)
            # 实际播放测试
            duration = 0.2
            test_audio = 0.3 * np.sin(2 * np.pi * 440 * np.linspace(0, duration, int(sample_rate * duration)))
            sd.play(test_audio, samplerate=sample_rate, device=device_id)
            sd.wait()
        else:
            sd.check_input_settings(device=device_id, samplerate=sample_rate)
            # 实际录音测试
            duration = 0.5
            recording = sd.rec(int(duration * sample_rate), 
                             samplerate=sample_rate, 
                             channels=1, 
                             device=device_id)
            sd.wait()
        
        return True, "成功"
    except Exception as e:
        return False, str(e)


def find_best_audio_settings():
    """寻找最佳音频设备和采样率配置"""
    print("\n=== 寻找最佳音频配置 ===\n")
    
    devices = sd.query_devices()
    test_sample_rates = [16000, 44100, 48000, 22050]  # 优先测试16000Hz (Gemini Live需要)
    
    best_output = None
    best_input = None
    
    # 寻找最佳输出设备
    print("寻找最佳输出设备配置:")
    for device_id, device in enumerate(devices):
        if device['max_output_channels'] > 0:
            print(f"\n  测试设备 [{device_id}] {device['name']}:")
            for sample_rate in test_sample_rates:
                success, message = test_specific_device_sample_rate(device_id, sample_rate, 'output')
                if success:
                    print(f"    ✅ {sample_rate} Hz - 支持")
                    if not best_output:
                        best_output = (device_id, sample_rate, device['name'])
                else:
                    print(f"    ❌ {sample_rate} Hz - {message}")
    
    # 寻找最佳输入设备
    print("\n寻找最佳输入设备配置:")
    for device_id, device in enumerate(devices):
        if device['max_input_channels'] > 0:
            print(f"\n  测试设备 [{device_id}] {device['name']}:")
            for sample_rate in test_sample_rates:
                success, message = test_specific_device_sample_rate(device_id, sample_rate, 'input')
                if success:
                    print(f"    ✅ {sample_rate} Hz - 支持")
                    if not best_input:
                        best_input = (device_id, sample_rate, device['name'])
                else:
                    print(f"    ❌ {sample_rate} Hz - {message}")
    
    # 输出推荐配置
    print(f"\n=== 推荐配置 ===")
    if best_output:
        device_id, sample_rate, device_name = best_output
        print(f"推荐输出设备: [{device_id}] {device_name}")
        print(f"推荐输出采样率: {sample_rate} Hz")
    else:
        print("❌ 未找到可用的输出设备")
    
    if best_input:
        device_id, sample_rate, device_name = best_input
        print(f"推荐输入设备: [{device_id}] {device_name}")
        print(f"推荐输入采样率: {sample_rate} Hz")
    else:
        print("❌ 未找到可用的输入设备")
    
    return best_output, best_input


def main():
    """主函数"""
    try:
        print("🔍 开始音频设备兼容性诊断...")
        
        # 基础设备测试
        test_audio_devices()
        
        # 寻找最佳配置
        best_output, best_input = find_best_audio_settings()
        
        # 生成配置建议
        print(f"\n=== 配置建议 ===")
        if best_output or best_input:
            print("建议在代码中使用以下配置:")
            if best_output:
                device_id, sample_rate, _ = best_output
                print(f"sd.default.device[1] = {device_id}  # 输出设备")
                print(f"output_sample_rate = {sample_rate}")
            if best_input:
                device_id, sample_rate, _ = best_input
                print(f"sd.default.device[0] = {device_id}  # 输入设备")
                print(f"input_sample_rate = {sample_rate}")
        else:
            print("❌ 音频系统可能有问题，建议检查驱动和权限")
        
        print(f"\n🎉 诊断完成！")
        
    except Exception as e:
        logger.error(f"诊断过程中发生错误: {e}")
        print(f"❌ 诊断失败: {e}")


if __name__ == "__main__":
    main()