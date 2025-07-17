#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker音频问题修复脚本
通过环境变量强制使用特定设备
"""

import os
import sys
import sounddevice as sd

def fix_docker_audio():
    """修复Docker音频问题"""
    print("🔧 Docker音频修复")
    print("=" * 50)
    
    # 强制sounddevice使用PulseAudio
    os.environ['SDL_AUDIODRIVER'] = 'pulse'
    os.environ['PULSE_RUNTIME_PATH'] = '/run/user/1000/pulse'
    os.environ['PULSE_SERVER'] = 'unix:/run/user/1000/pulse/native'
    
    # 重新初始化sounddevice
    sd._terminate()
    sd._initialize()
    
    print("1. 检查修复后的设备列表...")
    devices = sd.query_devices()
    
    pulse_devices = []
    for i, device in enumerate(devices):
        if device['max_output_channels'] > 0:
            print(f"  [{i}] {device['name']}")
            if 'pulse' in device['name'].lower() or 'default' in device['name'].lower():
                pulse_devices.append(i)
    
    print(f"\n2. 找到 {len(pulse_devices)} 个potential PulseAudio设备")
    
    if pulse_devices:
        print("✅ 修复成功！")
        return True
    else:
        print("❌ 修复失败，没有找到PulseAudio设备")
        return False

if __name__ == "__main__":
    fix_docker_audio()