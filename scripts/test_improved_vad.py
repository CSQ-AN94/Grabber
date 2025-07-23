#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
改进VAD测试脚本
测试新的语音片段合并和完整语句检测功能
"""

import sys
import os
import time
import asyncio
import wave
from datetime import datetime
from pathlib import Path

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensors.improved_vad import ImprovedVAD


class ImprovedVADTester:
    """改进VAD测试器"""
    
    def __init__(self):
        self.vad = ImprovedVAD(
            sample_rate=16000,
            chunk_size=1024,
            speech_timeout=2.0,  # 2秒静音后结束语音
            min_speech_duration=0.3,  # 最小0.3秒语音
            speech_threshold=100
        )
        
        # 测试统计
        self.test_start_time = None
        self.utterances_received = []
        self.output_dir = Path("./improved_vad_output")
        self.output_dir.mkdir(exist_ok=True)
        
        # 设置回调
        self.setup_callbacks()
    
    def setup_callbacks(self):
        """设置VAD事件回调"""
        def on_speech_start():
            current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            print(f"🎤 [{current_time}] 检测到语音开始")
        
        def on_complete_utterance(audio_data: bytes, duration: float):
            current_time = datetime.now().strftime("%H:%M:%S.%f")[:-3]
            utterance_id = len(self.utterances_received) + 1
            
            print(f"📝 [{current_time}] 完整语句 #{utterance_id}:")
            print(f"   时长: {duration:.2f}秒")
            print(f"   大小: {len(audio_data)/1024:.1f}KB")
            
            # 保存音频文件
            filename = self.output_dir / f"utterance_{utterance_id:03d}_{int(duration*100):03d}ms.wav"
            self.save_utterance(audio_data, filename)
            
            # 记录语句信息
            self.utterances_received.append({
                'id': utterance_id,
                'timestamp': current_time,
                'duration': duration,
                'size_bytes': len(audio_data),
                'filename': filename.name
            })
            
            print(f"   保存为: {filename.name}")
            print()
        
        self.vad.set_callbacks(
            speech_start=on_speech_start,
            complete_utterance=on_complete_utterance
        )
    
    def save_utterance(self, audio_data: bytes, filename: Path):
        """保存完整语句音频"""
        try:
            with wave.open(str(filename), 'wb') as wav_file:
                wav_file.setnchannels(1)  # 单声道
                wav_file.setsampwidth(2)  # 16位
                wav_file.setframerate(16000)  # 16kHz
                wav_file.writeframes(audio_data)
        except Exception as e:
            print(f"❌ 保存音频失败: {e}")
    
    async def run_test(self):
        """运行改进VAD测试"""
        print("=== 改进VAD测试 ===")
        print("测试目标:")
        print("1. 验证语音片段合并功能")
        print("2. 测试完整语句检测准确性")
        print("3. 验证音频质量和连续性")
        print("4. 对比传统VAD的改进效果")
        print()
        
        # 检查音频源
        if self.vad.audio_source is None:
            print("❌ 无可用音频源！")
            return False
        
        print(f"✅ 音频源: {self.vad.audio_source}")
        print()
        
        try:
            # 开始录音
            await self.vad.start_recording()
            print("✅ 改进VAD录音已启动")
            
            self.test_start_time = time.time()
            
            print("\n=== 开始语音测试 ===")
            print("请进行以下测试:")
            print("1. 说一句短话 (1-2秒)")
            print("2. 说一句长话 (3-5秒)")
            print("3. 说话中间停顿一下")
            print("4. 连续说几句话，中间有短暂停顿")
            print("5. 正常对话语速说话")
            print()
            print("按 Ctrl+C 停止测试")
            print()
            
            # 等待用户交互
            while True:
                await asyncio.sleep(1)
                
                # 显示实时统计
                if int(time.time()) % 10 == 0:  # 每10秒显示一次
                    self.print_real_time_stats()
                
        except KeyboardInterrupt:
            print("\n\n⏹️ 用户停止测试")
        except Exception as e:
            print(f"\n❌ 测试过程出错: {e}")
        finally:
            await self.vad.stop_recording()
            self.print_final_summary()
    
    def print_real_time_stats(self):
        """显示实时统计"""
        stats = self.vad.get_stats()
        uptime = time.time() - self.test_start_time
        
        print(f"\n📊 实时统计 (运行时间: {uptime:.1f}秒)")
        print(f"   完整语句: {stats['utterance_count']}")
        print(f"   总语音时长: {stats['total_speech_duration']:.1f}秒")
        print(f"   平均语句长度: {stats['average_utterance_length']:.2f}秒")
        print(f"   当前状态: {'🎤 语音中' if stats['is_in_speech'] else '🤫 静音中'}")
        print(f"   缓冲区大小: {stats['speech_buffer_size']} 块")
    
    def print_final_summary(self):
        """显示最终测试总结"""
        total_time = time.time() - self.test_start_time if self.test_start_time else 0
        stats = self.vad.get_stats()
        
        print("\n" + "="*60)
        print("📋 改进VAD测试总结")
        print("="*60)
        print(f"测试时长: {total_time:.1f}秒")
        print(f"完整语句数: {stats['utterance_count']}")
        print(f"总语音时长: {stats['total_speech_duration']:.1f}秒")
        print(f"平均语句长度: {stats['average_utterance_length']:.2f}秒")
        
        if self.utterances_received:
            print(f"\n📝 语句详情:")
            for utterance in self.utterances_received:
                print(f"  {utterance['id']:2d}. [{utterance['timestamp']}] "
                      f"{utterance['duration']:.2f}s, "
                      f"{utterance['size_bytes']/1024:.1f}KB - "
                      f"{utterance['filename']}")
        
        print(f"\n📁 音频文件保存在: {self.output_dir.absolute()}")
        
        # 与传统VAD对比分析
        print(f"\n🔍 改进效果分析:")
        if stats['utterance_count'] > 0:
            avg_length = stats['average_utterance_length']
            if avg_length > 1.0:
                print("✅ 语音片段合并效果良好 (平均长度 > 1秒)")
            elif avg_length > 0.5:
                print("⚠️ 语音片段合并部分有效 (平均长度 > 0.5秒)")
            else:
                print("❌ 语音片段仍然过短，需要调整参数")
                
            if stats['utterance_count'] < stats['total_speech_duration'] * 2:
                print("✅ 语音分割明显减少 (语句数量合理)")
            else:
                print("⚠️ 语音分割仍然较多，建议增加speech_timeout")
        
        # 参数调优建议
        print(f"\n💡 参数调优建议:")
        if stats['average_utterance_length'] < 1.0:
            print("- 建议增加 speech_timeout (当前: 2.0s)")
        if stats['utterance_count'] > total_time / 5:  # 平均每5秒超过1个语句
            print("- 建议降低 VAD 敏感度")
        if stats['utterance_count'] == 0:
            print("- 建议降低 speech_threshold 或检查麦克风")
    
    async def run_comparison_test(self):
        """运行对比测试（与原VAD对比）"""
        print("=== VAD改进效果对比测试 ===")
        print("将同时运行改进VAD和原始VAD，对比效果差异")
        print()
        
        # TODO: 实现与原始VAD的并行对比测试
        print("对比测试功能待实现...")


async def main():
    """主函数"""
    print("开始改进VAD测试...")
    print()
    
    tester = ImprovedVADTester()
    
    try:
        await tester.run_test()
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        return 1
    
    print("\n✅ 改进VAD测试完成")
    return 0


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️ 测试被用户中断")
        sys.exit(0)
    except Exception as e:
        print(f"\n💥 测试脚本异常: {e}")
        sys.exit(1)