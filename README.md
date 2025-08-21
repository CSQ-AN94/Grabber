# Grabber - 智能零售机器人系统

**基于Agent驱动架构的智能零售机器人系统**

一个集成6自由度机械臂(Realman RM-65B)和RGBD相机(Orbbec Gemini 336L)的智能零售机器人，通过Google Gemini + SpeechRecognition + porcupine实现自然语言交互，支持语音聊天、商品识别、自动抓取、结算商品等功能。采用Agent为中心的架构设计。

## 项目概览

### 核心特性

- **AI驱动决策**: Google Gemini 2.5 Flash模型，支持自然语言理解和工具函数自动调用
- **双向语音交互**: 唤醒词激活 + 语音识别 + TTS语音反馈的完整对话系统
- **智能视觉识别**: YOLOv8目标检测，支持16种零售商品的实时识别和定位
- **精准操作控制**: 6DOF机械臂 + 自适应夹爪 + 手眼标定的毫米级抓取精度
- **灵活运动平台**: 全向移动底盘，支持自主导航和精确定位
- **完整购物体验**: 从商品扫描、智能推荐到抓取放置的全流程自动化

## Agent驱动架构

### main_agent.py

`main_agent.py`为系统入口：

1. **语音唤醒**: 用户说"小浦"激活系统
2. **TTS响应**: 机器人语音回复"我在"
3. **语音录制**: 自动录音5秒捕获用户指令
4. **AI理解**: Gemini分析语音内容并决策
5. **工具调用**: 自动调用相应的robot_tools函数
6. **硬件执行**: 实际控制机械臂、相机等硬件
7. **结果反馈**: 语音播报执行结果

### 架构分层设计

#### 智能决策层 (`intelligence/`)
- **`gemini_agent.py`**: 基于Gemini API的agent，负责自然语言理解和决策
- **`robot_tools.py`**: 工具函数库，连接AI决策与硬件执行
- **`vision.py`**: YOLOv8视觉分析，16种商品实时检测
- **`speech.py`**: iFlytek TTS异步语音合成
- **`voice_input.py`**: 唤醒词激活和语音识别

#### 硬件控制层 (`controllers/`)
- **`arm_controller.py`**: Realman RM-65B机械臂控制 + Modbus RTU夹爪
- **`ugv_controller.py`**: AgileX Ranger Mini 3全向移动控制

#### 传感器层 (`sensors/`)
- **`camera_thread.py`**: Orbbec相机实时图像流处理

#### 工具层 (`utils/`)
- **`config.py`**: 统一配置管理（硬件连接、AI模型、标定数据）
- **`calibration.py`**: 手眼标定和坐标变换
- **`items_info.py`**: 商品数据库（价格、规格、抓取参数）

---

## 快速开始

### 环境要求

- **开发环境**: Ubuntu 22.04 + Docker
- **硬件要求**: NVIDIA GPU

### Docker环境搭建

**所有开发都在Docker容器内进行，确保环境一致性和硬件抽象：**

```bash
# 1. 克隆项目并初始化子模块
git clone <repository-url>
cd Grabber
git submodule update --init --recursive

# 2. 构建开发环境镜像
docker compose build

# 3. 进入开发容器
docker compose run --rm grabber_dev bash

# 4. 验证环境
nvidia-smi                    # 验证GPU访问
```

### 系统启动

```bash
# 在Docker容器内启动主程序
python3 main_agent.py
```

启动后根据需求选择运行模式：
- **测试agent**: 选择"Mock调试模式 + 文本交互"
- **测试语音**: 选择"Mock调试模式 + 语音交互" 
- **真实操作**: 选择"真实硬件模式 + 语音交互"

## 项目结构详解

```
Grabber/
├── main_agent.py                 # 系统入口
├── config.yaml                   # 统一系统配置
├── requirements.txt               # pip依赖
├── docker-compose.yml            # 容器编排配置
├── Dockerfile                    # 多架构镜像构建
│
├── intelligence/                  # AI相关
│   ├── gemini_agent.py           # Gemini AI核心
│   ├── robot_tools.py            # agent工具函数库
│   ├── vision.py                 # YOLOv8视觉检测系统
│   ├── speech.py                 # iFlytek语音合成
│   ├── voice_input.py            # 语音输入
│   └── models/                   # 模型文件
│       ├── 8_17.pt               # YOLOv8零售商品检测模型
│       ├── 小浦_zh_linux_v3_0_0.ppn  # 中文唤醒词模型
│       └── porcupine_params_zh.pv # Porcupine中文参数
│
├── controllers/                   # 硬件控制包装
│   ├── arm_controller.py         # 机械臂+夹爪控制器
│   └── ugv_controller.py         # 移动底盘控制器
│
├── sensors/                       # 传感器接口
│   └── camera_thread.py          # 相机包装
│
├── utils/                         # 工具和配置
│   ├── config.py                 # 配置加载
│   ├── calibration.py            # 手眼标定和坐标变换
│   ├── items_info.py             # 商品数据库
│   └── handeye_calibrator.py     # 标定工具实现
│
├── scripts/                       # 测试和工具脚本
│   ├── test_arm.py               # 机械臂功能测试
│   ├── test_ugv.py               # UGV移动测试
│   ├── test_camera.py            # 相机系统测试
│   ├── test_calibration.py       # 标定测试
│   ├── collect_images.py         # 数据采集工具
│   ├── test_audio_output.py       # 语音合成和播报测试
│   └── test_speech_recognition.py # 语音识别测试
│
├── external/                      # 外部依赖（Git子模块）
│   ├── RM_API2/                  # 睿尔曼机械臂官方SDK
│   ├── pyorbbecsdk/              # Orbbec相机官方SDK
│   └── pyagxrobots/              # AgileX移动底盘SDK（fork修复版）