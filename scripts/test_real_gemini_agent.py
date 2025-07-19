#!/usr/bin/env python3
"""
真实GeminiAgent测试脚本
严格遵循：只使用真实麦克风，在容器环境中测试
"""

import sys
import os
import asyncio
import logging
import time

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.real_gemini_agent import RealGeminiAgent, VoiceCommand
from interfaces.audio_input import RealAudioInput
from utils.config import load_config


async def test_real_gemini_agent():
    """测试真实GeminiAgent"""
    print("🎤 真实GeminiAgent测试")
    print("=" * 50)
    print("严格要求：只使用真实麦克风，禁止任何模拟数据")
    print("=" * 50)
    
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        # 加载配置
        config = load_config()
        
        # 创建音频输入接口
        print("🔧 初始化真实音频输入...")
        audio_config = {
            'sample_rate': 16000,
            'chunk_size': 1024,
            'silence_threshold': 1.0,
            'speech_threshold': 100
        }
        
        try:
            audio_input = RealAudioInput(audio_config)
            print(f"✅ 音频输入初始化成功")
            
            # 显示音频源信息
            stats = audio_input.get_stats()
            print(f"🎤 音频源: {stats['audio_source']}")
            
            if stats['audio_source'] is None:
                print("❌ 无可用音频源，测试无法继续")
                return
            
        except Exception as e:
            print(f"❌ 音频输入初始化失败: {e}")
            print("💡 请确保在容器中运行: docker compose run --rm grabber_dev python3 scripts/test_real_gemini_agent.py")
            return
        
        # 创建GeminiAgent
        print("🤖 初始化真实GeminiAgent...")
        gemini_config = {
            'api_key': config.llm.gemini_api_key,
            'model_name': config.llm.model_name,
            'temperature': 0.7,  # 默认值
            'max_output_tokens': 1024,  # 默认值
        }
        
        agent = RealGeminiAgent(gemini_config)
        
        # 设置音频输入
        agent.set_audio_input(audio_input)
        
        # 设置命令处理器
        def command_handler(command: VoiceCommand):
            print(f"\\n🎯 接收到语音命令:")
            print(f"   动作: {command.action}")
            print(f"   参数: {command.parameters}")
            print(f"   响应: {command.response_text}")
            print(f"   置信度: {command.confidence}")
            print(f"   时间戳: {command.timestamp}")
            print("-" * 30)
        
        agent.set_command_handler(command_handler)
        
        # 启动会话
        print("🚀 启动真实语音交互会话...")
        session_id = await agent.start_session()
        print(f"✅ 会话已启动: {session_id}")
        
        # 显示系统信息
        system_info = agent.get_system_info()
        print(f"🔍 系统信息:")
        for key, value in system_info.items():
            print(f"   {key}: {value}")
        
        print("\\n" + "=" * 50)
        print("🎙️ 请对着麦克风说话...")
        print("🛑 按Ctrl+C停止测试")
        print("=" * 50)
        
        # 定期显示统计信息
        last_stats_time = time.time()
        
        try:
            while True:
                # 每10秒显示一次统计信息
                if time.time() - last_stats_time >= 10:
                    stats = agent.get_session_stats()
                    print(f"\\n📊 会话统计:")
                    print(f"   运行时间: {stats['uptime_seconds']:.1f} 秒")
                    print(f"   音频源: {stats.get('audio_source', 'N/A')}")
                    print(f"   音频块: {stats.get('audio_chunks', 0)}")
                    print(f"   语音事件: {stats.get('speech_events', 0)}")
                    print(f"   静音事件: {stats.get('silence_events', 0)}")
                    print(f"   处理命令: {stats['commands_processed']}")
                    print("-" * 30)
                    last_stats_time = time.time()
                
                await asyncio.sleep(1)
                
        except KeyboardInterrupt:
            print("\\n🛑 用户停止测试")
        
        finally:
            # 停止会话
            print("🔚 停止真实语音交互会话...")
            await agent.stop_session()
            
            # 显示最终统计
            final_stats = agent.get_session_stats()
            print(f"\\n📊 最终统计:")
            print(f"   总运行时间: {final_stats['uptime_seconds']:.1f} 秒")
            print(f"   音频源: {final_stats.get('audio_source', 'N/A')}")
            print(f"   音频块: {final_stats.get('audio_chunks', 0)}")
            print(f"   语音事件: {final_stats.get('speech_events', 0)}")
            print(f"   静音事件: {final_stats.get('silence_events', 0)}")
            print(f"   处理命令: {final_stats['commands_processed']}")
            
            # 验证测试结果
            print(f"\\n🔍 测试结果验证:")
            if final_stats.get('audio_chunks', 0) > 0:
                print("   ✅ 真实音频输入: 正常")
            else:
                print("   ❌ 真实音频输入: 异常")
            
            if final_stats.get('speech_events', 0) > 0:
                print("   ✅ 语音检测: 正常")
            else:
                print("   ⚠️ 语音检测: 未检测到语音")
            
            if final_stats.get('audio_source') in ['sounddevice', 'pulseaudio']:
                print("   ✅ 音频源: 真实硬件")
            else:
                print("   ❌ 音频源: 非真实硬件")
        
        print("\\n🎉 真实GeminiAgent测试完成!")
        
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        logging.error(f"测试失败: {e}", exc_info=True)


if __name__ == "__main__":
    asyncio.run(test_real_gemini_agent())