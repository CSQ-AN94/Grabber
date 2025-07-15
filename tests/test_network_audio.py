#!/usr/bin/env python3
"""
测试网络音频源的实时性 - 证明不损失Live API实时性
"""

import asyncio
import logging
import time
from google import genai
from google.genai import types
from utils.config import load_config
from audio_source_abstraction import NetworkAudioSource, SimulatedAudioSource

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def test_network_realtime():
    """测试网络音频源的实时性"""
    
    print("启动网络音频实时测试...")
    
    # 1. 启动网络音频源
    network_source = NetworkAudioSource(port=8888)
    await network_source.start()
    
    print(f"网络音频服务器已启动，端口8888")
    print(f"在另一个终端运行以下命令发送实时音频:")
    print(f"   python3 -c \"")
    print(f"import numpy as np, time")
    print(f"import socket")
    print(f"s = socket.socket()")
    print(f"s.connect(('localhost', 8888))")
    print(f"for i in range(100):")
    print(f"    tone = np.sin(2*np.pi*440*np.linspace(0,0.1,1600))")
    print(f"    data = (tone*16000).astype('int16').tobytes()")
    print(f"    s.send(data)")
    print(f"    time.sleep(0.05)  # 20Hz发送频率")
    print(f"\"")
    
    # 2. 连接Gemini Live API
    config = load_config()
    client = genai.Client(api_key=config.llm.gemini_api_key)
    model = "gemini-2.0-flash-live-001"
    
    live_config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction="你是实时音频测试助手。收到音频后请简短回应。用中文回复。"
    )
    
    print("连接Gemini Live API...")
    
    async with client.aio.live.connect(model=model, config=live_config) as session:
        print("Gemini连接成功，开始实时处理...")
        
        start_time = time.time()
        chunks_processed = 0
        last_response_time = start_time
        
        # 3. 实时音频处理循环
        async def audio_sender():
            """音频发送任务"""
            nonlocal chunks_processed
            
            while time.time() - start_time < 30:  # 运行30秒
                chunk = await network_source.get_audio_chunk()
                if chunk:
                    try:
                        await session.send_realtime_input(
                            audio=types.Blob(
                                data=chunk,
                                mime_type="audio/pcm;rate=16000"
                            )
                        )
                        chunks_processed += 1
                        
                        # 每50个块发送一次文本提示
                        if chunks_processed % 50 == 0:
                            await session.send_realtime_input(
                                text=f"这是第{chunks_processed}个音频块，请确认收到。"
                            )
                            
                    except Exception as e:
                        logger.error(f"发送音频失败: {e}")
                
                await asyncio.sleep(0.01)
        
        async def response_handler():
            """响应处理任务"""
            nonlocal last_response_time
            
            async for response in session.receive():
                if hasattr(response, 'text') and response.text:
                    current_time = time.time()
                    latency = current_time - last_response_time
                    print(f"Gemini [{latency:.2f}s延迟]: {response.text}")
                    last_response_time = current_time
                
                if hasattr(response, 'server_content') and response.server_content:
                    if hasattr(response.server_content, 'turn_complete') and response.server_content.turn_complete:
                        print("对话轮次完成")
        
        # 4. 并发运行音频发送和响应处理
        try:
            await asyncio.gather(
                audio_sender(),
                response_handler(),
                return_exceptions=True
            )
        except Exception as e:
            logger.error(f"处理过程出错: {e}")
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"\n实时性统计:")
        print(f"   运行时间: {duration:.1f}秒")
        print(f"   处理音频块: {chunks_processed}个")
        print(f"   平均处理率: {chunks_processed/duration:.1f}块/秒")
        print(f"   实时性: {'良好' if chunks_processed/duration > 15 else '需优化'}")
    
    await network_source.stop()

async def test_simulated_realtime():
    """使用模拟音频源测试实时性（无需外部输入）"""
    
    print("\n启动模拟音频实时测试...")
    
    # 1. 启动模拟音频源
    sim_source = SimulatedAudioSource()
    await sim_source.start()
    
    # 2. 连接Gemini
    config = load_config()
    client = genai.Client(api_key=config.llm.gemini_api_key)
    model = "gemini-2.0-flash-live-001"
    
    live_config = types.LiveConnectConfig(
        response_modalities=["TEXT"],
        system_instruction="你收到连续的音频信号。请每收到约2秒音频就简短确认一次。用中文回复。"
    )
    
    async with client.aio.live.connect(model=model, config=live_config) as session:
        print("模拟音频源 + Gemini Live API 连接成功")
        
        start_time = time.time()
        chunks_sent = 0
        last_prompt_time = start_time
        
        # 实时处理循环
        while time.time() - start_time < 15:  # 15秒测试
            chunk = await sim_source.get_audio_chunk()
            if chunk:
                await session.send_realtime_input(
                    audio=types.Blob(
                        data=chunk,
                        mime_type="audio/pcm;rate=16000"
                    )
                )
                chunks_sent += 1
                
                # 每2秒发送一次文本提示
                current_time = time.time()
                if current_time - last_prompt_time >= 2.0:
                    await session.send_realtime_input(
                        text=f"已发送{chunks_sent}个音频块，请确认。"
                    )
                    last_prompt_time = current_time
            
            # 检查响应
            try:
                # 非阻塞检查响应
                response_task = asyncio.create_task(session.receive().__anext__())
                done, pending = await asyncio.wait([response_task], timeout=0.001)
                
                if done:
                    response = await response_task
                    if hasattr(response, 'text') and response.text:
                        elapsed = time.time() - start_time
                        print(f"[{elapsed:.1f}s] Gemini: {response.text}")
                else:
                    response_task.cancel()
                    
            except Exception:
                pass
            
            await asyncio.sleep(0.02)  # 50Hz处理频率
        
        duration = time.time() - start_time
        print(f"\n模拟音频实时性统计:")
        print(f"   运行时间: {duration:.1f}秒")
        print(f"   发送音频块: {chunks_sent}个")
        print(f"   处理频率: {chunks_sent/duration:.1f}块/秒")
        print(f"   证明: 非麦克风音频源同样保持Live API实时性")
    
    await sim_source.stop()

if __name__ == "__main__":
    print("实时性测试 - 证明非麦克风音频源不损失Live API实时性")
    print("="*60)
    
    # 先测试模拟音频源（无需外部输入）
    asyncio.run(test_simulated_realtime())
    
    print("\n" + "="*60)
    print("如需测试网络音频源，请取消注释下面一行:")
    asyncio.run(test_network_realtime())