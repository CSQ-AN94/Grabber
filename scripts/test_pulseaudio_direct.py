#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接使用PulseAudio播放音频测试
"""

import sys
import os
import subprocess
import asyncio
import logging

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class PulseAudioPlayer:
    """使用PulseAudio命令行播放音频"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
    
    def play_pcm_file_sync(self, pcm_file: str) -> bool:
        """使用paplay播放PCM文件"""
        try:
            # 转换PCM到WAV格式
            wav_file = pcm_file.replace('.pcm', '.wav')
            
            # 使用sox将PCM转换为WAV（如果可用）
            sox_cmd = [
                'sox', '-t', 'raw', '-r', '16000', '-e', 'signed-integer', '-b', '16', '-c', '1',
                pcm_file, wav_file
            ]
            
            try:
                subprocess.run(sox_cmd, check=True, capture_output=True)
                self.logger.info(f"PCM转WAV成功: {wav_file}")
            except subprocess.CalledProcessError as e:
                self.logger.error(f"PCM转WAV失败: {e}")
                return False
            except FileNotFoundError:
                self.logger.error("sox命令未找到")
                return False
            
            # 使用paplay播放WAV文件
            paplay_cmd = ['paplay', wav_file]
            
            try:
                result = subprocess.run(paplay_cmd, check=True, capture_output=True, text=True)
                self.logger.info(f"paplay播放成功")
                return True
            except subprocess.CalledProcessError as e:
                self.logger.error(f"paplay播放失败: {e}")
                return False
            except FileNotFoundError:
                self.logger.error("paplay命令未找到")
                return False
            
            finally:
                # 清理临时WAV文件
                if os.path.exists(wav_file):
                    os.remove(wav_file)
        
        except Exception as e:
            self.logger.error(f"播放音频失败: {e}")
            return False
    
    def play_with_aplay(self, pcm_file: str) -> bool:
        """使用aplay播放PCM文件"""
        try:
            # 使用aplay直接播放PCM文件
            aplay_cmd = [
                'aplay', '-t', 'raw', '-f', 'S16_LE', '-r', '16000', '-c', '1', pcm_file
            ]
            
            result = subprocess.run(aplay_cmd, check=True, capture_output=True, text=True)
            self.logger.info(f"aplay播放成功")
            return True
            
        except subprocess.CalledProcessError as e:
            self.logger.error(f"aplay播放失败: {e}")
            return False
        except FileNotFoundError:
            self.logger.error("aplay命令未找到")
            return False
        except Exception as e:
            self.logger.error(f"播放音频失败: {e}")
            return False


async def test_pulse_audio_playback():
    """测试PulseAudio播放"""
    print("=== 测试PulseAudio播放 ===\n")
    
    # 先生成测试音频
    from intelligence.speech_local import LocalSpeechSystem
    from utils.config import load_config
    
    config = load_config("config.ini")
    tts_system = LocalSpeechSystem(config.speech)
    
    # 生成测试音频
    test_text = "测试PulseAudio播放音频"
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
    
    # 使用PulseAudio播放
    player = PulseAudioPlayer()
    
    print("\n🔊 使用paplay播放...")
    success1 = player.play_pcm_file_sync(audio_file)
    
    if success1:
        print("✅ paplay播放成功")
    else:
        print("❌ paplay播放失败")
    
    print("\n🔊 使用aplay播放...")
    success2 = player.play_with_aplay(audio_file)
    
    if success2:
        print("✅ aplay播放成功")
    else:
        print("❌ aplay播放失败")
    
    # 清理
    os.remove(audio_file)
    
    return success1 or success2


async def main():
    """主函数"""
    print("🔧 PulseAudio直接播放测试")
    print("=" * 50)
    
    try:
        success = await test_pulse_audio_playback()
        
        if success:
            print("\n🎯 找到了可用的音频播放方法！")
            print("可以使用命令行工具播放音频")
        else:
            print("\n❌ 所有播放方法都失败了")
        
    except Exception as e:
        logger.error(f"测试过程中发生错误: {e}")
        print(f"❌ 测试失败: {e}")


if __name__ == "__main__":
    asyncio.run(main())