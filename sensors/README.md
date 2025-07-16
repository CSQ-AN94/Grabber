# 传感器模块

包含相机、麦克风、扬声器等传感器的线程管理和网络音频流系统。

## 文件结构

```
sensors/
├── __init__.py                 # 模块初始化
├── camera_thread.py           # 相机线程管理
├── microphone_thread.py       # 麦克风线程（TCP音频输入）
├── speaker_thread.py          # 扬声器线程（TCP音频输出）
├── audio_client_tcp.py        # 笔记本端TCP音频客户端
├── audio_server_tcp.py        # Jetson端TCP音频服务器
├── test_tcp_audio.py          # TCP音频系统测试脚本
├── audio_info.txt            # 音频设备信息
└── README.md                 # 本文件
```

## 系统架构

### TCP音频流架构（推荐）
```
笔记本(192.168.3.7) ←→ Jetson(192.168.3.1)
    ↓                      ↓
TCPAudioClient          MicrophoneThread(8888) + SpeakerThread(8889)
麦克风/扬声器          ↓
                    AudioServer + Live API + TTS
```

**设计优势**：
- TCP原始音频流，延迟更低
- 基于microphone_thread.py的成熟设计
- 音频质量验证和统计监控
- 更简单的协议，更高的稳定性

## 使用方法

### 1.TCP音频系统测试步骤

**第一步 - 运行测试脚本**：
```bash
# 在笔记本或Jetson容器内运行
python sensors/test_tcp_audio.py --host 192.168.3.1
```

**第二步 - 启动Jetson音频服务器**
```bash
# 在Jetson容器内运行
python sensors/audio_server_tcp.py --mic-port 8888 --speaker-port 8889
```

**第三步 - 启动笔记本音频客户端**：
```bash
# 在笔记本上运行
python sensors/audio_client_tcp.py --host 192.168.3.1 --mic-port 8888 --speaker-port 8889
```

### 2.可选参数

**audio_client_tcp.py**:
```bash
python sensors/audio_client_tcp.py --host 192.168.3.1 --mic-port 8888 --speaker-port 8889 --list-devices
```

**audio_server_tcp.py**:
```bash
python sensors/audio_server_tcp.py --mic-port 8888 --speaker-port 8889 --config config.ini
```

## 核心组件

### 1. MicrophoneThread (microphone_thread.py)
- TCP服务器，接收网络音频流
- 16kHz单声道，Live API标准格式
- 音频质量验证和队列管理
- 线程安全的asyncio.Queue
- 详细的统计监控

### 2. SpeakerThread (speaker_thread.py)
- TCP服务器，发送音频到网络客户端
- 与MicrophoneThread配套设计
- 支持numpy数组和bytes格式输入
- 自动格式转换和验证

### 3. TCPAudioClient (audio_client_tcp.py)
- 笔记本端TCP音频客户端
- 自动音频设备检测和选择
- 双向音频流：麦克风→Jetson, Jetson→扬声器
- 实时统计和错误处理

### 4. TCPAudioServer (audio_server_tcp.py)
- Jetson端音频服务器
- 集成MicrophoneThread和SpeakerThread
- Mock Live API（可替换为真实Gemini Live API）
- TTS系统集成

## 技术特性

- **极低延迟**：TCP原始音频流，无JSON序列化开销
- **音频验证**：幅度检查、格式验证、静音检测
- **自适应设备**：智能音频设备检测和选择
- **容错机制**：自动重连、队列管理、错误恢复
- **实时监控**：详细的延迟和性能统计
- **模块化架构**：易于集成真实Live API

## 音频格式

- **采样率**：16kHz（Live API标准）
- **位深度**：16bit
- **声道**：单声道
- **编码**：PCM（原始音频数据）
- **块大小**：1024样本（64ms）

## 预期性能

基于TCP原始音频流和3.2ms网络延迟：
- 音频采集：20ms
- TCP传输：<5ms（往返）
- Live API处理：200ms
- TTS合成：150ms
- 音频播放：20ms
- **总计**：~395ms（比WebSocket减少约20ms）

## 故障排除

1. **TCP连接失败**：
   - 检查Jetson服务器是否启动
   - 验证端口8888和8889是否可用
   - 确认网络连通性

2. **音频设备问题**：
   - 运行 `--list-devices` 查看可用设备
   - 检查容器音频设备权限
   - 验证采样率支持

3. **音频质量问题**：
   - 查看统计日志中的丢包信息
   - 检查网络延迟和稳定性
   - 调整音频块大小

4. **依赖项问题**：
   - 运行测试脚本检查依赖项
   - 确保sounddevice正确安装
   - 验证numpy版本兼容性

## 开发状态

### TCP音频系统 ✅
- ✅ MicrophoneThread基础架构
- ✅ SpeakerThread配套实现
- ✅ TCP音频客户端
- ✅ TCP音频服务器
- ✅ Mock Live API集成
- ✅ TTS系统集成
- ✅ 综合测试框架

### 待完成任务 ⏳
- ⏳ 真实Gemini Live API集成
- ⏳ 音频压缩和优化
- ⏳ 多客户端支持
- ⏳ 音频录制和回放功能

### 已弃用 ❌
- ❌ WebSocket音频流（延迟较高）
- ❌ JSON音频传输（效率较低）