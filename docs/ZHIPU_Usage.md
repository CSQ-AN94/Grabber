# 智谱AI开放平台 Python SDK

[![PyPI version](https://img.shields.io/pypi/v/zhipuai.svg)](https://pypi.org/project/zhipuai/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)

[English Readme](README.md)

[智谱AI开放平台](https://open.bigmodel.cn/dev/api)官方 Python SDK，帮助开发者快速集成智谱AI强大的人工智能能力到Python应用中。

## ✨ 特性

- 🚀 **类型安全**: 所有接口完全类型封装，无需查阅API文档即可完成接入
- 🔧 **简单易用**: 简洁直观的API设计，快速上手
- ⚡ **高性能**: 基于现代Python库构建，性能优异
- 🛡️ **安全可靠**: 内置身份验证和令牌管理
- 📦 **轻量级**: 最小化依赖，易于项目集成
- 🔄 **流式支持**: 支持SSE流式响应和异步调用

## 📦 安装

### 环境要求
- Python 3.9 或更高版本
- pip 包管理器

### 使用 pip 安装

```sh
pip install zhipuai
```

### 📋 核心依赖

本SDK使用以下核心依赖库：

| 依赖库 | 用途 |
|--------|------|
| httpx | HTTP客户端库 |
| pydantic | 数据验证和序列化 |
| typing-extensions | 类型注解扩展 |

## 🚀 快速开始

### 基本用法

1. **使用API密钥创建客户端**
2. **调用相应的API方法**

完整示例请参考开放平台[接口文档](https://open.bigmodel.cn/dev/api)以及[使用指南](https://open.bigmodel.cn/dev/howuse/)，记得替换为您自己的API密钥。

### 客户端配置

SDK支持多种方式配置API密钥：

**环境变量配置：**
```bash
export ZHIPUAI_API_KEY="your_api_key_here"
export ZHIPUAI_BASE_URL="https://open.bigmodel.cn/api/paas/v4/"  # 可选
```

**代码配置：**
```python
from zhipuai import ZhipuAI

client = ZhipuAI(
    api_key="your_api_key_here",  # 填写您的 APIKey
) 
```
**高级配置：**

SDK提供了灵活的客户端配置选项：

```python
import httpx
from zhipuai import ZhipuAI

client = ZhipuAI(
    api_key="your_api_key_here",
    timeout=httpx.Timeout(timeout=300.0, connect=8.0),  # 超时配置
    max_retries=3,  # 重试次数
    base_url="https://open.bigmodel.cn/api/paas/v4/"  # Custom API endpoint
)
```

**配置选项：**
- `timeout`: 控制接口连接和读取超时时间
- `max_retries`: 控制重试次数，默认为3次
- `base_url`: 自定义API基础URL


## 💡 使用示例

### 基础对话

```python
from zhipuai import ZhipuAI

client = ZhipuAI(api_key="your-api-key")  # 请填写您自己的APIKey
response = client.chat.completions.create(
    model="glm-4",  # 填写需要调用的模型名称
    messages=[
        {"role": "user", "content": "你好，请介绍一下智谱AI"}
    ],
    tools=[
        {
            "type": "web_search",
            "web_search": {
                "search_query": "Search the Zhipu",
                "search_result": True,
            }
        }
    ],
    extra_body={"temperature": 0.5, "max_tokens": 50}
)
print(response.choices[0].message.content)
```

### 流式对话

```python
from zhipuai import ZhipuAI

client = ZhipuAI(api_key="your-api-key")  # 请填写您自己的APIKey
response = client.chat.completions.create(
    model="glm-4",  # 填写需要调用的模型名称
    messages=[
        {"role": "system", "content": "你是一个人工智能助手，你叫ChatGLM"},
        {"role": "user", "content": "你好！你叫什么名字"},
    ],
    stream=True,
)

for chunk in response:
    if chunk.choices[0].delta.content:
        print(chunk.choices[0].delta)
```

### 多模态对话

```python
import base64
from zhipuai import ZhipuAI

def encode_image(image_path):
    """将图片编码为base64格式"""
    with open(image_path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

client = ZhipuAI()  # 请填写您自己的APIKey
base64_image = encode_image("path/to/your/image.jpg")

response = client.chat.completions.create(
    model="glm-4v",  # 视觉模型
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "请描述这张图片的内容"
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
        }
    ],
    extra_body={"temperature": 0.5, "max_tokens": 50}
)
print(response.choices[0].message.content)
```

### 角色扮演

```python
from zhipuai import ZhipuAI

client = ZhipuAI()  # 请填写您自己的APIKey
response = client.chat.completions.create(
    model="charglm-3",  # 角色扮演模型
    messages=[
        {
            "role": "user",
            "content": "你好，最近在忙什么呢？"
        }
    ],
    meta={
        "user_info": "我是一位电影导演，擅长拍摄音乐题材的电影。",
        "bot_info": "你是一位当红的国内女歌手及演员，拥有出众的音乐才华。",
        "bot_name": "小雅",
        "user_name": "导演"
    },
)
print(response.choices[0].message.content)
```

### 智能体对话

```python
from zhipuai import ZhipuAI

client = ZhipuAI()  # 请填写您自己的APIKey

response = client.assistant.conversation(
    assistant_id="your_assistant_id",  # 智能体ID，可用 65940acff94777010aa6b796 进行测试
    model="glm-4-assistant",
    messages=[
        {
            "role": "user",
            "content": [{
                "type": "text",
                "text": "帮我搜索智谱AI的最新产品信息"
            }]
        }
    ],
    stream=True,
    attachments=None,
    metadata=None,
    request_id="request_1790291013237211136",
    user_id="12345678"
)

for chunk in response:
    print(chunk)
```

### 视频生成

```python
from zhipuai import ZhipuAI

client = ZhipuAI(api_key="your-api-key")
response = client.videos.generations(
    model="cogvideox-2",
    prompt="一个美丽的日落海滩场景",   # 生成内容的提示词
    quality="quality",          # 输出模式：'quality' 表示质量优先，'speed' 表示速度优先
    with_audio=True,            # 生成带背景音频的视频
    size="1920x1080",           # 视频分辨率（最高支持 4K，例如 "3840x2160"）
    fps=30,                     # 帧率（可选 30 或 60）
    user_id="user_12345"
)

# 生成过程可能需要一些时间
result = client.videos.retrieve_videos_result(id=response.id)
print(result)
```

## 🚨 异常处理

SDK提供了完善的异常处理机制：

```python
from zhipuai import ZhipuAI
import zhipuai

client = ZhipuAI()  # 请填写您自己的APIKey

try:
    response = client.chat.completions.create(
        model="glm-4",
        messages=[
            {"role": "user", "content": "你好，智谱AI！"}
        ]
    )
    print(response.choices[0].message.content)
    
except zhipuai.APIStatusError as err:
    print(f"API状态错误: {err}")
except zhipuai.APITimeoutError as err:
    print(f"请求超时: {err}")
except Exception as err:
    print(f"其他错误: {err}")
```


SDK 用户鉴权指南

我们的所有 API 使用 API Key 进行身份验证。您可以访问API Keys 页面查找您将在请求中使用的 API Key。
本版本对鉴权方式进行了升级，历史已接入平台的用户可继续沿用老版本的鉴权方式。新版本的鉴权方法可参考以下详细描述：

【重要】安全提示
请注意保护您的密钥信息！不要与他人共享或在任何客户端代码（浏览器、应用程序）中公开您的 API Key。如您的 API Key 存在泄露风险，您可以通过删除该密钥来保护您的账户安全。
Python SDK 创建 Client

我们已经将接口鉴权封装到 SDK，您只需按照 SDK 调用示例填写 API Key 即可，示例如下：

from zhipuai import ZhipuAI

client = ZhipuAI(api_key="")  # 请填写您自己的API Key
response = client.chat.completions.create(
  model="glm-4-0520",  # 填写需要调用的模型编码
  messages=[
      {"role": "user", "content": "你好！你叫什么名字"},
  ],
  stream=True,
)
for chunk in response:
    print(chunk.choices[0].delta)

Java SDK 创建 Client

类似的，使用 Java SDK 您替换自己的 ApiSecretKey 即可，示例如下：

ClientV4 client = new ClientV4.Builder("{Your ApiSecretKey}").build();  

传输层默认使用 okhttpclient，如果需要修改为其他 http client，可以如下指定（注意 apache 不支持 sse 调用）：

ClientV4 client = new ClientV4.Builder("{Your ApiSecretKey}")
                  .httpTransport(new ApacheHttpClientTransport())
                  .build();  


SDK 代码示例

平台提供了同步、异步、SSE 三种调用方式（调用方式取决于具体模型的支持情况）
同步调用

调用后即可一次性获得最终结果，Python 代码示例如下：

from zhipuai import ZhipuAI
client = ZhipuAI(api_key="") # 填写您自己的APIKey
response = client.chat.completions.create(
    model="glm-4-0520",  # 填写需要调用的模型编码
    messages=[
        {"role": "user", "content": "作为一名营销专家，请为我的产品创作一个吸引人的slogan"},
        {"role": "assistant", "content": "当然，为了创作一个吸引人的slogan，请告诉我一些关于您产品的信息"},
        {"role": "user", "content": "智谱AI开放平台"},
        {"role": "assistant", "content": "智启未来，谱绘无限一智谱AI，让创新触手可及!"},
        {"role": "user", "content": "创造一个更精准、吸引人的slogan"}
    ],
)
print(response.choices[0].message)

Java 代码示例如下：

/**
* 同步调用
*/
private static void testInvoke() {
   List<ChatMessage> messages = new ArrayList<>();
   ChatMessage chatMessage = new ChatMessage(ChatMessageRole.USER.value(), "作为一名营销专家，请为智谱开放平台创作一个吸引人的slogan");
   messages.add(chatMessage);
   String requestId = String.format("YourRequestId-d%", System.currentTimeMillis());
   ChatCompletionRequest chatCompletionRequest = ChatCompletionRequest.builder()
           .model(Constants.ModelChatGLM4)
           .stream(Boolean.FALSE)
           .invokeMethod(Constants.invokeMethod)
           .messages(messages)
           .requestId(requestId)
           .build();
   ModelApiResponse invokeModelApiResp = client.invokeModelApi(chatCompletionRequest);
   try {
       System.out.println("model output:" + mapper.writeValueAsString(invokeModelApiResp));
   } catch (JsonProcessingException e) {
       e.printStackTrace();
   }
}

异步调用

调用后会立即返回一个任务 ID，然后用任务ID查询调用结果（根据模型和参数的不同，通常需要等待10-30秒才能得到最终结果），Python代码示例如下：

from zhipuai import ZhipuAI
 
client = ZhipuAI(api_key="") # 请填写您自己的APIKey
response = client.chat.asyncCompletions.create(
    model="glm-4-0520",  # 填写需要调用的模型编码
    messages=[
        {
            "role": "user",
            "content": "请你作为童话故事大王，写一篇短篇童话故事，故事的主题是要永远保持一颗善良的心，要能够激发儿童的学习兴趣和想象力，同时也能够帮助儿童更好地理解和接受故事中所蕴含的道理和价值观。"
        }
    ],
)
print(response)

Java 代码示例如下：

/**
* 异步调用
*/
private static String testAsyncInvoke() {
   List<ChatMessage> messages = new ArrayList<>();
   ChatMessage chatMessage = new ChatMessage(ChatMessageRole.USER.value(), "作为一名营销专家，请为智谱开放平台创作一个吸引人的slogan");
   messages.add(chatMessage);
   String requestId = String.format("YourRequestId-d%", System.currentTimeMillis());
   
   ChatCompletionRequest chatCompletionRequest = ChatCompletionRequest.builder()
           .model(Constants.ModelChatGLM4)
           .stream(Boolean.FALSE)
           .invokeMethod(Constants.invokeMethodAsync)
           .messages(messages)
           .requestId(requestId)
           .build();
   ModelApiResponse invokeModelApiResp = client.invokeModelApi(chatCompletionRequest);
   System.out.println("model output:" + JSON.toJSONString(invokeModelApiResp));
   return invokeModelApiResp.getData().getTaskId();
}

流式调用

调用后可以流式的实时获取到结果直到结束，Python 代码示例如下：

from zhipuai import ZhipuAI
client = ZhipuAI(api_key="") # 请填写您自己的APIKey
response = client.chat.completions.create(
    model="glm-4-0520",  # 填写需要调用的模型编码
    messages=[
        {"role": "system", "content": "你是一个乐于解答各种问题的助手，你的任务是为用户提供专业、准确、有见地的建议。"},
        {"role": "user", "content": "我对太阳系的行星非常感兴趣，特别是土星。请提供关于土星的基本信息，包括其大小、组成、环系统和任何独特的天文现象。"},
    ],
    stream=True,
)
for chunk in response:
    print(chunk.choices[0].delta)

Java 代码示例如下：

* sse调用*/
private static void testSseInvoke() {
   List<ChatMessage> messages = new ArrayList<>();
   ChatMessage chatMessage = new ChatMessage(ChatMessageRole.USER.value(), "作为一名营销专家，请为智谱开放平台创作一个吸引人的slogan");
   messages.add(chatMessage);
   String requestId = String.format("YourRequestId-d%", System.currentTimeMillis());
 
   ChatCompletionRequest chatCompletionRequest = ChatCompletionRequest.builder()
           .model(Constants.ModelChatGLM4)
           .stream(Boolean.TRUE)
           .messages(messages)
           .requestId(requestId)
           .build();
   ModelApiResponse sseModelApiResp = client.invokeModelApi(chatCompletionRequest);
   if (sseModelApiResp.isSuccess()) {
       AtomicBoolean isFirst = new AtomicBoolean(true);
       ChatMessageAccumulator chatMessageAccumulator = mapStreamToAccumulator(sseModelApiResp.getFlowable())
               .doOnNext(accumulator -> {
                   {
                       if (isFirst.getAndSet(false)) {
                           System.out.print("Response: ");
                       }
                       if (accumulator.getDelta() != null && accumulator.getDelta().getTool_calls() != null) {
                           String jsonString = mapper.writeValueAsString(accumulator.getDelta().getTool_calls());
                           System.out.println("tool_calls: " + jsonString);
                       }
                       if (accumulator.getDelta() != null && accumulator.getDelta().getContent() != null) {
                           System.out.print(accumulator.getDelta().getContent());
                       }
                   }
               })
               .doOnComplete(System.out::println)
               .lastElement()
               .blockingGet();
 
       Choice choice = new Choice(chatMessageAccumulator.getChoice().getFinishReason(), 0L, chatMessageAccumulator.getDelta());
       List<Choice> choices = new ArrayList<>();
       choices.add(choice);
       ModelData data = new ModelData();
       data.setChoices(choices);
       data.setUsage(chatMessageAccumulator.getUsage());
       data.setId(chatMessageAccumulator.getId());
       data.setCreated(chatMessageAccumulator.getCreated());
       data.setRequestId(chatCompletionRequest.getRequestId());
       sseModelApiResp.setFlowable(null);
       sseModelApiResp.setData(data);
   }
   System.out.println("model output:" + JSON.toJSONString(sseModelApiResp));
}



GLM-4V系列

GLM-4V 在不牺牲任何NLP任务性能的情况下，实现了视觉语言特征的深度融合；支持视觉问答、图像字幕、视觉定位、复杂目标检测等各类图像/视频理解任务。

    模型编码：glm-4v-plus-0111 、glm-4v-flash；
    了解GLM-4V系列模型差异，选择最适合你的的大模型；
    查看 产品价格 ,大规模处理图像数据，推荐使用 Batch API，更有 5 折扣优惠；
    欢迎在 体验中心 体验 GLM-4V-Plus-0111 模型的强大能力；
    查看模型 速率限制；
    查看您的 API Key；

同步调用
接口请求
类型 	说明
传输方式 	https
请求地址 	https://open.bigmodel.cn/api/paas/v4/chat/completions
调用方式 	同步调用，等待模型执行完成并返回最终结果或 SSE 调用
字符编码 	UTF-8
接口请求格式 	JSON
响应格式 	JSON 或标准 Stream Event
接口请求类型 	POST
开发语言 	任意可发起 http 请求的开发语言
请求参数
参数名称 	类型 	必填 	参数说明
model 	String 	是 	调用的模型编码。 模型编码：glm-4v-plus-0111 、glm-4v、glm-4v-flash(免费)
GLM-4V-Plus-0111:具备卓越的多模态理解能力，可同时处理最多5张图像，并支持视频内容理解（视频大小 ＜200M ），适用于复杂的多媒体分析场景。
GLM-4V-Flash（免费）: 专注于高效的单一图像理解，适用于图像解析的场景，例如实时图像分析或批量图像处理。
messages 	List<Object> 	是 	调用语言模型时，将当前对话信息列表作为提示输入给模型， 按照 json 数组形式进行传参。比如，
视频理解参数：{ "role": "user", "content": [ { "type": "video_url", "video_url": { "url" : "https://xxx/xx.mp4" } }, { "type": "text", "text": "请仔细描述这个视频" } ] }
图片理解参数：{ "role": "user", "content": [ { "type": "image_url", "image_url": { "url" : "https://xxx/xx.jpg" } }, { "type": "text", "text": "解释一下图中的现象" } ] }
可能的消息类型包括 User message、Assistant message。见下方 message 消息字段说明。
request_id 	String 	否 	由用户端传参，需保证唯一性；用于区分每次请求的唯一标识，用户端不传时平台会默认生成。
do_sample 	Boolean 	否 	do_sample 为 true 时启用采样策略，do_sample 为 false 时采样策略 temperature、top_p 将不生效
stream 	Boolean 	否 	使用同步调用时，此参数应当设置为 Fasle 或者省略。表示模型生成完所有内容后一次性返回所有内容。如果设置为 True，模型将通过标准 Event Stream ，逐块返回模型生成内容。Event Stream 结束时会返回一条data: [DONE]消息。
temperature 	Float 	否 	采样温度，控制输出的随机性，必须为正数 取值范围是：[0.0,1.0]， 默认值为 0.8，值越大，会使输出更随机，更具创造性；值越小，输出会更加稳定或确定 建议您根据应用场景调整 top_p 或 temperature 参数，但不要同时调整两个参数
top_p 	Float 	否 	用温度取样的另一种方法，称为核取样 取值范围是：[0.0, 1.0]，默认值为 0.6 模型考虑具有 top_p 概率质量 tokens 的结果 例如：0.1 意味着模型解码器只考虑从前 10% 的概率的候选集中取 tokens 建议您根据应用场景调整 top_p 或 temperature 参数，但不要同时调整两个参数
max_tokens 	Integer 	否 	模型最大输出 tokens
user_id 	String 	否 	终端用户的唯一ID，协助平台对终端用户的违规行为、生成违法及不良信息或其他滥用行为进行干预。ID长度要求：最少6个字符，最多128个字符。 了解更多
Messages 格式

模型可接受的消息类型包括 User message、Assistant message ，不同的消息类型格式有所差异。具体如下：
User message
参数名称 	类型 	必填 	参数说明
role 	String 	是 	消息的角色信息，此时应为user
content 	List<Object> 	是 	消息内容。
 type 	String 	是 	文本类型：text
图片类型：image_url
视频类型：video_url
视频和图片类型不能同时输入
 text 	String 	是 	type是text 时补充
 image_url 	Object 	是 	type是image_url 时补充
  url 	String 	是 	图片url或者base64编码。
图像大小上传限制为每张图像 5M以下，且像素不超过 6000*6000。
支持jpg、png、jpeg格式。
说明： GLM-4V-Flash 不支持base64编码
 video_url 	Object 	是 	type是video_url 时补充，仅glm-4v-plus支持视频输入
视频理解时，video_url参数必须在第一个。
  url 	String 	是 	视频url地址。
GLM-4V-Plus视频大小限制为20M以内，视频时长不超过 30s。
GLM-4V-Plus-0111视频大小限制为 200M 以内。
视频类型： mp4 。
Assistant message
参数名称 	类型 	必填 	参数说明
role 	String 	是 	消息的角色信息，此时应为assistant
content 	String 	是 	消息内容
响应参数
参数名称 	类型 	参数说明
id 	String 	任务 ID
created 	Long 	请求创建时间，是以秒为单位的 Unix 时间戳。
model 	String 	模型名称
choices 	List 	当前对话的模型输出内容
 index 	Integer 	结果下标
 finish_reason 	String 	模型推理终止的原因。
stop代表推理自然结束或触发停止词。
length 代表到达 tokens 长度上限。
sensitive 代表模型推理内容被安全审核接口拦截。
network_error 代表模型推理异常。
 message 	Object 	模型返回的文本信息
  role 	String 	当前对话的角色，目前默认为 assistant（模型）
  content 	List 	当前对话的内容
usage 	Object 	结束时返回本次模型调用的 tokens 数量统计
 prompt_tokens 	Integer 	用户输入的 tokens 数量
 completion_tokens 	Integer 	模型输出的 tokens 数量
 total_tokens 	Integer 	总 tokens 数量
content_filter 	List 	返回内容安全的相关信息
 role 	String 	安全生效环节，包括
role = assistant 模型推理，
role = user 用户输入，
role = history 历史上下文
 level 	Integer 	严重程度 level 0-3，level 0表示最严重，3表示轻微
请求示例
上传视频 URL

#视频理解示例、上传视频URL
from zhipuai import ZhipuAI

client = ZhipuAI(api_key="YOUR API KEY") # 填写您自己的APIKey
response = client.chat.completions.create(
    model="glm-4v-plus-0111",  # 填写需要调用的模型名称
    messages=[
      {
        "role": "user",
        "content": [
          {
            "type": "video_url",
            "video_url": {
                "url" : "https://sfile.chatglm.cn/testpath/video/xxxxx.mp4"
            }
          },
          {
            "type": "text",
            "text": "请仔细描述这个视频"
          }
        ]
      }
    ]
)
print(response.choices[0].message)

上传图片 URL

from zhipuai import ZhipuAI
client = ZhipuAI(api_key="") # 填写您自己的APIKey
response = client.chat.completions.create(
    model="glm-4v-plus-0111",  # 填写需要调用的模型名称
    messages=[
       {
        "role": "user",
        "content": [
          {
            "type": "text",
            "text": "图里有什么"
          },
          {
            "type": "image_url",
            "image_url": {
                "url" : "https://img1.baidu.com/it/u=1369931113,3388870256&fm=253&app=138&size=w931&n=0&f=JPEG&fmt=auto?sec=1703696400&t=f3028c7a1dca43a080aeb8239f09cc2f"
            }
          }
        ]
      }
    ]
)
print(response.choices[0].message)

上传图片 Base64

import base64
from zhipuai import ZhipuAI

img_path = "/Users/YourCompluter/xxxx.jpeg"
with open(img_path, 'rb') as img_file:
    img_base = base64.b64encode(img_file.read()).decode('utf-8')

client = ZhipuAI(api_key="YOUR API KEY") # 填写您自己的APIKey
response = client.chat.completions.create(
    model="glm-4v-plus-0111",  # 填写需要调用的模型名称
    messages=[
      {
        "role": "user",
        "content": [
          {
            "type": "image_url",
            "image_url": {
                "url": img_base
            }
          },
          {
            "type": "text",
            "text": "请描述这个图片"
          }
        ]
      }
    ]
)
print(response.choices[0].message)

多轮图片对话

from zhipuai import ZhipuAI

client = ZhipuAI(api_key="YOUR API KEY") # 填写您自己的APIKey
response = client.chat.completions.create(
    model="glm-4v-plus-0111",  # 填写需要调用的模型名称
    messages=[
      {
          "content": [
              {
                  "image_url": {
                      "url": "https://cdn.bigmodel.cn/xxxxxx.png"
                  },
                  "type": "image_url"
              },
              {
                  "text": "图中有什么",
                  "type": "text"
              }
          ],
          "role": "user"
      },
      {
          "content": [
              {
                  "text": "这是一幅描绘自然风景的画，展现了一片宁静的湖泊，湖水呈现出深浅不一的蓝绿色调。湖边长着一棵盛开的樱花树，粉白色的花朵在阳光下显得格外鲜艳。树下有一位身穿蓝色衣服的人坐在船上，似乎正在享受这美好的时光。\n\n背景是连绵起伏的山脉，山体被绿色的植被覆盖，山顶则被云雾缭绕，增添了几分神秘感。远处还可以看到一座小亭子，它坐落在湖边的岩石上，与周围的自然环境和谐相融。\n\n整个画面给人一种宁静、和谐的感觉，仿佛置身于一个世外桃源之中。",
                  "type": "text"
              }
          ],
          "role": "assistant"
      },
      {
          "content": [
              {
                  "image_url": {
                      "url": "https://cdn.bigmodel.cn/xxxxxxx.jpeg"
                  },
                  "type": "image_url"
              },
              {
                  "text": "这个图与上面图有什么不一样",
                  "type": "text"
              }
          ],
          "role": "user"
      },
      {
          "content": [
              {
                  "text": "第一张图和第二张图在画面内容、构图、色彩等方面都有很大的不同，形成鲜明的对比。\n\n1.第一张图是风景画，主要描绘了自然风景，如樱花树、湖泊、山脉等，色彩丰富，充满春天的气息，而第二张图是描绘长城在冬季的风景照片，长城在白雪覆盖的山脉中蜿蜒盘旋，整体色调偏冷，给人一种寒冷、宁静的感觉。\n\n2.构图上，第一张图采用对称式构图，以樱花树为中心，两侧的景物相互呼应，形成平衡和谐的画面效果，第二张图则采用对角线构图，长城作为视觉引导线，引导观众的视线穿越整个画面，增加画面的深度和动态感。\n\n整体来看，这两张图在画面内容、色彩、构图和氛围上都呈现出明显的对比，一张是充满生机和色彩的春日风景画，另一张是宁静而神秘的冬日长城风景照。",
                  "type": "text"
              }
          ],
          "role": "assistant"
      },
      {
          "content": [
              {
                  "image_url": {
                      "url": "https://cdn.bigmodel.cn/xxxxxxx.jpeg"
                  },
                  "type": "image_url"
              },
              {
                  "text": "这个图与上一张图有什么区别",
                  "type": "text"
              }
          ],
          "role": "user"
      }
    ]
)
print(response.choices[0].message)

响应示例

{
    "created": 1703487403,
    "id": "8239375684858666781",
    "model": "glm-4v-plus-0111",
    "request_id": "8239375684858666781",
    "choices": [
        {
            "finish_reason": "stop",
            "index": 0,
            "message": {
                "content": "图中有一片蓝色的海和蓝天，天空中有白色的云朵。图片的右下角有一个小岛或者岩石，上面长着深绿色的树木。",
                "role": "assistant"
            }
        }
    ],
    "usage": {
        "completion_tokens": 37,
        "prompt_tokens": 1037,
        "total_tokens": 1074
    }
  }

流式输出
响应参数
参数名称 	类型 	参数说明
id 	String 	任务 ID
created 	Long 	请求创建时间，是以秒为单位的 Unix 时间戳。
choices 	List 	当前对话的模型输出内容
 index 	Integer 	结果下标
 finish_reason 	String 	模型推理终止的原因。
stop代表推理自然结束或触发停止词。
length 代表到达 tokens 长度上限。
sensitive 代表模型推理内容被安全审核接口拦截。
network_error 代表模型推理异常。
 delta 	Object 	模型增量返回的文本信息
  role 	String 	当前对话的角色，目前默认为 assistant（模型）
  content 	String 	当前对话的内容
usage 	Object 	本次模型调用的 tokens 数量统计
 prompt_tokens 	Integer 	用户输入的 tokens 数量
 completion_tokens 	Integer 	模型输出的 tokens 数量
 total_tokens 	Integer 	总 tokens 数量
content_filter 	List 	返回内容安全的相关信息
 role 	String 	安全生效环节，包括
role = assistant 模型推理，
role = user 用户输入，
role = history 历史上下文
 level 	Integer 	严重程度 level 0-3，level 0 表示最严重，3 表示轻微
请求示例

from zhipuai import ZhipuAI
client = ZhipuAI(api_key="") # 请填写您自己的APIKey
response = client.chat.completions.create(
    model="glm-4v-plus-0111",  # 填写需要调用的模型名称
    messages=[
        {
          "role": "user", 
          "content": [
            {
              "type": "image_url",
              "image_url": {
                "url" : "sfile.chatglm.cn/testpath/xxxx.jpg"
              }
            },
            {
              "type": "text",
              "text": "图里有什么"
            }
          ]
        },
    ],
    stream=True,
)
for chunk in response:
    print(chunk.choices[0].delta)

响应示例

data: {"id":"8305986882425703351","created":1705476637,"model":"glm-4v-plus-0111","choices":[{"index":0,"delta":{"role":"assistant","content":"下"}}]}
data: {"id":"8305986882425703351","created":1705476637,"model":"glm-4v-plus-0111","choices":[{"index":0,"delta":{"role":"assistant","content":"角"}}]}
data: {"id":"8305986882425703351","created":1705476637,"model":"glm-4v-plus-0111","choices":[{"index":0,"delta":{"role":"assistant","content":"有一个"}}]}
... ...
data: {"id":"8305986882425703351","created":1705476637,"model":"glm-4v-plus-0111","choices":[{"index":0,"delta":{"role":"assistant","content":"树木"}}]}
data: {"id":"8305986882425703351","created":1705476637,"model":"glm-4v-plus-0111","choices":[{"index":0,"delta":{"role":"assistant","content":"。"}}]}
data: {"id":"8305986882425703351","created":1705476637,"model":"glm-4v-plus-0111","choices":[{"index":0,"finish_reason":"stop","delta":{"role":"assistant","content":""}}],"usage":{"prompt_tokens":1037,"completion_tokens":37,"total_tokens":1074}}

