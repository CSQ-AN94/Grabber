#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Docker容器内PulseAudio配置脚本
在容器启动时自动配置PulseAudio访问
"""

import os
import sys
import time
import subprocess
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def configure_pulseaudio_environment():
    """配置PulseAudio环境变量"""
    logger.info("配置PulseAudio环境变量...")
    
    # 设置关键环境变量
    pulse_env = {
        'PULSE_RUNTIME_PATH': '/run/user/1000/pulse',
        'PULSE_SERVER': 'unix:/run/user/1000/pulse/native',
        'XDG_RUNTIME_DIR': '/run/user/1000',
        'PULSE_STATE_PATH': '/run/user/1000/pulse',
        'PULSE_CONFIG_PATH': '/etc/pulse',
    }
    
    for key, value in pulse_env.items():
        os.environ[key] = value
        logger.info(f"设置环境变量: {key}={value}")
    
    return True


def check_pulseaudio_socket():
    """检查PulseAudio socket是否可用"""
    logger.info("检查PulseAudio socket...")
    
    socket_path = '/run/user/1000/pulse/native'
    
    if os.path.exists(socket_path):
        logger.info(f"✅ PulseAudio socket存在: {socket_path}")
        
        # 检查socket权限
        try:
            stat = os.stat(socket_path)
            logger.info(f"Socket权限: {oct(stat.st_mode)}")
            return True
        except Exception as e:
            logger.error(f"无法检查socket权限: {e}")
            return False
    else:
        logger.error(f"❌ PulseAudio socket不存在: {socket_path}")
        return False


def start_pulseaudio_daemon():
    """启动PulseAudio守护进程"""
    logger.info("尝试启动PulseAudio守护进程...")
    
    try:
        # 检查是否已经有PulseAudio进程
        result = subprocess.run(['pgrep', 'pulseaudio'], 
                              capture_output=True, text=True)
        
        if result.returncode == 0:
            logger.info("PulseAudio守护进程已经在运行")
            return True
        
        # 尝试启动PulseAudio
        cmd = ['pulseaudio', '--start', '--log-target=stderr', '-v']
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0:
            logger.info("✅ PulseAudio守护进程启动成功")
            return True
        else:
            logger.warning(f"PulseAudio启动失败: {result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.warning("PulseAudio启动超时")
        return False
    except FileNotFoundError:
        logger.warning("pulseaudio命令不存在")
        return False
    except Exception as e:
        logger.error(f"启动PulseAudio时发生错误: {e}")
        return False


def test_pulseaudio_devices():
    """测试PulseAudio设备是否可用"""
    logger.info("测试PulseAudio设备...")
    
    try:
        # 重新导入sounddevice以获取最新设备列表
        import sounddevice as sd
        
        # 强制重新初始化
        sd._terminate()
        sd._initialize()
        
        # 获取设备列表
        devices = sd.query_devices()
        
        pulse_devices = []
        for i, device in enumerate(devices):
            if device['max_output_channels'] > 0:
                device_name = device['name'].lower()
                if 'pulse' in device_name or 'default' in device_name:
                    pulse_devices.append((i, device))
                    logger.info(f"找到PulseAudio设备: [{i}] {device['name']}")
        
        if pulse_devices:
            logger.info(f"✅ 成功检测到 {len(pulse_devices)} 个PulseAudio设备")
            return True, pulse_devices
        else:
            logger.warning("❌ 未检测到PulseAudio设备")
            return False, []
            
    except Exception as e:
        logger.error(f"测试PulseAudio设备时发生错误: {e}")
        return False, []


def create_pulseaudio_config():
    """创建PulseAudio客户端配置"""
    logger.info("创建PulseAudio客户端配置...")
    
    config_dir = '/root/.config/pulse'
    config_file = os.path.join(config_dir, 'client.conf')
    
    try:
        # 确保配置目录存在
        os.makedirs(config_dir, exist_ok=True)
        
        # 创建客户端配置
        config_content = f"""
# PulseAudio客户端配置
default-server = unix:/run/user/1000/pulse/native
autospawn = no
daemon-binary = /usr/bin/pulseaudio
"""
        
        with open(config_file, 'w') as f:
            f.write(config_content)
        
        logger.info(f"✅ PulseAudio客户端配置创建成功: {config_file}")
        return True
        
    except Exception as e:
        logger.error(f"创建PulseAudio配置失败: {e}")
        return False


def fix_permissions():
    """修复权限问题"""
    logger.info("修复权限问题...")
    
    try:
        # 添加当前用户到audio组
        subprocess.run(['usermod', '-a', '-G', 'audio', 'root'], 
                      capture_output=True, text=True)
        
        # 设置socket权限
        socket_path = '/run/user/1000/pulse/native'
        if os.path.exists(socket_path):
            os.chmod(socket_path, 0o666)
            logger.info(f"✅ Socket权限已修复: {socket_path}")
        
        return True
        
    except Exception as e:
        logger.error(f"修复权限失败: {e}")
        return False


def main():
    """主配置流程"""
    logger.info("🔧 开始配置Docker容器内的PulseAudio...")
    
    success_steps = []
    
    # 1. 配置环境变量
    if configure_pulseaudio_environment():
        success_steps.append("环境变量配置")
    
    # 2. 检查socket
    if check_pulseaudio_socket():
        success_steps.append("Socket检查")
    
    # 3. 创建配置文件
    if create_pulseaudio_config():
        success_steps.append("配置文件创建")
    
    # 4. 修复权限
    if fix_permissions():
        success_steps.append("权限修复")
    
    # 5. 测试设备
    success, pulse_devices = test_pulseaudio_devices()
    if success:
        success_steps.append("设备检测")
    
    # 总结结果
    logger.info(f"\n📊 配置结果:")
    logger.info(f"成功步骤: {len(success_steps)}/5")
    for step in success_steps:
        logger.info(f"✅ {step}")
    
    if len(success_steps) >= 3:
        logger.info("🎉 PulseAudio配置基本成功！")
        return True
    else:
        logger.warning("⚠️ PulseAudio配置可能存在问题")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)