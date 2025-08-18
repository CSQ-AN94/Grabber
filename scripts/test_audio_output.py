#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试容器内音频输出设备
"""

import sounddevice as sd
import pyaudio
import numpy as np
import time

def test_sounddevice_devices():
    """测试sounddevice设备列表"""
    print("=== SoundDevice设备信息 ===")
    
    try:
        devices = sd.query_devices()
        print("所有设备:")
        for i, device in enumerate(devices):
            if device['max_output_channels'] > 0:
                print(f"  输出设备{i}: {device['name']} - {device['default_samplerate']}Hz")
                print(f"    最大输出通道: {device['max_output_channels']}")
        
        # 获取默认输出设备
        try:
            default_out = sd.query_devices(kind='output')
            print(f"\n默认输出设备: {default_out['name']}")
        except Exception as e:
            print(f"\n无法获取默认输出设备: {e}")
            
        return True
    except Exception as e:
        print(f"SoundDevice设备查询失败: {e}")
        return False

def test_pyaudio_output_devices():
    """测试PyAudio输出设备"""
    print("\n=== PyAudio输出设备 ===")
    
    try:
        p = pyaudio.PyAudio()
        output_devices = []
        
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info['maxOutputChannels'] > 0:
                output_devices.append((i, info))
                print(f"  输出设备{i}: {info['name']} - {info['defaultSampleRate']}Hz")
        
        p.terminate()
        return output_devices
    except Exception as e:
        print(f"PyAudio输出设备查询失败: {e}")
        return []

def test_sounddevice_playback(device_id=None):
    """测试sounddevice播放功能"""
    print(f"\n=== 测试SoundDevice播放 (设备{device_id if device_id is not None else '默认'}) ===")
    
    try:
        # 生成1秒440Hz正弦波测试音
        duration = 1.0
        sample_rate = 16000
        frequency = 440
        t = np.linspace(0, duration, int(sample_rate * duration))
        test_audio = 0.3 * np.sin(2 * np.pi * frequency * t).astype(np.float32)
        
        print(f"播放1秒测试音 (440Hz, {sample_rate}Hz采样率)...")
        
        if device_id is not None:
            sd.play(test_audio, samplerate=sample_rate, device=device_id, blocking=True)
        else:
            sd.play(test_audio, samplerate=sample_rate, blocking=True)
            
        print("  ✓ 播放成功")
        return True
        
    except Exception as e:
        print(f"  ✗ 播放失败: {e}")
        return False

def test_pyaudio_playback(device_id):
    """测试PyAudio播放功能"""
    print(f"\n=== 测试PyAudio播放 (设备{device_id}) ===")
    
    try:
        # 生成1秒测试音
        duration = 1.0
        sample_rate = 16000
        frequency = 440
        t = np.linspace(0, duration, int(sample_rate * duration))
        test_audio = (0.3 * np.sin(2 * np.pi * frequency * t) * 32767).astype(np.int16)
        
        p = pyaudio.PyAudio()
        
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=sample_rate,
            output=True,
            output_device_index=device_id
        )
        
        print(f"播放1秒测试音...")
        stream.write(test_audio.tobytes())
        
        stream.stop_stream()
        stream.close()
        p.terminate()
        
        print("  ✓ PyAudio播放成功")
        return True
        
    except Exception as e:
        print(f"  ✗ PyAudio播放失败: {e}")
        return False

def find_working_output_devices():
    """查找可用的输出设备"""
    print("\n=== 查找可用输出设备 ===")
    
    working_sd_devices = []
    working_pa_devices = []
    
    # 测试sounddevice设备
    try:
        devices = sd.query_devices()
        for i, device in enumerate(devices):
            if device['max_output_channels'] > 0:
                print(f"测试sounddevice设备{i}: {device['name']}")
                if test_sounddevice_playback(i):
                    working_sd_devices.append(i)
                time.sleep(0.5)  # 避免设备冲突
    except Exception as e:
        print(f"SoundDevice设备测试失败: {e}")
    
    # 测试PyAudio设备  
    output_devices = test_pyaudio_output_devices()
    for device_id, info in output_devices:
        print(f"测试PyAudio设备{device_id}: {info['name']}")
        if test_pyaudio_playback(device_id):
            working_pa_devices.append(device_id)
        time.sleep(0.5)
    
    return working_sd_devices, working_pa_devices

def main():
    """主测试函数"""
    print("容器内音频输出设备测试")
    print("=" * 40)
    
    # 1. 查询设备信息
    sd_ok = test_sounddevice_devices()
    pa_devices = test_pyaudio_output_devices()
    
    # 2. 测试默认设备
    print("\n测试默认输出设备...")
    default_ok = test_sounddevice_playback()
    
    # 3. 查找所有可用设备
    working_sd, working_pa = find_working_output_devices()
    
    # 总结结果
    print("\n" + "=" * 40)
    print("测试结果:")
    print(f"  SoundDevice设备查询: {'✓' if sd_ok else '✗'}")
    print(f"  默认设备播放: {'✓' if default_ok else '✗'}")
    print(f"  可用SoundDevice设备: {working_sd}")
    print(f"  可用PyAudio设备: {working_pa}")
    
    if working_sd:
        print(f"\n💡 建议修改speech.py使用SoundDevice设备: {working_sd[0]}")
    elif working_pa:
        print(f"\n💡 建议修改speech.py使用PyAudio设备: {working_pa[0]}")
    else:
        print("\n❌ 未找到可用的输出设备")

if __name__ == "__main__":
    main()