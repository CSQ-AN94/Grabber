#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
语音系统测试脚本
测试TTS（文本转语音）功能，音频处理由Gemini Live API处理
支持iFlytek WebAPI集成
"""

import sys
import os
import time
import asyncio

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from intelligence.speech import SpeechSystem, SpeechConfig


def test_speech_synthesis(speech_system: SpeechSystem):
    """测试语音合成 (TTS)"""
    print("\n--- [Test] Speech Synthesis (TTS) ---")
    
    test_texts = [
        "你好，这是一个语音合成测试。",
        "如果能听到我说话，说明一切正常。",
        "智慧零售机器人系统正在运行。",
        "测试完成。"
    ]
    
    try:
        for i, text in enumerate(test_texts, 1):
            print(f"测试 {i}/{len(test_texts)}: {text}")
            
            if asyncio.iscoroutinefunction(speech_system.say):
                # 异步版本
                asyncio.run(speech_system.say(text))
            else:
                # 同步版本
                speech_system.say(text)
            
            print(f"TTS 测试 {i} 完成")
            time.sleep(1)
        
        print("--- TTS Test PASSED ---")
        return True
        
    except Exception as e:
        print(f"TTS Test FAILED: {e}")
        return False


def test_gemini_voice_processing():
    """测试Gemini语音处理"""
    print("\n--- [Test] Gemini Voice Processing ---")
    print("语音识别由Gemini Live API处理")
    print("这里仅显示音频处理流程说明")
    
    try:
        print("音频流程说明:")
        print("  1. 音频通过麦克风捕获")
        print("  2. 实时发送到Gemini Live API")
        print("  3. Gemini直接处理音频并理解语义")
        print("  4. 返回结构化命令响应")
        print("--- Gemini Voice Processing Test Info ---")
        return True
            
    except Exception as e:
        print(f"Voice Processing Test FAILED: {e}")
        return False


def test_speech_loop(speech_system: SpeechSystem):
    """测试语音交互循环"""
    print("\n--- [Test] Speech Interaction Loop ---")
    print("语音识别由Gemini Live API处理")
    print("输入'quit'退出测试")
    
    try:
        while True:
            # 模拟语音交互
            user_input = input("\n请输入测试文本（或'quit'退出）: ")
            
            if user_input.lower() == 'quit':
                break
                
            if user_input.strip():
                print(f"模拟语音输入: {user_input}")
                
                # 模拟执行命令后的回复
                response = f"收到您的指令：{user_input}。正在处理..."
                print(f"系统回复: {response}")
                
                # TTS播报
                if asyncio.iscoroutinefunction(speech_system.say):
                    asyncio.run(speech_system.say(response))
                else:
                    speech_system.say(response)
                    
                print("语音播报完成")
        
        print("--- Speech Loop Test PASSED ---")
        return True
        
    except Exception as e:
        print(f"Speech Loop Test FAILED: {e}")
        return False


def test_speech_config(speech_system: SpeechSystem):
    """测试语音配置"""
    print("\n--- [Test] Speech Configuration ---")
    
    try:
        # 检查配置
        if hasattr(speech_system, 'config'):
            config = speech_system.config
            print(f"Speech config loaded")
            
            # 显示配置信息
            if hasattr(config, '__dict__'):
                for key, value in config.__dict__.items():
                    if 'key' not in key.lower() and 'secret' not in key.lower():
                        print(f"  {key}: {value}")
        else:
            print("No config attribute found")
        
        print("--- Speech Configuration Test PASSED ---")
        return True
        
    except Exception as e:
        print(f"Speech Configuration Test FAILED: {e}")
        return False


def run_speech_tests():
    """运行所有语音测试"""
    print("=== 语音系统测试 ===")
    
    try:
        # 加载配置
        app_config = load_config("config.ini")
        
        # 初始化语音系统
        speech_system = SpeechSystem()
        print("语音系统初始化成功")
        
        # 运行测试菜单
        while True:
            print("\n" + "="*40)
            print("语音系统测试菜单")
            print("="*40)
            print("1. 测试语音合成 (TTS)")
            print("2. 测试Gemini语音处理说明")
            print("3. 测试语音交互循环")
            print("4. 测试语音配置")
            print("5. 运行所有测试")
            print("Q. 退出")
            print("\n注意：语音识别由Gemini Live API处理")
            
            choice = input("请选择: ").upper()
            
            if choice == '1':
                test_speech_synthesis(speech_system)
            elif choice == '2':
                test_gemini_voice_processing()
            elif choice == '3':
                test_speech_loop(speech_system)
            elif choice == '4':
                test_speech_config(speech_system)
            elif choice == '5':
                test_speech_config(speech_system)
                test_speech_synthesis(speech_system)
                test_gemini_voice_processing()
            elif choice == 'Q':
                break
            else:
                print("无效选择，请重试")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"语音测试失败: {e}")
    finally:
        print("语音测试结束")


if __name__ == "__main__":
    run_speech_tests()