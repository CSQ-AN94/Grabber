#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频系统诊断工具
检查Docker环境中的音频设备状态、能量级别和VAD阈值
"""

import sys
import os
import asyncio
import logging
import time
import numpy as np
from typing import Optional

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False
    sd = None

from utils.config import setup_logging


class AudioDiagnosticTool:
    """音频系统诊断工具"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.sample_rate = 16000
        self.chunk_size = 1024
        self.is_recording = False
        self.audio_data_samples = []
        
    def diagnose_system_info(self):
        """诊断系统信息"""
        self.logger.info("=" * 60)
        self.logger.info("🔍 音频系统诊断开始")
        self.logger.info("=" * 60)
        
        # 检查sounddevice可用性
        if not HAS_SOUNDDEVICE:
            self.logger.error("❌ sounddevice 库未安装或无法导入")
            return False
        
        self.logger.info("✅ sounddevice 库可用")
        
        # 检查音频设备
        try:
            devices = sd.query_devices()
            self.logger.info(f"📱 发现 {len(devices)} 个音频设备:")
            
            input_devices = []
            for i, device in enumerate(devices):
                device_type = "🎤输入" if device['max_input_channels'] > 0 else "🔊输出"
                if device['max_input_channels'] > 0:
                    input_devices.append((i, device))
                
                self.logger.info(f"  [{i}] {device_type}: {device['name']}")
                self.logger.info(f"      最大输入通道: {device['max_input_channels']}")
                self.logger.info(f"      最大输出通道: {device['max_output_channels']}")
                self.logger.info(f"      默认采样率: {device['default_samplerate']}")
            
            if not input_devices:
                self.logger.error("❌ 没有找到可用的输入设备")
                return False
            
            self.logger.info(f"✅ 找到 {len(input_devices)} 个输入设备")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 查询音频设备失败: {e}")
            return False
    
    def test_device_compatibility(self):
        """测试设备兼容性"""
        self.logger.info("\n🧪 测试设备兼容性...")
        
        devices = sd.query_devices()
        sample_rates = [16000, 22050, 44100, 48000]
        compatible_devices = []
        
        for device_id, device in enumerate(devices):
            if device['max_input_channels'] > 0:
                self.logger.info(f"\n测试设备 [{device_id}]: {device['name']}")
                
                for rate in sample_rates:
                    try:
                        sd.check_input_settings(
                            device=device_id,
                            samplerate=rate,
                            channels=1
                        )
                        self.logger.info(f"  ✅ {rate}Hz - 支持")
                        compatible_devices.append((device_id, device, rate))
                        break  # 找到一个支持的采样率就够了
                    except Exception as e:
                        self.logger.debug(f"  ❌ {rate}Hz - 不支持: {e}")
                
                if not any(dev[0] == device_id for dev in compatible_devices):
                    self.logger.warning(f"  ⚠️ 设备 [{device_id}] 不支持任何测试的采样率")
        
        if compatible_devices:
            self.logger.info(f"\n✅ 找到 {len(compatible_devices)} 个兼容设备")
            return compatible_devices[0]  # 返回第一个兼容设备
        else:
            self.logger.error("\n❌ 没有找到兼容的设备")
            return None
    
    def _audio_callback(self, indata, frames, time, status):
        """音频回调函数 - 记录实际数据"""
        if status:
            self.logger.warning(f"音频状态警告: {status}")
        
        if self.is_recording:
            try:
                # 转换为16位PCM
                audio_data = (indata.flatten() * 32767).astype(np.int16)
                
                # 计算能量
                energy = np.mean(np.abs(audio_data))
                max_amplitude = np.max(np.abs(audio_data))
                
                # 保存样本用于分析
                self.audio_data_samples.append({
                    'energy': energy,
                    'max_amplitude': max_amplitude,
                    'timestamp': time.inputBufferAdcTime,
                    'data_length': len(audio_data),
                    'data_sample': audio_data[:10].tolist()  # 前10个采样点
                })
                
                # 实时日志（每50个块输出一次）
                if len(self.audio_data_samples) % 50 == 0:
                    self.logger.info(f"🎵 音频样本 #{len(self.audio_data_samples)}: "
                                   f"能量={energy:.1f}, 最大幅度={max_amplitude}, "
                                   f"数据长度={len(audio_data)}")
                
            except Exception as e:
                self.logger.error(f"音频回调错误: {e}")
    
    async def test_real_audio_capture(self, device_id, sample_rate, duration=10):
        """测试真实音频捕获"""
        self.logger.info(f"\n🎤 测试真实音频捕获...")
        self.logger.info(f"设备: [{device_id}], 采样率: {sample_rate}Hz, 时长: {duration}秒")
        self.logger.info("请对着麦克风说话...")
        
        self.audio_data_samples = []
        self.is_recording = True
        
        try:
            # 创建音频流
            with sd.InputStream(
                samplerate=sample_rate,
                channels=1,
                dtype=np.float32,
                blocksize=self.chunk_size,
                callback=self._audio_callback,
                device=device_id
            ) as stream:
                self.logger.info("✅ 音频流启动成功")
                
                # 录音指定时间
                for i in range(duration):
                    await asyncio.sleep(1)
                    self.logger.info(f"⏱️ 录音中... {i+1}/{duration}秒")
        
        except Exception as e:
            self.logger.error(f"❌ 音频捕获失败: {e}")
            return False
        
        finally:
            self.is_recording = False
        
        # 分析捕获的数据
        if self.audio_data_samples:
            self.analyze_captured_audio()
            return True
        else:
            self.logger.error("❌ 没有捕获到任何音频数据")
            return False
    
    def analyze_captured_audio(self):
        """分析捕获的音频数据"""
        if not self.audio_data_samples:
            return
        
        self.logger.info(f"\n📊 分析 {len(self.audio_data_samples)} 个音频样本...")
        
        energies = [sample['energy'] for sample in self.audio_data_samples]
        max_amplitudes = [sample['max_amplitude'] for sample in self.audio_data_samples]
        
        # 统计信息
        energy_stats = {
            'min': np.min(energies),
            'max': np.max(energies),
            'mean': np.mean(energies),
            'std': np.std(energies),
            'median': np.median(energies)
        }
        
        amplitude_stats = {
            'min': np.min(max_amplitudes),
            'max': np.max(max_amplitudes),
            'mean': np.mean(max_amplitudes),
            'std': np.std(max_amplitudes),
            'median': np.median(max_amplitudes)
        }
        
        self.logger.info("🔍 音频能量统计:")
        self.logger.info(f"  最小值: {energy_stats['min']:.2f}")
        self.logger.info(f"  最大值: {energy_stats['max']:.2f}")
        self.logger.info(f"  平均值: {energy_stats['mean']:.2f}")
        self.logger.info(f"  标准差: {energy_stats['std']:.2f}")
        self.logger.info(f"  中位数: {energy_stats['median']:.2f}")
        
        self.logger.info("\n🔍 最大幅度统计:")
        self.logger.info(f"  最小值: {amplitude_stats['min']:.2f}")
        self.logger.info(f"  最大值: {amplitude_stats['max']:.2f}")
        self.logger.info(f"  平均值: {amplitude_stats['mean']:.2f}")
        self.logger.info(f"  标准差: {amplitude_stats['std']:.2f}")
        self.logger.info(f"  中位数: {amplitude_stats['median']:.2f}")
        
        # VAD阈值分析
        current_threshold = 2000
        self.logger.info(f"\n🎯 VAD阈值分析 (当前阈值: {current_threshold}):")
        
        above_threshold = sum(1 for e in energies if e > current_threshold)
        percentage_above = (above_threshold / len(energies)) * 100
        
        self.logger.info(f"  高于当前阈值的样本: {above_threshold}/{len(energies)} ({percentage_above:.1f}%)")
        
        # 建议新阈值
        if energy_stats['max'] > 0:
            suggested_thresholds = [
                energy_stats['mean'] + energy_stats['std'],
                energy_stats['median'] * 2,
                energy_stats['max'] * 0.1,
                energy_stats['max'] * 0.05
            ]
            
            self.logger.info("\n💡 建议的VAD阈值:")
            for i, threshold in enumerate(suggested_thresholds):
                above_count = sum(1 for e in energies if e > threshold)
                percentage = (above_count / len(energies)) * 100
                self.logger.info(f"  方案{i+1}: {threshold:.1f} (触发率: {percentage:.1f}%)")
        
        # 显示一些原始数据样本
        self.logger.info("\n🔬 前5个音频样本的原始数据:")
        for i, sample in enumerate(self.audio_data_samples[:5]):
            self.logger.info(f"  样本{i+1}: 能量={sample['energy']:.2f}, "
                           f"数据={sample['data_sample']}")
    
    async def run_full_diagnosis(self):
        """运行完整诊断"""
        # 步骤1: 系统信息
        if not self.diagnose_system_info():
            return False
        
        # 步骤2: 设备兼容性
        compatible_device = self.test_device_compatibility()
        if not compatible_device:
            return False
        
        device_id, device, sample_rate = compatible_device
        
        # 步骤3: 真实音频测试
        success = await self.test_real_audio_capture(device_id, sample_rate)
        
        self.logger.info("\n" + "=" * 60)
        if success:
            self.logger.info("✅ 音频系统诊断完成")
        else:
            self.logger.info("❌ 音频系统诊断发现问题")
        self.logger.info("=" * 60)
        
        return success


async def main():
    """主函数"""
    print("🔍 音频系统诊断工具")
    print("用于诊断Docker环境中的VAD静音检测问题")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 创建诊断工具
    diagnostic_tool = AudioDiagnosticTool()
    
    try:
        # 运行完整诊断
        await diagnostic_tool.run_full_diagnosis()
        
    except KeyboardInterrupt:
        print("\n用户中断诊断")
    except Exception as e:
        print(f"诊断过程中出错: {e}")
        logging.error(f"诊断错误: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(main())