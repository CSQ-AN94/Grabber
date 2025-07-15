# Grabber 系统架构文档

## 概述

Grabber 是一个智能零售机器人系统，采用模块化、可扩展的架构设计。系统集成了6自由度机械臂、线性导轨、深度相机和AI语音交互功能，专为智能零售比赛任务而设计。

## 架构原则

1. **模块化设计** - 各组件独立开发和测试
2. **感知-决策分离** - 感知层、决策层和执行层解耦
3. **执行可中断** - 所有操作支持安全中断
4. **配置驱动** - 通过配置文件管理所有参数
5. **容器化部署** - 支持Docker容器化开发和部署


## 核心组件

### 1. 应用层 (main.py)

**职责**: 系统启动、生命周期管理、任务调度

**主要功能**:
- 系统初始化和资源管理
- 比赛任务调度 (A/B/C/D任务)
- 语音交互模式
- 安全关闭流程

**接口**:
```python
class GrabberSystem:
    def __init__(config_path: str = 'config.ini')
    def run_main_loop()
    def task_a_inventory_scan()
    def task_b_image_recommendation()
    def task_c_voice_shopping()
    def task_d_checkout_calculation()
    def shutdown()
```

### 2. 智能决策层 (intelligence/)

#### 2.1 Gemini Agent (gemini_agent.py)
**职责**: Google Gemini Live API语音交互

**主要功能**:
- 实时语音识别和处理
- 自然语言理解
- 工具函数调用
- 音频流处理和重采样

**接口**:
```python
class GeminiAgent:
    def __init__(llm_config, agent_config, tool_registry)
    async def start_interactive_session(command_callback)
    async def stop_session()
```

#### 2.2 机器人工具 (robot_tools.py)
**职责**: 为AI Agent提供可调用的机器人功能

**主要功能**:
- 库存扫描和播报
- 商品抓取 (按名称/位置/语义)
- 商品推荐
- 结账计算

**接口**:
```python
class MockRobotTools:
    async def scan_inventory(announce: bool = True)
    async def grab_item_by_name(item_name: str)
    async def grab_item_by_position(reference_item: str, direction: str)
    async def grab_item_by_semantic(category: str)
    async def calculate_checkout()
```

#### 2.3 计算机视觉 (vision.py)
**职责**: YOLOv8物体检测和分析

**主要功能**:
- 实时物体检测
- 商品识别和定位
- 场景理解

#### 2.4 语音系统 (speech.py)
**职责**: 文本转语音

**主要功能**:
- iFlytek TTS语音合成
- 音频处理

### 3. 硬件控制层 (controllers/)

#### 3.1 机械臂控制器 (arm_controller.py)
**职责**: 睿尔曼RM-65B机械臂控制

**主要功能**:
- 关节空间运动控制
- 笛卡尔空间运动控制
- 实时状态监控
- 安全限制检查

**接口**:
```python
class ArmController:
    def move_to_joints(joint_angles, speed=30, wait=True)
    def move_to_cartesian_pose(pose, speed=30, wait=True)
    def get_current_joint_angles()
    def get_base_to_end_pose_matrix()
    def set_gripper_openness(openness)
```

#### 3.2 导轨控制器 (rail_controller.py)
**职责**: 线性导轨定位控制

**主要功能**:
- 精确位置控制
- 速度和加速度管理
- 位置反馈

#### 3.3 夹爪控制器 (集成在arm_controller.py)
**职责**: Modbus RTU夹爪控制

**主要功能**:
- 开合度控制
- 状态监控

### 4. 传感器层 (sensors/)

#### 4.1 相机线程 (camera_thread.py)
**职责**: Orbbec深度相机管理

**主要功能**:
- 连续图像采集
- 彩色和深度图像同步
- 相机内参标定
- 线程安全的帧访问

**接口**:
```python
class CameraThread:
    def start()
    def stop()
    def get_camera_intrinsics()
```

### 5. 基础设施层 (utils/)

#### 5.1 配置管理 (config.py)
**职责**: 统一配置管理

**主要功能**:
- 配置文件解析
- 环境变量支持
- 配置验证
- 日志设置

#### 5.2 状态管理 (state.py)
**职责**: 线程安全的系统状态管理

**主要功能**:
- 机器人状态跟踪
- 世界地图管理
- 商品信息维护
- 线程安全访问

#### 5.3 手眼标定 (calibration.py)
**职责**: 坐标系变换和标定

**主要功能**:
- 像素到世界坐标变换
- 手眼标定矩阵管理
- 正向/逆向运动学

## 数据流

### 感知数据流
```
Orbbec相机 → 相机线程 → 共享状态 → 视觉分析 → 世界地图更新
```

### 控制数据流
```
用户指令 → Gemini Agent → 机器人工具 → 硬件控制器 → 物理执行
```

### 状态数据流
```
硬件状态 → 控制器 → 共享状态 → 状态监控 → 安全检查
```

## 关键接口

### 1. 工具注册接口
```python
class ToolRegistry:
    def get_tool_definitions() -> list
    async def execute_tool(tool_name: str, parameters: dict) -> dict
```

### 2. 命令响应接口
```python
@dataclass
class RobotCommand:
    action: str
    parameters: dict
    response_text: str
    confidence: float
```

### 3. 标准响应格式
```python
{
    "success": bool,
    "message": str,
    "data": any,
    "execution_time": float,
    "error": str  # 仅在失败时存在
}
```