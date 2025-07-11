ARG TARGETPLATFORM

# amd64带显卡笔记本的基础镜像
FROM nvidia/cuda:12.8.0-devel-ubuntu22.04 AS base-amd64
# jetson orin 的基础镜像
FROM dustynv/l4t-pytorch:r36.4.0 AS base-arm64

# --- 环境配置 ---
FROM base-${TARGETPLATFORM#linux/}
# 设置为非交互模式，防止apt在构建时卡住
ENV DEBIAN_FRONTEND=noninteractive
# 确保Python输出是无缓冲的, 日志会立刻显示
ENV PYTHONUNBUFFERED=1

# --- 安装系统依赖 ---
RUN apt-get update && apt-get install -y \
    tmux htop net-tools nmap tree xclip curl wget vim\
    python3-pip \
    python3-dev \
    python3-venv \
    python3-opencv \
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
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# --- 设置工作目录并拷贝pip依赖相关文件 ---
WORKDIR /app
COPY requirements.txt .

# --- 安装Python核心依赖 ---
RUN pip install --no-cache-dir -r requirements.txt

COPY external/ ./external/

# --- 编译并强制安装pyorbbecsdk ---
RUN cd /app/external/pyorbbecsdk && \
    echo "Skipping sdk's requirements.txt to avoid pre-installation." && \
    mkdir -p build && cd build && \
    cmake -Dpybind11_DIR=$(pybind11-config --cmakedir) .. && \
    make -j$(nproc) && \
    make install && \
    cd .. && \
    python3 setup.py bdist_wheel && \
    pip install --force-reinstall ./dist/pyorbbecsdk-*.whl && \
    rm -rf /app/external/pyorbbecsdk/build /app/external/pyorbbecsdk/dist
# --- 安装udev规则 ---
RUN bash /app/external/pyorbbecsdk/scripts/install_udev_rules.sh

COPY . .
ENV PYTHONPATH=/app
CMD ["bash"]