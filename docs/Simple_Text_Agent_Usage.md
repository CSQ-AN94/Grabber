# 简单文本Gemini代理使用指南

## 概述

`SimpleTextAgent` 是一个务实的语音系统和Gemini集成方案，专为智能零售机器人设计。

### 核心特性
- ✅ 文本输入 → Gemini 2.5 Flash-Lite → 文本输出
- ✅ 使用新的 `google-genai` 库和Client方式
- ✅ 支持工具函数调用 (Tool Use)
- ✅ 集成iFlyTek TTS语音播报
- ✅ 简单可靠的实现，不追求完美用户体验

## 配置文件

系统使用 `config.yaml` 配置文件，通过 `utils/config.py` 的数据类加载配置。

### 必需配置 (config.yaml)

```yaml
# 大语言模型配置 - Google Gemini (必需)
llm:
  gemini_api_key: "your_gemini_api_key"
  model_name: "gemini-2.5-flash-lite"

# 语音合成配置 - iFlytek WebAPI (可选)
speech:
  app_id: "your_app_id"
  api_key: "your_api_key"
  api_secret: "your_api_secret"

# 智能Agent配置 - 音频参数
agent:
  audio_sample_rate: 16000  # 采样率：16kHz
  audio_channels: 1         # 声道数：单声道
  audio_chunk_size: 1024    # 音频块大小
```

如果不配置speech部分，系统将只显示文本而不进行语音播报。

## 使用方法

### 1. 交互式测试

```bash
# 在容器内运行
python3 scripts/test_simple_text_agent.py
```

### 2. 批量测试

```bash
# 批量测试预定义指令
python3 scripts/test_simple_text_agent.py batch
```

### 3. 编程集成

```python
from intelligence.simple_text_agent import SimpleTextAgent

# 初始化代理 (自动从config.yaml加载配置)
agent = SimpleTextAgent("config.yaml")

# 处理文本输入
result = await agent.process_text_input("扫描货架")

if result["success"]:
    print(f"AI回复: {result['text']}")
    # 自动进行TTS播报
```

## 工具函数支持

系统内置了以下工具函数：

### 1. 扫描货架
```
用户: 扫描货架
AI: 开始扫描货架... (执行scan_shelf工具)
播报: 货架扫描完成。检测到3个商品...
```

### 2. 抓取商品
```
用户: 抓取1-1区域的商品
AI: 正在抓取... (执行grasp_item工具)
播报: 正在抓取区域1-1的商品...抓取完成！
```

### 3. 查询商品信息
```
用户: 奥利奥饼干多少钱？
AI: 查询商品信息... (执行get_item_info工具)
播报: 奥利奥饼干的价格是8元，属于零食类。
```

### 4. 移动到位置
```
用户: 移动到扫描位置
AI: 开始移动... (执行move_to_position工具)
播报: 正在移动到scanning位置...到达目标位置。
```

## 系统架构

```
用户文本输入
    ↓
Gemini 2.5 Flash-Lite API (新google-genai库)
    ↓
响应解析 + 工具函数调用
    ↓
TTS播报 (iFlyTek) + 文本显示
```

## 示例对话

```
👤 用户: 你好，请帮我扫描一下货架
🤖 AI: 好的，我来为您扫描货架，检查商品情况。
🔊 TTS: 好的，我来为您扫描货架，检查商品情况。
🔧 执行: scan_shelf(announce=True)
🔊 TTS: 货架扫描完成。检测到3个商品：1-1区域的奥利奥饼干，1-2区域的橘子，2-1区域的可口可乐。

👤 用户: 奥利奥饼干多少钱？
🤖 AI: 让我查一下奥利奥饼干的价格信息。
🔊 TTS: 让我查一下奥利奥饼干的价格信息。
🔧 执行: get_item_info(item_name="奥利奥饼干")
🔊 TTS: 奥利奥饼干的价格是8元，属于零食类。

👤 用户: 请抓取1-1区域的商品
🤖 AI: 好的，我来抓取1-1区域的商品。
🔊 TTS: 好的，我来抓取1-1区域的商品。
🔧 执行: grasp_item(region_id="1-1")
🔊 TTS: 正在抓取区域1-1的商品...
🔊 TTS: 抓取完成！
```

## 技术特性

### 1. 新API架构
- 使用 `google-genai` 库 (不是旧的 `google.generativeai`)
- 客户端模式: `genai.Client(api_key=api_key)`
- 类型化配置: `types.GenerateContentConfig`

### 2. 错误处理
- API调用重试机制 (指数退避)
- TTS播报失败时自动降级为文本显示
- 工具函数异常捕获和报告

### 3. 异步支持
- 完全异步的处理流程
- 非阻塞的TTS播报
- 并发工具函数执行支持

### 4. 可扩展性
- 简单的工具函数注册机制
- 可替换的TTS系统
- 模块化的配置管理

## 故障排除

### 常见问题

1. **API密钥错误**
   ```
   ❌ Gemini客户端初始化失败: 401 Unauthorized
   ```
   解决: 检查GEMINI_API_KEY环境变量设置

2. **TTS播报无声音**
   ```
   ⚠️ iFlyTek配置缺失，TTS功能将被禁用
   ```
   解决: 设置iFlyTek相关环境变量，或者接受纯文本显示

3. **工具函数执行失败**
   ```
   ❌ 工具函数 xxx 执行失败: ...
   ```
   解决: 检查工具函数实现，确保Mock数据正确

### 调试模式

```bash
# 启用详细日志
export PYTHONPATH=/home/ningma/dev/Scratch/Grabber:$PYTHONPATH
python3 -c "
import logging
logging.basicConfig(level=logging.DEBUG)
# 然后运行测试
"
```

## 下一步开发

1. **集成真实硬件**: 将Mock工具函数替换为真实的机械臂和视觉系统调用
2. **语音输入**: 集成 `local_microphone.py` 的录音功能，实现语音输入
3. **Live API升级**: 未来可升级到Gemini Live API实现真正的实时对话
4. **多轮对话**: 添加对话上下文管理和多轮对话支持

## 总结

这个简单文本代理是一个务实的第一步实现，专注于：
- ✅ 能够工作的集成
- ✅ 简单可靠的架构  
- ✅ 易于测试和调试
- ✅ 为后续扩展打下基础

它不追求完美的用户体验，但提供了一个稳定的基础来验证Gemini+工具函数+TTS的完整流程。