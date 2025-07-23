# Grabber - 智能零售机器人系统

一个智能零售机器人系统，结合6自由度机械臂（Realman RM-65B）与UGV底盘（AgileX Ranger Mini 3），实现自动库存扫描、物体识别和精确抓取。使用Google Gemini Live API进行实时语音交互，采用"感知-决策分离，执行可中断"的架构设计。

## 当前状态

目前处于**核心功能集成阶段**：

- ✅ **硬件控制层**: 完整的机械臂、相机、夹爪控制
- ✅ **视觉系统**: YOLOv11目标检测，支持中文标签和深度信息
- ✅ **音频输出**: iFlytek TTS，生产者消费者架构，完整句子播放
- ⚠️ **音频输入**: 基础实现存在，VAD功能待修复
- ⚠️ **AI集成**: Gemini Live API基础架构完成，集成调试中
- ⚠️ **精细抓取**: 硬编码坐标可用，精确标定和TCP待完成

## 系统架构

系统采用严格的模块化架构，遵循"真实硬件优先、生产代码纯净、组件解耦"原则：

### 核心组件

**主入口**
- `main.py`: 异步任务管理器和事件循环中心，管理GeminiAgent和RobotTools集成

**智能层 (`intelligence/`)**
- `gemini_agent.py`: 基于Gemini Live API的语音交互代理，集成工具函数调用
- `robot_tools.py`: 连接AI决策与硬件执行的工具函数库（当前Mock，待真实实现）
- `vision.py`: YOLOv11物体检测和分析，支持中文文本绘制
- `speech_local.py`: iFlytek WebAPI异步语音合成，队列化处理

**硬件控制层 (`controllers/`)**
- `arm_controller.py`: Realman RM-65B机械臂控制，集成Modbus RTU夹爪接口
- `ugv_controller.py`: AgileX Ranger Mini 3 UGV控制系统

**传感器层 (`sensors/`)**
- `camera_thread.py`: Orbbec相机连续帧捕获和缓冲管理
- `smart_microphone.py`: 智能麦克风输入，集成VAD和实时音频流处理

**工具层 (`utils/`)**
- `state.py`: 线程安全的世界状态管理，包含完整商品数据库
- `config.py`: 统一配置管理，已清理单位换算问题
- `calibration.py`: 手眼标定和坐标变换系统

**接口抽象 (`interfaces/`)**
- `audio_input.py`: 音频输入接口抽象，支持多种音频源

## 核心功能

### 已实现功能
- ✅ **实时语音合成**: 基于iFlytek WebAPI的异步TTS系统
- ✅ **物体检测**: YOLOv11实时检测，支持中文标签和深度信息
- ✅ **硬件控制**: 机械臂、夹爪的完整控制接口
- ✅ **状态管理**: 线程安全的世界状态，包含商品数据库和位置信息
- ✅ **手眼标定基础**: 坐标变换框架（需要新标定数据）

### 开发中功能
- 🔧 **语音输入**: SmartMicrophone基础实现，VAD功能调试中
- 🔧 **AI集成**: Gemini Live API集成，音频格式适配优化中
- 🔧 **精细抓取**: 基础坐标可用，TCP标定和视觉引导待完成

## 快速开始

### 开发环境

**所有开发都在Docker容器内进行，禁止在主机系统上运行代码：**

```bash
# 构建容器镜像
docker compose build

# 进入开发容器
docker compose run --rm grabber_dev bash

# 验证硬件访问
nvidia-smi                  # 验证GPU访问
```

### 初始化依赖

项目包含关键的git子模块：

```bash
git submodule update --init --recursive
```

**依赖管理**：
- 系统依赖：通过Dockerfile中的`apt install`
- Python依赖：通过`requirements.txt`统一管理
- SDK依赖：通过`external/`目录的git子模块

### 系统测试

**硬件测试**（需要真实硬件）：
```bash
python3 scripts/test_arm.py         # 机械臂和夹爪测试
python3 scripts/test_ugv.py         # UGV控制测试
python3 scripts/test_camera.py      # 相机捕获测试
python3 scripts/test_calibration.py # 手眼标定测试
```

**软件测试**（容器内可运行）：
```bash
python3 scripts/collect_images.py        # 数据采集工具
```

## 配置管理

所有系统配置集中在`config.ini`中：

- **硬件连接**: 机械臂IP、相机设置、UGV参数
- **AI配置**: Gemini API密钥、音频设置、模型路径
- **标定数据**: 手眼变换矩阵（T_end_to_camera）
- **操作参数**: 关节姿态、速度、阈值

**注意**: 开发环境中API密钥已提交到配置文件，生产部署时使用环境变量覆盖。

## 代码质量标准
- **详细注释**: 特别是单位转换、坐标变换、异步流程
- **统一错误格式**: `{"success": bool, "message": str, "error": str}`
- **类型注解**: 复杂函数添加类型注解
- **单位一致性**: 明确标注所有物理量单位

## 精细抓取系统

### 开发路径
1. **手眼标定**: 基于清理后的单位系统重新标定
2. **TCP标定**: 使用RM_API2获取工具坐标系
3. **精确测试**: 夹爪中心到相机画面中心20cm深度点
4. **AnyGrasp集成**: 抓取位姿估计算法（见`docs/AnyGrasp_Usage.md`）
5. **真实grasp_by_id()**: 替换Mock实现

### 坐标系统
- **世界坐标**: UGV零点
- **基座坐标系**：机械臂基座，目前与世界坐标系是同一个
- **相机坐标**: Orbbec相机光心坐标系
    - `transform_pixel_to_world()`, 相机坐标系到世界坐标系
- **工具坐标**: 夹爪中心点（TCP）

## 项目结构

```
Grabber/
├── main.py                   # 主入口点
├── config.ini               # 系统配置文件
├── controllers/             # 硬件控制模块
│   ├── arm_controller.py    # 机械臂控制
│   └── ugv_controller.py    # UGV控制
├── intelligence/            # AI/视觉/语音模块
│   ├── gemini_agent.py      # Gemini语音交互代理
│   ├── robot_tools.py       # 机器人工具函数
│   ├── vision.py            # YOLOv11视觉分析
│   ├── speech_local.py      # iFlytek语音合成
│   ├── models/              # YOLOv11模型文件
│   └── data/                # 训练图像数据
├── sensors/                 # 传感器接口
│   ├── camera_thread.py     # 相机线程管理
│   └── smart_microphone.py  # 智能麦克风输入
├── utils/                   # 工具和配置
│   ├── state.py             # 世界状态管理
│   ├── config.py            # 配置加载
│   └── calibration.py       # 手眼标定
├── scripts/                 # 测试和工具脚本
│   ├── test_*.py            # 各种测试脚本
│   ├── collect_images.py    # 数据采集
│   └── simple_reach_test.py # 精细抓取测试
├── docs/                    # 项目文档
├── external/                # Git子模块
│   ├── RM_API2/             # 睿尔曼机械臂SDK
│   └── pyorbbecsdk/         # Orbbec相机SDK
└── grabber_demo.py          # 硬编码的演示脚本
```