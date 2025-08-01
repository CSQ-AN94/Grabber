# GLM Agent 实现参考文档

## 基本信息
- **模型**: glm-4v-flash (免费)
- **库**: zhipuai (pip install zhipuai)
- **API**: https://open.bigmodel.cn/api/paas/v4/chat/completions

## 核心代码模式

### 1. 客户端初始化
```python
from zhipuai import ZhipuAI

# 方式1: 直接传入API密钥
client = ZhipuAI(api_key="your_api_key_here")

# 方式2: 环境变量 (支持 ZHIPUAI_API_KEY)
client = ZhipuAI()  # 自动读取环境变量
```

### 2. 基本文本对话
```python
response = client.chat.completions.create(
    model="glm-4v-flash",  # 使用免费的flash模型
    messages=[
        {"role": "user", "content": "你好，请介绍一下智谱AI"}
    ],
)
print(response.choices[0].message.content)
```

### 3. 响应数据结构
```python
response.choices[0].message.content  # 文本内容
response.choices[0].finish_reason    # 结束原因: "stop", "length", "sensitive"
response.usage.total_tokens          # token使用量
response.id                          # 请求ID
```

### 4. 异常处理
```python
import zhipuai

try:
    response = client.chat.completions.create(...)
except zhipuai.APIStatusError as err:
    print(f"API状态错误: {err}")
except zhipuai.APITimeoutError as err:
    print(f"请求超时: {err}")
except Exception as err:
    print(f"其他错误: {err}")
```

### 5. 配置参数
```python
response = client.chat.completions.create(
    model="glm-4v-flash",
    messages=[...],
    temperature=0.8,      # 控制随机性 [0.0, 1.0]
    top_p=0.6,           # 核采样 [0.0, 1.0]
    max_tokens=1024,     # 最大输出token数
    stream=False,        # 是否流式输出
)
```

## 实现要点

1. **模型选择**: 使用 `glm-4v-flash` (免费版本)
2. **消息格式**: 标准的 `{"role": "user/assistant", "content": "text"}` 格式
3. **错误处理**: 使用 zhipuai 库的异常类型
4. **异步支持**: 需要用 asyncio.get_event_loop().run_in_executor() 包装
5. **配置方式**: 支持直接传入 api_key 或环境变量 ZHIPUAI_API_KEY