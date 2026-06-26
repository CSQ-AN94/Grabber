# Grabber - 直接识别抓取版本

**当前阶段目标：识别商品，接收明确商品指令，然后直接抓取。**

这个分支面向双臂 Realman + RealSense 迁移调试。自然语言、语音和 Gemini Agent 暂时不是主路径；主入口是 `direct_grab.py`，流程是：

1. 初始化 YOLO 商品识别、RealSense 相机、Realman 机械臂。
2. 扫描当前可见商品。
3. 操作者输入商品名或编号。
4. 系统按确定性指令执行抓取。

旧的 `main_agent.py` 和 Gemini/语音模块仍保留在仓库里，后续需要自然语言交互时再接回。

## 当前主入口

```bash
python3 direct_grab.py
```

交互命令：

```text
scan        # 重新扫描
红牛         # 抓取识别列表中的“红牛”
1           # 抓取当前识别列表的第 1 个商品
抓 红牛      # 同上
q           # 退出
```

一次性命令：

```bash
python3 direct_grab.py scan
python3 direct_grab.py grab 红牛
```

`grab` 会先扫描一次用于确认/解析商品名，然后调用抓取流程。输入商品名必须能和 YOLO 输出的中文商品名匹配；支持唯一子串匹配，例如识别到“可口可乐”时输入“可乐”。

## 当前架构

#### 智能决策层 (`intelligence/`)
- **`vision.py`**: YOLOv8 商品检测。
- **`robot_tools.py`**: 确定性工具函数，提供 `scan_shelf()` 和 `execute_grab(item_name)`。
- **`gemini_agent.py` / `speech.py` / `voice_manager.py`**: 旧自然语言/语音入口，当前直接抓取版本不依赖。

#### 硬件控制层 (`controllers/`)
- **`arm_controller.py`**: Realman 官方 `robotic-arm` SDK 控制机械臂和 Realman Plus 夹爪。
- **`ugv_controller.py`**: AgileX 底盘控制，当前直接抓取主路径暂不使用。

#### 传感器层 (`sensors/`)
- **`camera_thread.py`**: RealSense 彩色/深度流处理。

#### 工具层 (`utils/`)
- **`config.py`**: 统一配置管理。
- **`calibration.py`**: 手眼标定和坐标变换。
- **`items_info.py`**: 商品数据库。

#### 抓取流程 (`references/`)
- **`enhanced_grab_interface.py`**: 直接抓取流程。它现在不再导入旧 `main_workflow`，避免把旧 RM_API2 控制器拉进当前路径。

---

## 运行方式

### 环境要求

- Ubuntu 22.04 或对应机器人主机环境
- Python 3.10+
- NVIDIA GPU 运行 YOLO
- RealSense 深度相机
- Realman 机械臂网络可达

### 推荐路径：机器人主机 Python 环境

当前分支还没有在 Docker 内完整验证过 RealSense、Realman SDK、GPU、USB/CAN 权限组合。迁移调试时，优先在机器人主机的 Python 环境里跑：

```bash
pip install -r requirements.txt
python3 direct_grab.py
```

最小冒烟测试：

```bash
python3 direct_grab.py --help
python3 direct_grab.py scan
python3 direct_grab.py grab 红牛
```

### Docker 状态说明

Docker 相关文件是**开发容器草案**，不是已经验证过的机器人部署方式。

- [Dockerfile](Dockerfile) 会构建 CUDA/Jetson 基础镜像，安装系统包和 `requirements.txt`。
- 当前分支使用 RealSense，因此 Dockerfile 不再编译旧 Orbbec `pyorbbecsdk`。
- [docker-compose.yml](docker-compose.yml) 使用 `privileged: true`、`network_mode: host`，挂载 USB、声卡、X11、PulseAudio，并声明 GPU。
- compose 里有 `command: tail -f /dev/null`，所以 `docker compose up` 只是让容器常驻，不会自动运行抓取程序。
- 这套 Docker 配置还没有在目标机器人上确认过 `pyrealsense2`、`robotic-arm`、GPU、USB 设备映射是否都可用。

如果要试 Docker，建议按“先建容器，再手动进容器跑命令”的方式：

```bash
git clone <repository-url>
cd Grabber

docker compose build
docker compose up -d
docker compose exec grabber_dev bash
```

进入容器后再检查：

```bash
nvidia-smi
python3 -c "import pyrealsense2 as rs; print('realsense ok')"
python3 -c "from Robotic_Arm.rm_robot_interface import RoboticArm; print('realman sdk ok')"
python3 direct_grab.py --help
```

这些检查通过后，再接真实硬件扫描和抓取。

### 标定状态

`config.yaml` 里的机械臂点位、放置点和手眼标定仍然是迁移初始值。直接模式可以作为软件连通和流程调试入口；上真实货架抓取前，需要重新标定：

- 左右臂 IP 和 `active_arm`
- 货架扫描/抓取位姿
- RealSense 手眼矩阵
- 放置点位姿
- 夹爪开闭时间和力度策略

## 项目结构详解

```
Grabber/
├── direct_grab.py                # 当前主入口：无 Gemini 的直接扫描/抓取
├── main_agent.py                 # 旧 Agent/语音入口，当前非主路径
├── config.yaml                   # 统一系统配置
├── requirements.txt               # pip依赖
├── docker-compose.yml            # 容器编排配置
├── Dockerfile                    # 多架构镜像构建
│
├── intelligence/                  # AI相关
│   ├── gemini_agent.py           # 旧 Gemini AI 核心
│   ├── robot_tools.py            # scan/grab 工具函数库
│   ├── vision.py                 # YOLOv8视觉检测系统
│   ├── speech.py                 # 旧 iFlytek 语音合成
│   ├── voice_manager.py          # 旧语音状态机管理
|   ├── audio_models/             # 语音onnx模型文件
│   └── yolo_models/              # yolo模型文件
│
├── controllers/                   # 硬件控制包装
│   ├── arm_controller.py         # 机械臂+夹爪控制器
│   └── ugv_controller.py         # 移动底盘控制器
│
├── sensors/                       # 传感器接口
│   └── camera_thread.py          # RealSense 相机包装
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
├── external/                      # 历史子模块，当前 direct_grab 主路径不依赖
```
