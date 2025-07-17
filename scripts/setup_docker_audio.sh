#!/bin/bash
# Docker容器音频设置脚本

echo "=== Docker容器音频设置 ==="

# 检查PulseAudio环境
echo "1. 检查PulseAudio环境..."
echo "PULSE_SERVER: $PULSE_SERVER"
echo "PULSE_RUNTIME_PATH: $PULSE_RUNTIME_PATH"
echo "XDG_RUNTIME_DIR: $XDG_RUNTIME_DIR"

# 检查PulseAudio socket
echo -e "\n2. 检查PulseAudio socket..."
if [ -S "/run/user/1000/pulse/native" ]; then
    echo "✅ PulseAudio socket存在"
else
    echo "❌ PulseAudio socket不存在"
fi

# 检查音频设备
echo -e "\n3. 检查音频设备..."
echo "可用的音频设备:"
python3 -c "
import sounddevice as sd
devices = sd.query_devices()
for i, device in enumerate(devices):
    if device['max_output_channels'] > 0:
        print(f'  [{i}] {device[\"name\"]}')
        print(f'      通道: {device[\"max_output_channels\"]}, 采样率: {device[\"default_samplerate\"]}')
"

# 尝试创建pulse设备访问
echo -e "\n4. 尝试设置PulseAudio客户端..."

# 设置PulseAudio客户端配置
export PULSE_SERVER="unix:/run/user/1000/pulse/native"
export PULSE_RUNTIME_PATH="/run/user/1000/pulse"

# 测试PulseAudio连接
echo "测试PulseAudio连接..."
timeout 5 python3 -c "
import sounddevice as sd
import os

# 强制重新查询设备
sd._terminate()
sd._initialize()

devices = sd.query_devices()
pulse_found = False
for i, device in enumerate(devices):
    if 'pulse' in device['name'].lower():
        print(f'找到pulse设备: [{i}] {device[\"name\"]}')
        pulse_found = True
        break

if not pulse_found:
    print('未找到pulse设备')
"

echo -e "\n5. 音频设置完成"