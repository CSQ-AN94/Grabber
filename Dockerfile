# 基础镜像: 完全遵照你的选择
FROM nvidia/cuda:12.8.0-devel-ubuntu22.04

# --- 环境配置 ---
# 设置为非交互模式，防止apt在构建时卡住
ENV DEBIAN_FRONTEND=noninteractive
# 确保Python输出是无缓冲的, 日志会立刻显示
ENV PYTHONUNBUFFERED=1

# --- 安装系统依赖 ---
# Ubuntu 22.04 默认就是 Python 3.10，我们只需安装pip和必要的库
RUN apt-get update && apt-get install -y \
    python3-pip \
    python3-dev \
    python3-venv \
    python3-opencv \
    git \
    cmake \
    libusb-1.0.0-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    portaudio19-dev \
    libasound2-dev \
    && rm -rf /var/lib/apt/lists/*

# --- 安装Python依赖 ---
COPY requirements.txt .
# 使用pip安装所有指定的Python包
RUN pip install --no-cache-dir -r requirements.txt

ENV PYTHONPATH="${PYTHONPATH}:/app/external/RM_API2/Python"

WORKDIR /app
COPY . .

# RUN pip install /app/external/RM_API2/Python
# RUN pip install /app/external/pyorbbecsdk

# --- 容器启动命令 ---
# 为开发环境提供一个bash终端，这是最灵活的方式
CMD ["bash"]