# 音频系统测试指南

本目录包含完整的音频系统测试脚本，用于验证语音输入输出链路。

## 架构概述

**音频输入链路**: 笔记本麦克风 → TCP客户端 → Jetson MicrophoneThread (端口8888)
**音频输出链路**: Jetson SpeechSystem → TCP客户端 → 笔记本扬声器服务器 (端口9889)

## 测试脚本

### 1. 麦克风系统测试 (`test_microphone_system.py`)

测试音频输入链路，验证从笔记本麦克风到Jetson的音频传输。

**在Jetson容器内运行:**
```bash
# 基本麦克风服务器测试
python scripts/test_microphone_system.py

# 音频质量分析测试
python scripts/test_microphone_system.py --quality
```

**在笔记本上运行客户端:**
```bash
# 发送麦克风音频到Jetson
python sensors/audio_client_tcp.py --host 192.168.3.10

# 列出可用音频设备
python sensors/audio_client_tcp.py --list-devices
```

### 2. 扬声器系统测试 (`test_speaker_system.py`)

测试语音输出链路，验证从Jetson语音合成到笔记本扬声器的音频传输。

**在Jetson容器内运行:**
```bash
# 仅测试TTS API连接
python scripts/test_speaker_system.py --api-only

# 仅测试语音合成（不网络传输）
python scripts/test_speaker_system.py --synthesis-only

# 仅测试网络扬声器传输
python scripts/test_speaker_system.py --network-only

# 完整流水线测试
python scripts/test_speaker_system.py --complete

# 运行所有测试
python scripts/test_speaker_system.py
```

**在笔记本上运行扬声器服务器:**
```bash
# 方法1: 使用专用的笔记本扬声器服务器（推荐）
python scripts/notebook_speaker_server.py

# 方法2: 测试音频播放功能
python scripts/notebook_speaker_server.py --test-audio

# 方法3: 使用项目内的扬声器线程（如果可用）
python sensors/speaker_thread.py
```

## 测试步骤

### 第一步：验证麦克风输入
1. 在Jetson容器内运行: `python scripts/test_microphone_system.py`
2. 在笔记本上运行: `python sensors/audio_client_tcp.py --host 192.168.3.10`
3. 对着笔记本麦克风说话，观察Jetson控制台的音频数据接收情况

### 第二步：验证扬声器输出
1. 在笔记本上运行: `python scripts/notebook_speaker_server.py`
2. 在Jetson容器内运行: `python scripts/test_speaker_system.py --complete`
3. 确认笔记本扬声器能够播放来自Jetson的合成语音

### 第三步：端到端测试
1. 同时启动麦克风和扬声器测试
2. 验证完整的双向音频通路
3. 为Gemini Live API集成做好准备

## 故障排除

### 麦克风问题
- **连接失败**: 检查网络连通性和端口8888是否开放
- **无音频数据**: 检查笔记本麦克风权限和设备选择
- **音频质量差**: 使用`--quality`参数分析音频数据统计信息

### 扬声器问题
- **TTS API失败**: 检查config.ini中的iFlytek API配置
- **网络传输失败**: 检查笔记本IP和端口9889连通性
- **无声音播放**: 检查笔记本扬声器设备和音量设置

### 配置问题
- **配置文件错误**: 验证config.ini中的[speech]配置段
- **IP地址错误**: 确认notebook_ip设置为笔记本的实际IP
- **端口冲突**: 确保8888和9889端口未被其他程序占用

## 预期输出示例

### 麦克风测试成功输出
```
🎤 启动麦克风服务器测试...
启动麦克风服务器，监听端口 8888
等待笔记本客户端连接...
✅ 音频队列: 45 帧, 新增: 15 帧, 累计: 23.45 KB
```

### 扬声器测试成功输出
```
🔊 测试网络扬声器功能...
目标扬声器: 192.168.3.7:9889
测试 1: 网络扬声器测试开始
✅ 网络语音发送成功
```

## 配置文件要求

确保`config.ini`包含正确的语音配置:
```ini
[speech]
notebook_ip = 192.168.3.7
speaker_port = 9889
app_id = aeb60378
api_key = e248b59b7b21d7291702b7808ba07257
api_secret = MjQ1ZmM3MjkwNmEzZTQyN2ZiNTYxN2Ey
```