# Google GenAI 新库使用指南

## 概述

本文档记录从旧的 `google.generativeai` 迁移到新的 `google-genai` 库的学习成果，专注于Grabber项目的实际使用需求。

## 关键变化

### 1. API架构变化

#### 旧API (google.generativeai)
```python
import google.generativeai as genai

# 全局配置
genai.configure(api_key="YOUR_API_KEY")

# 直接模型调用
model = genai.GenerativeModel('gemini-1.5-flash')
response = model.generate_content("Hello")
```

#### 新API (google-genai)
```python
from google import genai

# 客户端实例化
client = genai.Client(api_key="YOUR_API_KEY")

# 通过客户端调用
response = client.models.generate_content(
    model='gemini-2.5-flash-lite',
    contents='Hello'
)
```

### 2. 核心变化要点

1. **中心化客户端**：所有操作通过`Client`对象统一管理
2. **标准化方法**：使用`client.models.generate_content()`替代直接模型调用
3. **配置对象**：使用类型化配置对象替代关键字参数
4. **环境变量支持**：自动检测`GEMINI_API_KEY`或`GOOGLE_API_KEY`

## Grabber项目实际使用

### 1. 客户端初始化

```python
from google import genai
from google.genai import types

class FlashLiteAgent:
    def __init__(self, api_key: str):
        # 初始化客户端
        self.client = genai.Client(api_key=api_key)
        
        # 无需创建模型实例，直接使用客户端调用
```

### 2. 原生音频输入处理

```python
async def process_audio(self, audio_data: bytes):
    """处理原生音频输入"""
    
    # 准备内容
    contents = [
        {
            "mime_type": "audio/pcm",
            "data": audio_data
        },
        "请理解用户的语音指令并提供帮助。"
    ]
    
    # 调用模型
    response = self.client.models.generate_content(
        model='gemini-2.5-flash-lite',
        contents=contents
    )
    
    return response
```

### 3. 配置参数设置

```python
def create_generation_config():
    """创建生成配置"""
    return types.GenerateContentConfig(
        temperature=0.7,
        top_p=0.8,
        top_k=40,
        max_output_tokens=2048,
        system_instruction="你是智能零售机器人助手..."
    )

# 使用配置
response = client.models.generate_content(
    model='gemini-2.5-flash-lite',
    contents=contents,
    config=create_generation_config()
)
```

### 4. 工具函数调用 (Function Calling)

```python
def create_tools():
    """创建工具定义"""
    return [
        types.Tool(
            function_declarations=[
                types.FunctionDeclaration(
                    name="scan_inventory",
                    description="扫描货架商品并播报位置",
                    parameters=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "announce": types.Schema(
                                type=types.Type.BOOLEAN,
                                description="是否播报商品清单"
                            )
                        }
                    )
                )
            ]
        )
    ]

# 带工具的调用
response = client.models.generate_content(
    model='gemini-2.5-flash-lite',
    contents=contents,
    config=types.GenerateContentConfig(
        tools=create_tools()
    )
)
```

### 5. 响应处理

```python
def process_response(self, response):
    """处理模型响应"""
    
    # 获取文本响应
    if response.text:
        print(f"AI响应: {response.text}")
    
    # 处理函数调用
    if response.candidates:
        for candidate in response.candidates:
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if hasattr(part, 'function_call'):
                        self.execute_function_call(part.function_call)
```

### 6. 错误处理和重试

```python
async def call_with_retry(self, contents, max_retries=3):
    """带重试的API调用"""
    for attempt in range(max_retries):
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None, 
                self.client.models.generate_content,
                'gemini-2.5-flash-lite',
                contents
            )
            return response
            
        except Exception as e:
            if attempt < max_retries - 1:
                await asyncio.sleep(2 ** attempt)  # 指数退避
            else:
                raise e
```

## 关键注意事项

### 1. 导入语句
```python
# 正确 ✅
from google import genai
from google.genai import types

# 错误 ❌ (旧API)
import google.generativeai as genai
```

### 2. 模型名称
```python
# 使用最新的模型名称
model = 'gemini-2.5-flash-lite'  # 稳定版
model = 'gemini-2.0-flash-exp'   # 实验版
```

### 3. 内容格式
```python
# 支持多种内容格式
contents = [
    "文本内容",
    {"mime_type": "audio/pcm", "data": audio_bytes},
    {"mime_type": "image/jpeg", "data": image_bytes}
]
```

### 4. 异步处理
```python
# 新API本身是同步的，需要包装为异步
response = await asyncio.get_event_loop().run_in_executor(
    None, 
    self.client.models.generate_content,
    model,
    contents
)
```

## 实际迁移步骤

### 步骤1: 更新依赖
```bash
# requirements.txt
google-genai  # 新库
# google-generativeai  # 移除旧库
```

### 步骤2: 重构初始化代码
```python
class FlashLiteAgent:
    def __init__(self, api_key: str):
        # 新方式
        self.client = genai.Client(api_key=api_key)
        
        # 移除旧方式
        # genai.configure(api_key=api_key)
        # self.model = genai.GenerativeModel(...)
```

### 步骤3: 更新API调用
```python
# 新方式
response = self.client.models.generate_content(
    model='gemini-2.5-flash-lite',
    contents=contents,
    config=config
)

# 移除旧方式
# response = self.model.generate_content(contents)
```

### 步骤4: 更新配置方式
```python
# 新方式：使用类型化配置
config = types.GenerateContentConfig(
    temperature=0.7,
    tools=tools,
    system_instruction=prompt
)

# 移除旧方式
# generation_config = {...}
# safety_settings = {...}
```

## 总结

新的google-genai库提供了：
1. 更一致的API设计
2. 更好的类型支持
3. 统一的客户端管理
4. 更强的配置能力

对于Grabber项目，主要优势是原生音频支持和稳定的函数调用能力，这正是我们Gemini 2.5 Flash-Lite方案的核心需求。