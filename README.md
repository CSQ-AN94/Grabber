## 使用
0. (Optional) 如果在Jetson上使用，建议ssh
    1. `ssh nb@192.168.3.10 -Y`
    2. 密码是`nb`
    3. `cd /app`到项目文件夹
1. 拉取仓库到本地
2. 根据具体IP和端口修改你的docker-compose.yml中的http_proxy和https_proxy
3. 一键构建镜像 `docker compose build`
4. 一键运行镜像 `docker compose run --rm grabber_dev bash`
5. 验证
    - `nvidia-smi` 验证显卡
    - `python3 utils/state.py` 验证相机/机械臂/夹爪工作状态

## 项目框架
```
Grabber/
│
├── main.py                 # 主程序入口
├── controllers/
│   ├── __init__.py
│   ├── arm_controller.py   # 封装机械臂和夹爪的控制
│   └── rail_controller.py  # 封装导轨的控制 (留出接口)
│
├── sensors/
│   ├── __init__.py
│   └── camera_thread.py    # 独立的摄像头线程，持续更新图像
│
├── intelligence/
│   ├── __init__.py
│   ├── vision.py           # 视觉分析 (YOLOv8)
│   ├── speech.py           # 语音识别与合成 (ASR/TTS)
│   └── llm_parser.py       # 大模型语义分析
│
├── utils/
│   ├── __init__.py
│   ├── state.py            # 共享的机器人状态和世界信息，线程安全
│   └── calibration.py      # 坐标系转换
|   └── config.py           # 处理config.ini，分发配置
│
├── config.ini              # 配置文件
└── requirements.txt
```