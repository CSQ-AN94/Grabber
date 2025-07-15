#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini Live API连接测试
测试基本的Live API连接，不涉及复杂音频处理
"""

import asyncio
import logging
from google import genai
from google.genai import types
import numpy as np

async def test_gemini_live_connection():
    """测试Gemini Live API基本连接"""
    print("Gemini Live API连接测试")
    print("=" * 40)
    
    api_key = "AIzaSyDoRYk_kU61IIeEsCuAUaRft2iaeKXtoFE"
    
    try:
        # 1. 创建客户端
        client = genai.Client(api_key=api_key)
        print("Gemini客户端创建成功")
        
        # 2. 测试不同的模型
        models_to_test = [
            "gemini-2.0-flash-live-001",
            "gemini-2.0-flash-exp",
            "models/gemini-2.0-flash-exp"
        ]
        
        for model_name in models_to_test:
            print(f"\n测试模型: {model_name}")
            try:
                # 创建最小配置
                config = {
                    "response_modalities": ["TEXT"],
                    "system_instruction": {
                        "parts": [{"text": "你是一个测试助手。请简短回复。"}]
                    }
                }
                
                # 尝试连接
                async with client.aio.live.connect(model=model_name, config=config) as session:
                    print(f"  {model_name} 连接成功")
                    
                    # 发送简单文本消息（使用正确的方法）
                    await session.send_client_content(
                        turns=[{"role": "user", "parts": [{"text": "你好"}]}],
                        turn_complete=True
                    )
                    print("  文本消息发送成功")
                    
                    # 尝试接收响应
                    response_received = False
                    async for response in session.receive():
                        if hasattr(response, 'text') and response.text:
                            print(f"  收到响应: {response.text[:50]}...")
                            response_received = True
                            break
                    
                    if response_received:
                        print(f"  {model_name} 工作正常")
                        return model_name  # 返回第一个工作的模型
                    else:
                        print(f"  {model_name} 无响应")
                        
            except Exception as e:
                print(f"  {model_name} 失败: {e}")
                
        return None
        
    except Exception as e:
        print(f"Gemini客户端创建失败: {e}")
        return None

async def test_audio_upload():
    """测试音频上传格式"""
    print("\n音频格式测试")
    print("=" * 40)
    
    api_key = "AIzaSyDoRYk_kU61IIeEsCuAUaRft2iaeKXtoFE"
    
    # 创建测试音频（1秒1kHz正弦波）
    sample_rate = 16000
    duration = 1.0
    t = np.linspace(0, duration, int(sample_rate * duration), False)
    test_signal = 0.1 * np.sin(2 * np.pi * 1000 * t)  # 低音量避免失真
    test_audio = (test_signal * 32767).astype(np.int16).tobytes()
    
    print(f"测试音频: {len(test_audio)}字节, {sample_rate}Hz")
    
    # 测试不同的MIME类型
    mime_types = [
        "audio/pcm;rate=16000;bit=16;channels=1",
        "audio/pcm",
        "audio/raw;rate=16000",
        "audio/l16;rate=16000"
    ]
    
    try:
        client = genai.Client(api_key=api_key)
        
        config = {
            "response_modalities": ["TEXT"],
            "system_instruction": {
                "parts": [{"text": "简短回复收到的音频"}]
            }
        }
        
        for mime_type in mime_types:
            print(f"\n测试MIME类型: {mime_type}")
            try:
                async with client.aio.live.connect(model="gemini-2.0-flash-live-001", config=config) as session:
                    # 发送音频
                    await session.send_realtime_input(
                        audio=types.Blob(
                            data=test_audio,
                            mime_type=mime_type
                        )
                    )
                    print(f"  音频发送成功: {mime_type}")
                    
                    # 等待一下看是否有1007错误
                    await asyncio.sleep(1)
                    print(f"  {mime_type} 无1007错误")
                    
            except Exception as e:
                if "1007" in str(e):
                    print(f"  {mime_type} 引起1007错误: {e}")
                else:
                    print(f"  {mime_type} 其他错误: {e}")
                    
    except Exception as e:
        print(f"音频测试失败: {e}")

async def main():
    """主测试函数"""
    print("开始Gemini Live API诊断...")
    
    # 设置日志
    logging.basicConfig(level=logging.INFO)
    
    # 1. 测试基本连接
    working_model = await test_gemini_live_connection()
    
    if working_model:
        print(f"\n找到可用模型: {working_model}")
        
        # 2. 测试音频格式
        await test_audio_upload()
    else:
        print("\n无可用模型，可能的问题:")
        print("   1. API密钥无效或过期")
        print("   2. 账户没有Live API权限")
        print("   3. 网络连接问题")
    
    print("\n诊断完成")

if __name__ == "__main__":
    asyncio.run(main())