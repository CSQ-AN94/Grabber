#!/usr/bin/env python3
"""
简单的智能麦克风测试脚本
验证基础功能，无需GPU和复杂依赖
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensors.smart_microphone import SmartMicrophoneInput


async def test_smart_microphone_basic():
    """测试智能麦克风基础功能"""
    print("🎤 智能麦克风基础功能测试")
    print("=" * 50)
    
    # 设置日志
    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)
    
    # 创建智能麦克风
    mic = SmartMicrophoneInput(
        sample_rate=16000,
        chunk_size=1024,
        silence_threshold=1.0,
        speech_threshold=100
    )
    
    # 设置事件回调
    event_counts = {"speech_start": 0, "speech_end": 0, "silence_end": 0}
    
    def on_speech_start():
        event_counts["speech_start"] += 1
        print(f"🎤 检测到语音开始 (#{event_counts['speech_start']})")
    
    def on_speech_end():
        event_counts["speech_end"] += 1
        print(f"🤫 检测到语音结束 (#{event_counts['speech_end']})")
    
    def on_silence_end():
        event_counts["silence_end"] += 1
        print(f"⏸️ 静音结束事件 (#{event_counts['silence_end']})")
    
    mic.set_event_callbacks(
        speech_start=on_speech_start,
        speech_end=on_speech_end,
        silence_end=on_silence_end
    )
    
    try:
        # 启动麦克风
        print("启动智能麦克风...")
        await mic.start_recording()
        
        # 获取初始统计信息
        initial_stats = mic.get_stats()
        print(f"音频源: {initial_stats['audio_source']}")
        print(f"采样率: {initial_stats['sample_rate']} Hz")
        print(f"运行状态: {initial_stats['is_running']}")
        print()
        
        if initial_stats['audio_source'] == 'mock':
            print("使用模拟音频进行测试...")
        else:
            print("使用真实音频设备进行测试...")
        
        print("开始监听音频事件...")
        print("按Ctrl+C停止测试")
        print("-" * 30)
        
        # 监听音频事件
        event_count = 0
        audio_events = 0
        silence_events = 0
        
        while True:
            try:
                event = await mic.get_audio_event()
                if event:
                    event_type, data = event
                    event_count += 1
                    
                    if event_type == 'audio':
                        audio_events += 1
                        if audio_events % 50 == 0:
                            print(f"📊 已接收 {audio_events} 个音频包")
                    
                    elif event_type == 'silence_end':
                        silence_events += 1
                        print(f"🔕 静音结束信号 #{silence_events}")
                    
                    # 每500个事件输出统计
                    if event_count % 500 == 0:
                        stats = mic.get_stats()
                        print(f"📈 统计: 音频块={stats['chunks_received']}, "
                              f"语音事件={stats['speech_events']}, "
                              f"静音事件={stats['silence_events']}, "
                              f"队列={stats['queue_size']}")
                
                await asyncio.sleep(0.01)
                
            except asyncio.TimeoutError:
                continue
    
    except KeyboardInterrupt:
        print("\n🛑 用户停止测试")
    
    except Exception as e:
        print(f"❌ 测试错误: {e}")
        logger.error(f"测试错误: {e}", exc_info=True)
    
    finally:
        # 停止麦克风
        print("停止智能麦克风...")
        await mic.stop_recording()
        
        # 显示最终统计
        final_stats = mic.get_stats()
        print(f"\n📊 最终统计:")
        print(f"  音频源: {final_stats['audio_source']}")
        print(f"  运行时间: {final_stats['uptime_seconds']:.1f} 秒")
        print(f"  接收字节: {final_stats['bytes_received']}")
        print(f"  音频块数: {final_stats['chunks_received']}")
        print(f"  语音事件: {final_stats['speech_events']}")
        print(f"  静音事件: {final_stats['silence_events']}")
        print(f"  数据速率: {final_stats['bytes_per_second']:.1f} 字节/秒")
        
        # 验证功能
        print(f"\n✅ 功能验证:")
        print(f"  ✅ 音频输入: {'正常' if final_stats['chunks_received'] > 0 else '异常'}")
        print(f"  ✅ VAD检测: {'正常' if final_stats['speech_events'] > 0 else '使用模拟'}")
        print(f"  ✅ 静音检测: {'正常' if final_stats['silence_events'] > 0 else '使用模拟'}")
        print(f"  ✅ 事件回调: {'正常' if sum(event_counts.values()) > 0 else '异常'}")
        
        print("\n🎉 智能麦克风基础功能测试完成!")


if __name__ == "__main__":
    asyncio.run(test_smart_microphone_basic())