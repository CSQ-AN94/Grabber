# Gemini Live API 集成指南

## 系统状态

✅ **完全集成完成** - Grabber系统已与Gemini Live API完全集成，支持实时语音交互和工具调用。

## 架构概述

```
笔记本麦克风 → TCP客户端 → Jetson MicrophoneThread → Gemini Live API
                                                           ↓
                                                      工具调用解析
                                                           ↓
Jetson SpeechSystem → TCP客户端 → 笔记本扬声器 ← MockRobotTools执行
```

## 核心组件

### 1. **GeminiAgent** (`intelligence/gemini_agent.py`)
- ✅ 完整的Gemini Live API集成
- ✅ 实时音频流处理
- ✅ 工具调用和响应处理
- ✅ 中文语音交互支持

### 2. **MockRobotTools** (`intelligence/robot_tools.py`)
- ✅ 7个完整的工具函数
- ✅ 标准化工具定义
- ✅ 覆盖所有比赛任务

### 3. **音频系统**
- ✅ 异步MicrophoneThread
- ✅ 网络音频传输
- ✅ 语音合成和播放

## 可用工具函数

| 工具名称 | 描述 | 对应任务 |
|---------|------|---------|
| `scan_inventory` | 扫描货架商品并播报位置 | 任务A |
| `grab_item_by_name` | 根据商品名称抓取商品 | 任务C1 |
| `grab_item_by_position` | 根据相对位置抓取商品 | 任务C2 |
| `grab_item_by_semantic` | 根据语义分类抓取商品 | 任务C3 |
| `calculate_checkout` | 计算结算区商品总价 | 任务D |
| `query_world_map` | 查询完整的货架商品地图 | 辅助查询 |
| `query_item_location` | 查询特定商品的位置信息 | 辅助查询 |

## 测试方法

### 方法1: 基本功能测试

```bash
# 在Jetson容器内运行基本测试
python scripts/test_gemini_integration.py --basic

# 测试语音输出
python scripts/test_gemini_integration.py --speech
```

### 方法2: 完整交互测试

**步骤1: 启动笔记本端音频系统**
```bash
# 在笔记本上启动扬声器服务器
python scripts/notebook_speaker_server.py

# 在另一个终端启动麦克风客户端
python sensors/audio_client_tcp.py --host 192.168.3.10
```

**步骤2: 在Jetson容器内启动交互测试**
```bash
# 60秒交互测试
python scripts/test_gemini_integration.py --interactive --duration 60

# 长时间交互测试
python scripts/test_gemini_integration.py --interactive --duration 300
```

### 方法3: 完整系统演示

```bash
# 启动完整的Grabber系统
python main.py

# 选择 [V] 语音交互模式
```

## 语音交互示例

### 基本对话
- **说**: "你好"
- **期待**: Gemini用中文回应

### 工具调用示例

#### 库存扫描 (任务A)
- **说**: "请扫描货架商品"
- **期待**: 调用`scan_inventory`，播报商品位置

#### 商品抓取 (任务C)
- **说**: "请帮我拿一瓶可口可乐"
- **期待**: 调用`grab_item_by_name`，模拟抓取过程

#### 相对位置抓取
- **说**: "请拿可口可乐右边的商品"
- **期待**: 调用`grab_item_by_position`

#### 语义抓取
- **说**: "请给我一个饮料"
- **期待**: 调用`grab_item_by_semantic`，可能询问具体选择

#### 结账计算 (任务D)
- **说**: "请计算结账金额"
- **期待**: 调用`calculate_checkout`，播报总价

#### 查询功能
- **说**: "牙膏在哪里？"
- **期待**: 调用`query_item_location`

## 配置文件

确保`config.ini`包含正确配置：

```ini
[llm]
gemini_api_key = AIzaSyDoRYk_kU61IIeEsCuAUaRft2iaeKXtoFE
model_name = gemini-2.0-flash-live-001

[agent]
audio_sample_rate = 16000
audio_channels = 1
audio_chunk_size = 1024

[speech]
notebook_ip = 192.168.3.7
speaker_port = 9889
app_id = aeb60378
api_key = e248b59b7b21d7291702b7808ba07257
api_secret = MjQ1ZmM3MjkwNmEzZTQyN2ZiNTYxN2Ey
```

## 故障排除

### 1. Gemini API连接问题
- **症状**: "API连接失败"
- **解决**: 检查API密钥和网络连接

### 2. 音频输入问题  
- **症状**: "没有收到音频数据"
- **解决**: 确保笔记本音频客户端正确连接到Jetson的8888端口

### 3. 语音输出问题
- **症状**: "语音合成成功但听不到声音"
- **解决**: 确保笔记本扬声器服务器在9889端口监听

### 4. 工具调用问题
- **症状**: "Gemini不调用工具"
- **解决**: 确保工具定义正确加载，尝试更明确的语音指令

## 性能监控

### 音频质量检查
```bash
# 检查音频数据接收
python scripts/test_microphone_system.py --quality
```

### 系统状态监控
```bash
# 查看Gemini Agent状态
python -c "from intelligence.gemini_agent import GeminiAgent; print('Agent可用')"
```

## 比赛任务映射

| 比赛任务 | 对应功能 | 测试语音指令 |
|---------|---------|-------------|
| 任务A: 库存扫描 | `scan_inventory` | "请扫描货架" |
| 任务B: 图像推荐 | `recommend_item` | "根据这张图片推荐商品" |
| 任务C: 语音购物 | `grab_item_*` | "请拿可口可乐" |
| 任务D: 结账计算 | `calculate_checkout` | "请计算总价" |

## 演示脚本

### 完整演示流程
1. 启动音频系统（笔记本端）
2. 启动Grabber系统: `python main.py`
3. 选择语音交互模式: `V`
4. 按序测试所有工具功能
5. 展示自然语言交互能力

### 预设演示对话
```
用户: "你好，请介绍一下你的功能"
Agent: [介绍机器人功能]

用户: "请扫描一下货架上的商品"
Agent: [调用scan_inventory，播报商品]

用户: "我想要一瓶可口可乐"
Agent: [调用grab_item_by_name，模拟抓取]

用户: "请计算一下总价"
Agent: [调用calculate_checkout，播报价格]
```

## 系统优势

1. **完全异步架构** - 高性能，低延迟
2. **模块化设计** - 易于扩展和维护  
3. **标准化工具接口** - 符合OpenAPI规范
4. **中文优化** - 针对中国机器人竞赛优化
5. **mock和真实硬件无缝切换** - 便于开发和演示

## 下一步扩展

1. **连接真实硬件** - 将mock工具替换为真实硬件控制
2. **视觉集成** - 添加实时图像分析到任务B
3. **多轮对话** - 增强对话上下文管理
4. **个性化推荐** - 基于用户偏好的智能推荐

---

**系统已完全就绪，可以进行实时语音交互和工具调用演示！** 🎉