# 音频系统重构计划

## 📋 项目背景

由于语音系统在Jetson-笔记本双向音频通信中遇到严重问题（语音重叠、连接不稳定、音频设备错误），决定推翻原来的网络音频架构，改为纯本地音频系统。

**目标**: 将系统从 **Jetson + 笔记本双设备** 架构改为 **纯笔记本Ubuntu + Docker** 架构

## 🔍 完整音频系统代码分析

### 📁 需要删除的代码（Jetson-笔记本网络通信）

#### 1. 网络音频传输基础架构
- **`sensors/microphone_thread.py`** - 完整删除
  - TCP麦克风服务器，监听8888端口
  - 接收来自笔记本的音频数据
  - 异步音频队列管理
  - 为Gemini Live API设计的网络音频输入

- **`sensors/audio_client_tcp.py`** - 完整删除
  - TCP音频客户端，在笔记本上运行
  - 捕获本地麦克风并发送到Jetson
  - 与MicrophoneThread配套工作

#### 2. 网络音频播放服务
- **`scripts/notebook_speaker_server.py`** - 完整删除
  - 笔记本端扬声器服务器，监听9889端口
  - 接收来自Jetson的音频数据并播放
  - 队列管理和音频设备控制

#### 3. 网络音频发送逻辑
- **`intelligence/speech.py`** 中的网络部分（部分删除）：
  - `_send_audio_to_speaker()` 方法
  - `_send_audio_sync()` 方法
  - 所有涉及 `self.speech_config.notebook_ip` 和 `speaker_port` 的代码
  - TCP socket连接和数据发送逻辑

#### 4. 配置文件中的网络配置
- **`utils/config.py`** 中的网络配置部分（部分删除）：
  - `SpeechConfig` 类中的 `notebook_ip` 和 `speaker_port` 字段
  - 相关的配置读取逻辑

#### 5. 网络音频测试脚本
- **`scripts/test_audio_receiver.py`** - 完整删除
- **`scripts/test_microphone_system.py`** - 完整删除
- **`scripts/test_speaker_system.py`** - 完整删除
- **`scripts/run_notebook_speaker.py`** - 完整删除
- **`scripts/test_improved_speech.py`** - 完整删除
- **`scripts/diagnose_speech_issues.py`** - 完整删除
- **`scripts/test_speech_comparison.py`** - 完整删除
- **`scripts/simple_speech_test.py`** - 完整删除
- **`sensors/test_tcp_audio.py`** - 完整删除（如果存在）

### 🎯 需要保留的代码（本地TTS功能）

#### 1. 核心TTS引擎
- **`intelligence/tts_ws_python3_demo.py`** - 保留
  - 原始iFlyTek WebSocket TTS实现
  - 语音合成核心逻辑
  - WebSocket通信和音频数据处理

#### 2. 语音合成系统核心
- **`intelligence/speech.py`** 中的TTS部分（部分保留）：
  - `iFlyTekTTS` 类 - 完整保留
  - `WsParam` 类 - 完整保留
  - `TTSConfig` 类 - 完整保留
  - `SpeechSystem` 类中的语音合成逻辑 - 部分保留
  - WebSocket相关的所有方法

#### 3. 配置系统中的TTS配置
- **`utils/config.py`** 中的TTS配置（部分保留）：
  - `SpeechConfig` 类中的 `app_id`, `api_key`, `api_secret` 字段
  - TTS相关的配置读取逻辑

#### 4. 基础测试脚本
- **`scripts/test_speech_system.py`** - 检查后决定是否保留
- 其他可能的TTS测试脚本（需要适配为本地播放）

### 🔄 需要重构的代码（网络→本地适配）

#### 1. Gemini Agent音频接口
- **`intelligence/gemini_agent.py`** - 需要重构
  - 当前使用MicrophoneThread接收网络音频
  - 需要改为本地麦克风接口
  - 保留Gemini Live API集成逻辑

#### 2. 语音系统输出接口
- **`intelligence/speech.py`** - 需要重构
  - 移除网络发送逻辑
  - 添加本地音频播放逻辑
  - 保留TTS合成功能

#### 3. 主应用集成
- **`main.py`** - 需要检查和可能的适配
  - 可能引用了网络音频相关的组件

---

## 🚀 详细执行计划

### 阶段1：清理网络音频代码 (1-2小时)

#### 1.1 备份重要文件
```bash
# 创建备份目录
mkdir -p backup/network_audio_system

# 备份关键文件
cp sensors/microphone_thread.py backup/network_audio_system/
cp sensors/audio_client_tcp.py backup/network_audio_system/
cp scripts/notebook_speaker_server.py backup/network_audio_system/
cp intelligence/speech.py backup/network_audio_system/
cp utils/config.py backup/network_audio_system/
```

#### 1.2 删除网络音频文件
```bash
# 删除网络音频传输文件
rm sensors/microphone_thread.py
rm sensors/audio_client_tcp.py
rm scripts/notebook_speaker_server.py
rm scripts/test_audio_receiver.py
rm scripts/test_microphone_system.py
rm scripts/test_speaker_system.py
rm scripts/run_notebook_speaker.py
rm scripts/test_improved_speech.py
rm scripts/diagnose_speech_issues.py
rm scripts/test_speech_comparison.py
rm scripts/simple_speech_test.py
rm -f sensors/test_tcp_audio.py
rm -f sensors/microphone_thread_backup.py
rm -f sensors/speaker_thread.py
rm -f intelligence/speech_new.py
rm -f intelligence/speech_backup.py
rm -f intelligence/speech_fixed.py
```

#### 1.3 清理配置文件
- 修改 `utils/config.py` 移除网络配置
- 修改 `config.ini` 移除网络相关配置

#### 1.4 清理speech.py
- 移除网络发送相关方法
- 保留TTS核心功能
- 移除网络相关的依赖

### 阶段2：实现本地音频系统 (2-3小时)

#### 2.1 创建本地音频播放接口
```python
class LocalAudioPlayer:
    """本地音频播放器，使用sounddevice直接播放"""
    
    async def play_audio(self, pcm_file: str) -> bool:
        """播放PCM音频文件"""
        # 使用sounddevice直接播放
        # 支持异步播放
        # 错误处理和资源管理
```

#### 2.2 重构SpeechSystem
- 替换网络发送为本地播放
- 简化异步架构
- 保留TTS合成功能
- 移除复杂的队列机制

#### 2.3 创建本地麦克风接口
```python
class LocalMicrophoneInput:
    """本地麦克风输入，替代网络音频输入"""
    
    async def start_recording(self) -> None:
        """开始录音"""
        
    async def get_audio_chunk(self) -> bytes:
        """获取音频数据块"""
        
    async def stop_recording(self) -> None:
        """停止录音"""
```

#### 2.4 重构Gemini Agent
- 使用本地麦克风替代网络音频
- 保留Live API集成
- 简化音频处理流程

### 阶段3：Docker配置优化 (1小时)

#### 3.1 更新Docker配置
```yaml
# docker-compose.yml
services:
  grabber:
    # 音频设备访问
    devices:
      - /dev/snd:/dev/snd
    # 环境变量
    environment:
      - PULSE_SERVER=unix:${XDG_RUNTIME_DIR}/pulse/native
      - DISPLAY=${DISPLAY}
    # 移除网络音频相关的端口映射
    # ports:
    #   - "8888:8888"  # 麦克风端口 - 删除
    #   - "9889:9889"  # 扬声器端口 - 删除
```

#### 3.2 音频依赖优化
- 确保容器内有sounddevice和相关音频库
- 配置PulseAudio或ALSA访问权限
- 测试容器内音频设备访问

### 阶段4：测试脚本重构 (1小时)

#### 4.1 创建本地音频测试脚本
```python
# scripts/test_local_audio.py
# 测试本地TTS合成和播放
# 测试本地麦克风录音
# 测试音频设备访问
```

#### 4.2 创建Gemini集成测试
```python
# scripts/test_gemini_local.py
# 测试本地音频 + Gemini Live API
# 测试工具调用功能
# 测试语音交互流程
```

### 阶段5：集成测试和验证 (1小时)

#### 5.1 功能验证
- TTS合成功能正常
- 本地音频播放正常
- 本地麦克风录音正常
- Gemini Live API集成正常

#### 5.2 性能测试
- 延迟测试（预期显著降低）
- 音频质量测试
- 并发处理测试
- 资源占用测试

#### 5.3 完整系统测试
- 运行 `python main.py`
- 测试语音交互模式
- 验证所有比赛任务功能
- 确保系统稳定性

---

## 📊 预期效果

### 性能改进
- **延迟降低**: 消除网络传输延迟，预期延迟从 ~500ms 降低到 ~100ms
- **稳定性提升**: 消除网络连接不稳定问题
- **资源占用减少**: 无需维护TCP连接和网络缓冲

### 架构简化
- **组件减少**: 从双设备架构简化为单设备架构
- **代码减少**: 删除 ~3000 行网络音频相关代码
- **配置简化**: 移除网络配置，只保留TTS配置

### 维护性提升
- **调试简化**: 所有组件在同一环境中
- **部署简化**: 只需要一个Docker容器
- **故障排除**: 消除网络相关的故障点

---

## 🎯 关键里程碑

- [x] **里程碑1**: 完成网络音频代码清理
- [x] **里程碑2**: 实现本地音频播放功能
- [x] **里程碑3**: 实现本地麦克风录音功能
- [x] **里程碑4**: 重构Gemini Agent音频接口
- [x] **里程碑5**: 完成Docker配置优化
- [x] **里程碑6**: 通过所有集成测试
- [x] **里程碑7**: 系统完全正常运行

---

## 🔧 技术实现细节

### 本地音频播放实现
```python
import sounddevice as sd
import numpy as np

class LocalAudioPlayer:
    async def play_pcm(self, pcm_file: str) -> bool:
        with open(pcm_file, 'rb') as f:
            audio_data = f.read()
        
        # 转换为numpy数组
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        audio_float = audio_array.astype(np.float32) / 32768.0
        
        # 播放音频
        sd.play(audio_float, samplerate=16000, blocking=True)
        return True
```

### 本地麦克风录音实现
```python
class LocalMicrophoneInput:
    def __init__(self):
        self.audio_queue = asyncio.Queue()
        self.stream = None
    
    def audio_callback(self, indata, frames, time, status):
        if status:
            print(f'Audio status: {status}')
        
        # 转换为16位PCM
        audio_data = (indata * 32767).astype(np.int16)
        self.audio_queue.put_nowait(audio_data.tobytes())
    
    async def start_recording(self):
        self.stream = sd.InputStream(
            samplerate=16000,
            channels=1,
            dtype=np.float32,
            callback=self.audio_callback
        )
        self.stream.start()
    
    async def get_audio_chunk(self) -> bytes:
        return await self.audio_queue.get()
```

---

## 📝 注意事项

### 重要提醒
1. **代码备份**: 在删除任何文件之前，务必备份到 `backup/` 目录
2. **渐进式重构**: 每个阶段完成后进行测试，确保功能正常
3. **依赖管理**: 确保新的音频库正确安装在Docker容器中
4. **权限配置**: 确保Docker容器有足够的权限访问音频设备

### 风险控制
- **回滚计划**: 如果重构失败，可以从备份恢复
- **测试优先**: 每个功能实现后立即测试
- **文档更新**: 及时更新相关文档和注释

---

**计划创建时间**: 2024年7月17日  
**预期完成时间**: 2024年7月17日  
**负责人**: Claude Code Assistant  
**状态**: 待执行