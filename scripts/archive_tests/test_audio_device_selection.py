#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频设备选择测试
强制测试sof-hda-dsp设备而非HDMI设备
"""

import sys
import os
import sounddevice as sd
import numpy as np
import asyncio
import logging

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class ForceDeviceAudioPlayer:
    """强制使用特定设备的音频播放器"""
    
    def __init__(self, force_device_pattern="sof-hda-dsp"):
        self.logger = logging.getLogger(__name__)
        self.force_device_pattern = force_device_pattern
        self._configure_audio_devices()
    
    def _configure_audio_devices(self):
        """配置音频设备，强制使用指定设备"""
        try:
            devices = sd.query_devices()
            
            # 寻找匹配的设备
            target_device = None
            
            for device_id, device in enumerate(devices):
                if (device['max_output_channels'] > 0 and 
                    self.force_device_pattern in device['name']):
                    
                    # 测试48000Hz采样率
                    try:
                        sd.check_output_settings(device=device_id, samplerate=48000)
                        target_device = device_id
                        self.logger.info(f"强制选择设备: [{device_id}] {device['name']} @ 48000Hz")
                        break
                    except Exception as e:
                        self.logger.warning(f"设备 [{device_id}] 不支持48000Hz: {e}")
                        continue
            
            if target_device is None:
                self.logger.error(f"未找到匹配 '{self.force_device_pattern}' 的设备")
                # 回退到默认设备
                target_device = sd.default.device[1]
                self.output_sample_rate = 44100
            else:
                self.output_sample_rate = 48000
            
            self.output_device = target_device
            
        except Exception as e:
            self.logger.error(f"配置音频设备失败: {e}")
            self.output_device = sd.default.device[1]
            self.output_sample_rate = 44100
    
    def play_pcm_file_sync(self, pcm_file: str) -> bool:
        """播放PCM音频文件"""
        try:
            # 读取PCM文件
            with open(pcm_file, 'rb') as f:
                audio_data = f.read()
            
            if not audio_data:
                self.logger.error("音频文件为空")
                return False
            
            # 转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            if len(audio_array) == 0:
                self.logger.error("音频数据为空")
                return False
            
            # 转换为float32格式
            audio_float = audio_array.astype(np.float32) / 32768.0
            
            # 重采样到目标采样率
            if self.output_sample_rate != 16000:
                audio_float = self._resample_audio(audio_float, 16000, self.output_sample_rate)
            
            # 播放音频
            self.logger.info(f"播放音频到设备 [{self.output_device}] @ {self.output_sample_rate}Hz")
            sd.play(audio_float, samplerate=self.output_sample_rate, device=self.output_device, blocking=True)
            
            self.logger.info(f"播放完成: {len(audio_data)} 字节")
            return True
            
        except Exception as e:
            self.logger.error(f"播放音频失败: {e}")
            return False
    
    def _resample_audio(self, audio_data: np.ndarray, original_rate: int, target_rate: int) -> np.ndarray:
        """重采样音频数据"""
        try:
            original_length = len(audio_data)
            target_length = int(original_length * target_rate / original_rate)
            
            original_indices = np.linspace(0, original_length - 1, original_length)
            target_indices = np.linspace(0, original_length - 1, target_length)
            
            resampled_audio = np.interp(target_indices, original_indices, audio_data)
            
            self.logger.info(f"重采样: {original_rate}Hz -> {target_rate}Hz")
            return resampled_audio
            
        except Exception as e:
            self.logger.error(f"重采样失败: {e}")
            return audio_data


async def test_sof_hda_dsp_device():
    """测试sof-hda-dsp设备"""
    print("=== 测试sof-hda-dsp设备 ===\n")
    
    # 先导入并测试TTS
    from intelligence.speech_local import LocalSpeechSystem
    from utils.config import load_config
    
    config = load_config("config.ini")
    tts_system = LocalSpeechSystem(config.speech)
    
    # 生成测试音频
    test_text = "测试sof-hda-dsp设备音频输出"
    print(f"🎵 合成测试音频: {test_text}")
    
    result = await tts_system.say(test_text, play_locally=False)  # 不播放，只合成
    
    if not result["success"]:
        print(f"❌ TTS合成失败: {result['message']}")
        return
    
    # 查找生成的音频文件
    audio_file = None
    for file in os.listdir("intelligence"):
        if file.endswith(".pcm"):
            audio_file = os.path.join("intelligence", file)
            break
    
    if not audio_file:
        print("❌ 未找到生成的音频文件")
        return
    
    print(f"✅ 音频文件生成: {audio_file}")
    
    # 使用强制sof-hda-dsp设备播放
    print("\n🔊 使用sof-hda-dsp设备播放...")
    player = ForceDeviceAudioPlayer(force_device_pattern="sof-hda-dsp")
    success = player.play_pcm_file_sync(audio_file)
    
    if success:
        print("✅ sof-hda-dsp设备播放成功")
        print("👂 请确认是否听到音频输出")
    else:
        print("❌ sof-hda-dsp设备播放失败")
    
    # 清理
    os.remove(audio_file)


async def test_all_devices():
    """测试所有可用设备"""
    print("\n=== 测试所有音频设备 ===\n")
    
    # 生成测试音频
    duration = 1.0
    sample_rate = 16000
    frequency = 440
    
    t = np.linspace(0, duration, int(sample_rate * duration))
    test_audio = 0.3 * np.sin(2 * np.pi * frequency * t)
    
    # 转换为16位PCM
    audio_int16 = (test_audio * 32767).astype(np.int16)
    test_file = "/tmp/test_tone.pcm"
    
    with open(test_file, 'wb') as f:
        f.write(audio_int16.tobytes())
    
    devices = sd.query_devices()
    
    # 测试每个设备
    for device_id, device in enumerate(devices):
        if device['max_output_channels'] > 0:
            print(f"\n🔊 测试设备 [{device_id}]: {device['name']}")
            
            # 寻找支持的采样率
            supported_rate = None
            for rate in [48000, 44100, 16000]:
                try:
                    sd.check_output_settings(device=device_id, samplerate=rate)
                    supported_rate = rate
                    break
                except:
                    continue
            
            if supported_rate is None:
                print("   ❌ 无支持的采样率")
                continue
            
            print(f"   📊 使用采样率: {supported_rate}Hz")
            
            # 使用强制设备播放器
            player = ForceDeviceAudioPlayer(force_device_pattern=device['name'])
            success = player.play_pcm_file_sync(test_file)
            
            if success:
                print(f"   ✅ 播放成功")
                print(f"   👂 是否听到音频？")
            else:
                print(f"   ❌ 播放失败")
    
    # 清理
    os.remove(test_file)


async def main():
    """主函数"""
    print("🔧 音频设备选择测试")
    print("=" * 50)
    
    try:
        # 1. 测试sof-hda-dsp设备
        await test_sof_hda_dsp_device()
        
        # 2. 测试所有设备
        await test_all_devices()
        
        print("\n🎯 测试完成！")
        print("根据测试结果，选择能够正确播放音频的设备")
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")
        print(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())