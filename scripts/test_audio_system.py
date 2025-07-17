#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
音频系统统一测试脚本
整合了语音合成、本地播放、麦克风录音和Docker环境的测试
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from intelligence.speech_local import LocalSpeechSystem
from sensors.local_microphone import LocalMicrophoneInput

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


async def test_speech_synthesis():
    """测试语音合成功能"""
    print("\n🎵 测试语音合成功能...")
    
    try:
        config = load_config("config.ini")
        speech_system = LocalSpeechSystem(config.speech)
        
        test_texts = [
            "音频系统测试正常",
            "语音合成功能正常",
            "本地播放功能正常"
        ]
        
        for i, text in enumerate(test_texts, 1):
            print(f"📢 测试 {i}/{len(test_texts)}: {text}")
            result = await speech_system.say(text)
            
            if result["success"]:
                print(f"✅ 成功")
            else:
                print(f"❌ 失败: {result['message']}")
            
            await asyncio.sleep(0.3)
        
        # 清理
        await speech_system.stop_speech_system()
        print("✅ 语音合成测试完成")
        return True
        
    except Exception as e:
        logger.error(f"语音合成测试失败: {e}")
        return False


async def test_microphone_input():
    """测试麦克风输入功能"""
    print("\n🎤 测试麦克风输入功能...")
    
    try:
        microphone = LocalMicrophoneInput()
        
        print("启动麦克风录音...")
        await microphone.start_recording()
        
        print("录音3秒...")
        chunks_received = 0
        start_time = asyncio.get_event_loop().time()
        
        while asyncio.get_event_loop().time() - start_time < 3:
            chunk = await microphone.get_audio_chunk()
            if chunk:
                chunks_received += 1
            await asyncio.sleep(0.01)
        
        await microphone.stop_recording()
        
        stats = microphone.get_stats()
        print(f"✅ 麦克风测试完成")
        print(f"   接收音频块: {stats['chunks_received']}")
        print(f"   接收字节数: {stats['bytes_received']}")
        return True
        
    except Exception as e:
        logger.error(f"麦克风测试失败: {e}")
        return False


async def test_docker_environment():
    """测试Docker环境配置"""
    print("\n🐳 测试Docker环境...")
    
    # 检查Docker环境
    is_docker = os.path.exists('/.dockerenv')
    print(f"   Docker环境: {'✅' if is_docker else '❌'}")
    
    # 检查PulseAudio socket
    pulse_socket = os.path.exists('/run/user/1000/pulse/native')
    print(f"   PulseAudio socket: {'✅' if pulse_socket else '❌'}")
    
    # 检查音频设备
    try:
        import sounddevice as sd
        devices = sd.query_devices()
        audio_devices = [d for d in devices if d['max_output_channels'] > 0]
        print(f"   音频输出设备: {len(audio_devices)} 个")
        
        if audio_devices:
            print("✅ Docker环境配置正常")
            return True
        else:
            print("❌ 未找到音频输出设备")
            return False
            
    except Exception as e:
        logger.error(f"Docker环境测试失败: {e}")
        return False


async def test_integration():
    """集成测试"""
    print("\n🔗 集成测试...")
    
    try:
        config = load_config("config.ini")
        
        # 检查Gemini Agent配置
        if config.llm.gemini_api_key != 'YOUR_GEMINI_API_KEY_HERE':
            from intelligence.gemini_agent import GeminiAgent
            from intelligence.robot_tools import MockRobotTools, ToolRegistry
            from utils.state import WorldState
            
            world_state = WorldState()
            world_state.initialize_world_map(mock_data=True)
            
            robot_tools = MockRobotTools(world_state, config)
            tool_registry = ToolRegistry(robot_tools)
            
            gemini_agent = GeminiAgent(config.llm, config.agent, tool_registry)
            
            print("✅ Gemini Agent集成正常")
        else:
            print("⚠️ Gemini API密钥未配置")
        
        # 测试主应用导入
        from main import GrabberSystem
        print("✅ 主应用导入成功")
        
        return True
        
    except Exception as e:
        logger.error(f"集成测试失败: {e}")
        return False


async def main():
    """主测试函数"""
    print("🔧 音频系统统一测试")
    print("=" * 50)
    
    test_results = []
    
    # 运行各项测试
    test_results.append(await test_speech_synthesis())
    test_results.append(await test_microphone_input())
    test_results.append(await test_docker_environment())
    test_results.append(await test_integration())
    
    # 统计结果
    passed = sum(test_results)
    total = len(test_results)
    
    print(f"\n📊 测试结果总结:")
    print(f"   通过: {passed}/{total}")
    print(f"   成功率: {passed/total*100:.1f}%")
    
    if passed == total:
        print("\n🎉 所有测试通过!")
        print("✅ 音频系统运行正常!")
    else:
        print(f"\n⚠️ 有 {total-passed} 项测试失败")
    
    return passed == total


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)