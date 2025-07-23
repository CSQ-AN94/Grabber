#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
VAD真实音频测试脚本
测试SmartMicrophoneInput在真实Docker容器环境下的工作状况
包括：VAD检测准确性、音频质量、事件触发等
"""

import sys
import os
import time
import asyncio
import threading
import wave
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensors.smart_microphone import SmartMicrophoneInput


class VADTester:
    """VAD测试器 - 真实环境测试"""
    
    def __init__(self):
        self.microphone = SmartMicrophoneInput(
            sample_rate=16000,
            chunk_size=1024,
            silence_threshold=1.0,  # 1秒静音阈值
            speech_threshold=100    # 语音检测阈值
        )
        
        # 测试统计
        self.test_start_time = None
        self.speech_events = 0
        self.silence_events = 0
        self.audio_chunks_received = 0
        self.total_audio_bytes = 0
        
        # 音频录制
        self.recording_audio = []
        self.is_recording = False
        self.output_dir = Path("./audio_test_output")
        self.output_dir.mkdir(exist_ok=True)
        
        # 测试状态
        self.test_running = False
        
    def setup_callbacks(self):
        """设置事件回调"""
        def on_speech_start():
            self.speech_events += 1
            current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"🎤 [{current_time}] 语音开始事件 #{self.speech_events}")
            
            # 开始录制这段语音
            self.recording_audio.clear()
            self.is_recording = True
            
        def on_silence_end():
            self.silence_events += 1
            current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"🤫 [{current_time}] 静音结束事件 #{self.silence_events}")
            
            # 停止录制并保存
            if self.is_recording and self.recording_audio:
                self._save_audio_segment()
            self.is_recording = False
            
        self.microphone.set_event_callbacks(
            speech_start=on_speech_start,
            silence_end=on_silence_end
        )
    
    def _save_audio_segment(self):
        """保存录制的音频片段"""
        if not self.recording_audio:
            return
            
        timestamp = datetime.now().strftime("%H%M%S_%f")[:-3]
        filename = self.output_dir / f"speech_segment_{timestamp}.wav"
        
        try:
            # 合并音频数据
            audio_data = b''.join(self.recording_audio)
            
            # 保存为WAV文件
            with wave.open(str(filename), 'wb') as wav_file:
                wav_file.setnchannels(1)  # 单声道
                wav_file.setsampwidth(2)  # 16位
                wav_file.setframerate(16000)  # 16kHz
                wav_file.writeframes(audio_data)
            
            duration = len(audio_data) / (16000 * 2)  # 持续时间（秒）
            size_kb = len(audio_data) / 1024
            
            print(f"💾 音频片段已保存: {filename.name}")
            print(f"   时长: {duration:.2f}秒, 大小: {size_kb:.1f}KB")
            
        except Exception as e:
            print(f"❌ 保存音频失败: {e}")
    
    async def process_audio_events(self):
        """处理音频事件"""
        print("\n=== 开始监听音频事件 ===")
        print("请开始说话测试VAD功能...")
        print("提示：")
        print("- 说话时应该看到 🎤 语音开始事件")
        print("- 停止说话1秒后应该看到 🤫 静音结束事件")
        print("- 音频片段会自动保存到 audio_test_output/ 目录")
        print("- 按 Ctrl+C 停止测试")
        print()
        
        while self.test_running:
            try:
                event = await self.microphone.get_audio_event()
                if event:
                    event_type, data = event
                    
                    if event_type == 'audio' and data:
                        self.audio_chunks_received += 1
                        self.total_audio_bytes += len(data)
                        
                        # 如果正在录制，添加到缓冲区
                        if self.is_recording:
                            self.recording_audio.append(data)
                        
                        # 每100个音频块显示一次统计
                        if self.audio_chunks_received % 100 == 0:
                            current_time = datetime.now().strftime("%H:%M:%S")
                            rate_kbps = self.total_audio_bytes / 1024 / (time.time() - self.test_start_time)
                            print(f"📊 [{current_time}] 已接收 {self.audio_chunks_received} 个音频块, "
                                  f"总计 {self.total_audio_bytes/1024:.1f}KB, "
                                  f"速率 {rate_kbps:.1f}KB/s")
                    
            except Exception as e:
                print(f"❌ 音频事件处理错误: {e}")
                break
    
    def print_real_time_stats(self):
        """实时统计显示"""
        def stats_thread():
            while self.test_running:
                try:
                    time.sleep(5)  # 每5秒显示一次
                    if not self.test_running:
                        break
                        
                    # 获取麦克风统计
                    stats = self.microphone.get_stats()
                    uptime = time.time() - self.test_start_time
                    
                    print(f"\n📈 实时统计 (运行时间: {uptime:.1f}秒)")
                    print(f"   音频源: {stats['audio_source']}")
                    print(f"   采样率: {stats['sample_rate']}Hz (硬件: {stats['hardware_sample_rate']}Hz)")
                    print(f"   重采样比例: {stats['resample_ratio']:.3f}")
                    print(f"   语音事件: {self.speech_events}")
                    print(f"   静音事件: {self.silence_events}")
                    print(f"   音频块: {self.audio_chunks_received}")
                    print(f"   数据传输: {stats['bytes_per_second']/1024:.1f}KB/s")
                    print(f"   队列大小: {stats['queue_size']}")
                    
                except Exception as e:
                    print(f"⚠️ 统计显示错误: {e}")
                    
        stats_thread_obj = threading.Thread(target=stats_thread)
        stats_thread_obj.daemon = True
        stats_thread_obj.start()
        return stats_thread_obj
    
    async def run_test(self):
        """运行VAD测试"""
        print("=== VAD真实音频测试 ===")
        print("测试目标:")
        print("1. 验证Docker容器内麦克风访问")
        print("2. 测试VAD语音活动检测准确性")
        print("3. 验证音频质量和采样率")
        print("4. 测试事件回调机制")
        print("5. 保存真实音频样本")
        print()
        
        # 检查音频源
        if self.microphone.audio_source is None:
            print("❌ 无可用音频源！请检查Docker容器音频设备配置")
            print("提示: 确保Docker启动时包含音频设备映射")
            return False
        
        print(f"✅ 检测到音频源: {self.microphone.audio_source}")
        
        try:
            # 设置回调
            self.setup_callbacks()
            
            # 开始录音
            await self.microphone.start_recording()
            print("✅ 麦克风录音已启动")
            
            # 测试开始
            self.test_running = True
            self.test_start_time = time.time()
            
            # 启动统计显示线程
            stats_thread = self.print_real_time_stats()
            
            # 开始处理音频事件
            await self.process_audio_events()
            
        except KeyboardInterrupt:
            print("\n\n⏹️ 用户停止测试")
        except Exception as e:
            print(f"\n❌ 测试过程出错: {e}")
        finally:
            # 清理
            self.test_running = False
            await self.microphone.stop_recording()
            
            # 显示最终统计
            self._print_final_summary()
    
    def _print_final_summary(self):
        """显示最终测试总结"""
        total_time = time.time() - self.test_start_time if self.test_start_time else 0
        
        print("\n" + "="*50)
        print("📋 VAD测试总结")
        print("="*50)
        print(f"测试时长: {total_time:.1f}秒")
        print(f"语音事件: {self.speech_events}")
        print(f"静音事件: {self.silence_events}")
        print(f"音频块数: {self.audio_chunks_received}")
        print(f"音频总量: {self.total_audio_bytes/1024:.1f}KB")
        print(f"平均速率: {self.total_audio_bytes/1024/total_time:.1f}KB/s" if total_time > 0 else "N/A")
        
        # 检查保存的音频文件
        audio_files = list(self.output_dir.glob("speech_segment_*.wav"))
        print(f"保存音频: {len(audio_files)}个片段")
        
        if audio_files:
            print("\n保存的音频片段:")
            for audio_file in sorted(audio_files):
                size_kb = audio_file.stat().st_size / 1024
                print(f"  - {audio_file.name} ({size_kb:.1f}KB)")
        
        print(f"\n音频文件保存在: {self.output_dir.absolute()}")
        
        # 健康状况评估
        print("\n🏥 系统健康状况:")
        if self.speech_events > 0:
            print("✅ VAD语音检测: 正常")
        else:
            print("⚠️ VAD语音检测: 未检测到语音事件")
            
        if self.silence_events > 0:
            print("✅ VAD静音检测: 正常") 
        else:
            print("⚠️ VAD静音检测: 未检测到静音事件")
            
        if self.audio_chunks_received > 100:
            print("✅ 音频流传输: 正常")
        else:
            print("⚠️ 音频流传输: 数据量偏低")
        
        print("\n建议: 如果检测到问题，请检查Docker音频配置和麦克风权限")


async def main():
    """主函数"""
    print("开始VAD真实音频测试...")
    print("请确保在Docker容器内运行此脚本")
    print()
    
    tester = VADTester()
    success = await tester.run_test()
    
    if success is False:
        print("\n❌ 测试失败，请检查系统配置")
        return 1
    
    print("\n✅ VAD测试完成")
    return 0


if __name__ == "__main__":
    # 运行测试
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except Exception as e:
        print(f"\n💥 测试脚本异常: {e}")
        sys.exit(1)