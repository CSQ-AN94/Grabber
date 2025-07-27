# USB音频设备配置指南

## 概述

本文档记录了在Jetson Orin NX上成功配置和使用Generalplus USB Audio Device的完整过程，包括硬件规格、测试方法和系统集成方案。

## 设备规格

### 硬件信息
- **制造商**: Generalplus Technology Inc.
- **产品ID**: 1b3f:2008
- **设备名称**: USB Audio Device
- **连接方式**: USB 1.1 Full Speed
- **供电**: 总线供电 (100mA)
- **ALSA设备标识**: card 2, device 0 (hw:2,0)

### 音频规格

#### 录音功能 (麦克风)
- **格式**: S16_LE (16位小端序)
- **声道数**: 1 (单声道)
- **采样率**: 44100Hz, 48000Hz
- **位深**: 16位
- **状态**: ✅ 完全正常

#### 播放功能 (扬声器)
- **格式**: S16_LE (16位小端序) **仅支持此格式**
- **声道数**: 2 (立体声: FL FR)
- **采样率**: 44100Hz, 48000Hz  
- **位深**: 16位
- **状态**: ✅ 完全正常
- **重要限制**: 不支持32位格式，必须使用16位

## 成功的测试命令

### 录音测试
```bash
# 48kHz单声道录音3秒
arecord -D hw:2,0 -f S16_LE -r 48000 -c 1 -d 3 /tmp/test_mic_48k.wav

# 44.1kHz录音（备选）
arecord -D hw:2,0 -f S16_LE -r 44100 -c 1 -d 3 /tmp/test_mic_44k.wav
```

### 播放测试
```bash
# 生成16位测试音调（重要：必须指定-b 16）
sox -n -r 48000 -c 2 -b 16 /tmp/test_tone_16bit.wav synth 2 sine 440

# 播放测试音调
aplay -D hw:2,0 /tmp/test_tone_16bit.wav

# 将录音转换为立体声并播放
sox /tmp/test_mic_48k.wav -c 2 -b 16 /tmp/test_mic_stereo_16bit.wav
aplay -D hw:2,0 /tmp/test_mic_stereo_16bit.wav

# 使用speaker-test播放测试音调
speaker-test -D hw:2,0 -r 48000 -c 2 -t sine -f 440 -s 1
```

### 格式验证
```bash
# 强制指定格式播放
aplay -D hw:2,0 -f S16_LE -r 48000 -c 2 /tmp/test_tone_16bit.wav
```

## Docker容器集成

### 当前状态 ✅ 完全验证
USB音频设备在Docker容器内完全正常工作：
- ✅ `aplay -l` 和 `arecord -l` 显示设备
- ✅ Python sounddevice检测到设备ID 24: "USB Audio Device"
- ✅ 容器内ALSA录音和播放功能正常
- ✅ 容器内录音质量与主机一致
- ✅ 容器内播放质量与主机一致

### Docker配置要求
```yaml
# docker-compose.yml
services:
  grabber_dev:
    privileged: true
    devices:
      - /dev/snd:/dev/snd  # 音频设备挂载
    # 其他配置...
```

## Python集成建议

### sounddevice设备信息
根据容器内实际测试，USB音频设备在sounddevice中的完整信息为：
```python
# devices[24] 的完整信息
{
    'name': 'USB Audio Device: - (hw:2,0)', 
    'index': 24, 
    'hostapi': 0, 
    'max_input_channels': 1, 
    'max_output_channels': 2, 
    'default_low_input_latency': 0.008684807256235827, 
    'default_low_output_latency': 0.008684807256235827, 
    'default_high_input_latency': 0.034829931972789115, 
    'default_high_output_latency': 0.034829931972789115, 
    'default_samplerate': 44100.0
}
```

**关键参数解读：**
- **设备索引**: 24
- **输入通道**: 1 (单声道麦克风)
- **输出通道**: 2 (立体声扬声器)
- **低延迟**: ~8.7ms (录音和播放)
- **高延迟**: ~34.8ms (录音和播放)
- **默认采样率**: 44100Hz

### 推荐的音频参数
```python
# 录音参数
RECORD_PARAMS = {
    'device': 24,  # USB Audio Device
    'samplerate': 48000,
    'channels': 1,
    'dtype': 'int16'  # 对应S16_LE
}

# 播放参数
PLAYBACK_PARAMS = {
    'device': 24,  # USB Audio Device
    'samplerate': 48000,
    'channels': 2,
    'dtype': 'int16'  # 必须是int16，不支持float32
}
```

### 格式转换注意事项
1. **必须使用16位格式**: 设备不支持32位或float格式
2. **录音单声道，播放立体声**: 录音为单声道，播放需要立体声
3. **推荐48kHz**: 虽然支持44.1kHz，但48kHz更标准

## 故障排除

### 常见问题和解决方案

#### 1. 播放格式错误
```
错误: aplay: set_params:1352: Sample format non available
解决: 确保音频文件是16位S16_LE格式，使用sox时添加-b 16参数
```

#### 2. 设备不识别
```bash
# 检查USB连接
lsusb | grep -i audio

# 检查ALSA设备
aplay -l | grep -i usb
arecord -l | grep -i usb
```

#### 3. Docker容器内访问问题
```bash
# 确保容器有音频设备访问权限
docker compose run --rm grabber_dev aplay -l
```

## 系统集成路线图

### 阶段1: 基础音频功能 ✅
- [x] USB音频设备硬件测试
- [x] ALSA层面录音/播放验证
- [x] Docker容器音频访问

### 阶段2: Python音频库集成
- [ ] 修改smart_microphone.py优先使用USB设备
- [ ] 修改speech_local.py支持USB音频播放
- [ ] 创建USB音频专用配置

### 阶段3: Gemini Live API集成
- [ ] 配置USB音频用于Gemini实时对话
- [ ] 测试端到端语音交互
- [ ] 性能优化和延迟调整

## 技术规格总结

| 项目 | 录音 | 播放 |
|------|------|------|
| 格式 | S16_LE | S16_LE |
| 声道 | 1 (单声道) | 2 (立体声) |
| 采样率 | 44.1/48 kHz | 44.1/48 kHz |
| 位深 | 16位 | 16位 |
| ALSA设备 | hw:2,0 | hw:2,0 |
| sounddevice ID | 24 | 24 |

## 验证状态

### Jetson主机测试 ✅
- ✅ **硬件连接**: USB设备正确识别 (1b3f:2008)
- ✅ **ALSA录音**: 48kHz单声道录音完全正常
- ✅ **ALSA播放**: 48kHz立体声播放完全正常  
- ✅ **格式兼容**: 16位S16_LE格式完全支持

### Docker容器测试 ✅
- ✅ **设备访问**: 容器内设备完全可访问
- ✅ **ALSA功能**: 录音和播放与主机一致
- ✅ **Python sounddevice**: 设备ID 24正确识别
- ✅ **延迟特性**: 低延迟~8.7ms，高延迟~34.8ms
- ✅ **音频质量**: 与主机完全一致

### 待实施功能
- ⏳ **Python集成**: 智能麦克风和TTS集成
- ⏳ **Gemini集成**: 实时语音对话功能

---

**文档创建时间**: 2025-01-26  
**测试平台**: Jetson Orin NX + Ubuntu 22.04 + Docker  
**验证状态**: 主机和容器完全正常  
**下一步**: Python音频库集成