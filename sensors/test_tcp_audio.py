#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
TCP音频系统测试脚本
基于microphone_thread.py和speaker_thread.py的设计
"""

import asyncio
import time
import logging
import socket
import sys
import os
import argparse

# 设置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class TCPAudioTest:
    """TCP音频系统测试类"""
    
    def __init__(self, jetson_host="192.168.3.1", mic_port=8888, speaker_port=8889):
        self.jetson_host = jetson_host
        self.mic_port = mic_port
        self.speaker_port = speaker_port
        
    async def test_network_connectivity(self):
        """测试网络连通性"""
        logger.info("测试网络连通性...")
        
        try:
            # 测试多个端口
            test_ports = [22, self.mic_port, self.speaker_port, 80]
            successful_connections = 0
            
            for port in test_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(3)
                    start_time = time.time()
                    result = sock.connect_ex((self.jetson_host, port))
                    end_time = time.time()
                    sock.close()
                    
                    if result == 0:
                        latency = (end_time - start_time) * 1000
                        logger.info(f"  端口 {port}: 连通 (延迟: {latency:.1f}ms)")
                        successful_connections += 1
                    else:
                        logger.info(f"  端口 {port}: 不可达")
                        
                except Exception as e:
                    logger.info(f"  端口 {port}: 连接失败 ({e})")
            
            if successful_connections > 0:
                logger.info(f"网络连通性测试通过 ({successful_connections}/{len(test_ports)} 端口可达)")
                return True
            else:
                logger.error("网络连通性测试失败：所有端口均不可达")
                return False
                
        except Exception as e:
            logger.error(f"网络连通性测试失败: {e}")
            return False
    
    def test_audio_devices(self):
        """测试音频设备"""
        logger.info("测试音频设备...")
        
        try:
            import sounddevice as sd
            
            # 列出设备
            devices = sd.query_devices()
            logger.info("可用音频设备:")
            
            input_devices = []
            output_devices = []
            
            for i, device in enumerate(devices):
                if device['max_input_channels'] > 0:
                    input_devices.append((i, device['name']))
                    logger.info(f"  输入设备 {i}: {device['name']}")
                if device['max_output_channels'] > 0:
                    output_devices.append((i, device['name']))
                    logger.info(f"  输出设备 {i}: {device['name']}")
            
            # 查找合适的设备
            suitable_input = False
            suitable_output = False
            
            for device_id, name in input_devices:
                if any(keyword in name.lower() for keyword in ['dmic', 'sof-hda-dsp', 'microphone']):
                    logger.info(f"找到合适的输入设备: {name} (ID: {device_id})")
                    suitable_input = True
                    break
            
            for device_id, name in output_devices:
                if any(keyword in name.lower() for keyword in ['analog', 'sof-hda-dsp', 'speaker']) and 'hdmi' not in name.lower():
                    logger.info(f"找到合适的输出设备: {name} (ID: {device_id})")
                    suitable_output = True
                    break
            
            if suitable_input and suitable_output:
                logger.info("音频设备测试通过")
                return True
            elif suitable_input or suitable_output:
                logger.warning("部分音频设备可用，将使用默认设备补充")
                return True
            else:
                logger.warning("未找到理想音频设备，将使用默认设备")
                return True
                
        except ImportError:
            logger.error("sounddevice模块未安装，请安装: pip install sounddevice")
            return False
        except Exception as e:
            logger.error(f"音频设备测试失败: {e}")
            return False
    
    async def test_tcp_audio_connections(self):
        """测试TCP音频连接"""
        logger.info("测试TCP音频连接...")
        
        try:
            # 测试麦克风端口
            logger.info(f"测试麦克风端口 {self.mic_port}...")
            mic_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            mic_socket.settimeout(5)
            
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, mic_socket.connect, (self.jetson_host, self.mic_port)
                )
                logger.info("麦克风端口连接成功")
                mic_socket.close()
                mic_connected = True
            except Exception as e:
                logger.warning(f"麦克风端口连接失败: {e}")
                mic_connected = False
            
            # 测试扬声器端口
            logger.info(f"测试扬声器端口 {self.speaker_port}...")
            speaker_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            speaker_socket.settimeout(5)
            
            try:
                await asyncio.get_event_loop().run_in_executor(
                    None, speaker_socket.connect, (self.jetson_host, self.speaker_port)
                )
                logger.info("扬声器端口连接成功")
                speaker_socket.close()
                speaker_connected = True
            except Exception as e:
                logger.warning(f"扬声器端口连接失败: {e}")
                speaker_connected = False
            
            if mic_connected and speaker_connected:
                logger.info("TCP音频连接测试通过")
                return True
            elif mic_connected or speaker_connected:
                logger.warning("部分TCP音频连接可用")
                return True
            else:
                logger.error("TCP音频连接测试失败")
                return False
                
        except Exception as e:
            logger.error(f"TCP音频连接测试失败: {e}")
            return False
    
    def check_dependencies(self):
        """检查依赖项"""
        logger.info("检查依赖项...")
        
        required_modules = [
            'sounddevice',
            'numpy',
            'asyncio'
        ]
        
        missing_modules = []
        
        for module in required_modules:
            try:
                __import__(module)
                logger.info(f"  ✓ {module}")
            except ImportError:
                logger.error(f"  ✗ {module}")
                missing_modules.append(module)
        
        if missing_modules:
            logger.error(f"缺少依赖项: {missing_modules}")
            logger.info("请安装缺少的模块:")
            logger.info(f"pip install {' '.join(missing_modules)}")
            return False
        
        logger.info("依赖项检查通过")
        return True
    
    def print_system_info(self):
        """打印系统信息"""
        logger.info("系统信息:")
        logger.info(f"  Python版本: {sys.version}")
        logger.info(f"  当前工作目录: {os.getcwd()}")
        logger.info(f"  脚本路径: {os.path.abspath(__file__)}")
        logger.info(f"  Jetson地址: {self.jetson_host}")
        logger.info(f"  麦克风端口: {self.mic_port}")
        logger.info(f"  扬声器端口: {self.speaker_port}")
    
    async def run_full_test(self):
        """运行完整测试"""
        logger.info("=" * 60)
        logger.info("TCP音频系统测试开始")
        logger.info("=" * 60)
        
        # 打印系统信息
        self.print_system_info()
        print()
        
        # 检查依赖项
        if not self.check_dependencies():
            logger.error("依赖项检查失败，退出测试")
            return False
        print()
        
        # 测试网络连通性
        if not await self.test_network_connectivity():
            logger.error("网络连通性测试失败，退出测试")
            return False
        print()
        
        # 测试音频设备
        if not self.test_audio_devices():
            logger.error("音频设备测试失败，退出测试")
            return False
        print()
        
        # 测试TCP音频连接
        if not await self.test_tcp_audio_connections():
            logger.warning("TCP音频连接测试失败")
            logger.info("这是正常的，因为Jetson音频服务器可能还未启动")
            logger.info(f"请确保在Jetson上运行: python sensors/audio_server_tcp.py")
        print()
        
        logger.info("=" * 60)
        logger.info("测试完成")
        logger.info("=" * 60)
        
        return True
    
    def print_usage_guide(self):
        """打印使用指南"""
        print("\n" + "=" * 60)
        print("TCP音频系统使用指南")
        print("=" * 60)
        print()
        print("1. 在Jetson容器内启动音频服务器:")
        print(f"   python sensors/audio_server_tcp.py --mic-port {self.mic_port} --speaker-port {self.speaker_port}")
        print()
        print("2. 在笔记本上启动音频客户端:")
        print(f"   python sensors/audio_client_tcp.py --host {self.jetson_host} --mic-port {self.mic_port} --speaker-port {self.speaker_port}")
        print()
        print("3. 系统特性:")
        print("   - 使用TCP原始音频流（比WebSocket更高效）")
        print("   - 16kHz单声道格式（Live API标准）")
        print("   - 自动音频设备检测")
        print("   - 实时延迟监控")
        print("   - 音频质量验证")
        print()
        print("4. 排查问题:")
        print("   - 确保Jetson和笔记本在同一网段")
        print("   - 检查防火墙设置")
        print("   - 验证音频设备权限")
        print("   - 查看日志输出")
        print()
        print("=" * 60)


async def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="TCP音频系统测试")
    parser.add_argument("--host", default="192.168.3.1", help="Jetson主机地址")
    parser.add_argument("--mic-port", type=int, default=8888, help="麦克风端口")
    parser.add_argument("--speaker-port", type=int, default=8889, help="扬声器端口")
    
    args = parser.parse_args()
    
    # 创建测试实例
    test = TCPAudioTest(args.host, args.mic_port, args.speaker_port)
    
    # 运行测试
    await test.run_full_test()
    
    # 打印使用指南
    test.print_usage_guide()


if __name__ == "__main__":
    asyncio.run(main())