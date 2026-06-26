ARG TARGETPLATFORM

# amd64带显卡笔记本的基础镜像
FROM nvidia/cuda:12.4.1-devel-ubuntu22.04 AS base-amd64
# jetson orin 的基础镜像
FROM ultralytics/ultralytics:latest-jetson-jetpack6 AS base-arm64

# --- 环境配置 ---
FROM base-${TARGETPLATFORM#linux/}
# 设置为非交互模式，防止apt在构建时卡住
ENV DEBIAN_FRONTEND=noninteractive
# 确保Python输出是无缓冲的, 日志会立刻显示
ENV PYTHONUNBUFFERED=1

# --- 安装系统依赖 ---
RUN apt-get update && apt-get install -y \
    tmux htop net-tools nmap tree xclip curl wget vim \
    python3-pip \
    python3-dev \
    git \
    cmake \
    build-essential \
    libusb-1.0.0-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    portaudio19-dev \
    libasound2-dev \
    libudev-dev \
    alsa-utils \
    libpulse-dev \
    ffmpeg \
    can-utils \
    iproute2 \
    kmod \
    && rm -rf /var/lib/apt/lists/*

# --- 安装完整PulseAudio-ALSA生态系统 ---
RUN apt-get update && apt-get install -y \
    pulseaudio-utils \
    libpulsedsp \
    libasound2-plugins \
    && rm -rf /var/lib/apt/lists/*

# --- 设置工作目录并拷贝pip依赖相关文件 ---
WORKDIR /app
COPY requirements.txt .

# --- 安装Python核心依赖 ---
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONPATH=/app
CMD ["bash"]
