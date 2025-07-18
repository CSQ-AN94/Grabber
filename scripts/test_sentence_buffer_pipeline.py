#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试 SentenceBuffer 和 SpeechSystem 组成的完整语音输出流水线。

本测试旨在模拟一个真实的场景：
1.  一个“生产者”线程模拟Gemini Agent，以不规则、零散的方式生成文本片段。
2.  这些文本片段被送入 SentenceBuffer进行处理和重组。
3.  一个“消费者”线程从 SentenceBuffer 中获取完整的句子。
4.  获取到的完整句子被交给 SpeechSystem 进行语音合成和播放。

通过这个独立的测试，我们可以在不修改主程序的情况下，验证整个语音输出流程的正确性和健壮性。
"""

import sys
import os
import asyncio
import threading
import time
import random

# 将项目根目录添加到Python路径中，以便导入其他模块
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.speech import SpeechSystem, SentenceBuffer
from utils.config import load_config, setup_logging

# --- 模拟的Gemini文本片段 ---
# 这些片段模拟了Gemini在流式响应中可能返回的文本，具有不自然的断点。
SIMULATED_GEMINI_FRAGMENTS = [
    "您",
    "好，我是您的智能",
    "零售助手。",
    "今天天气不错！",
    "请问有什么可以帮您的吗？",
    "我们店里有牙膏、",
    "雀巢咖啡、",
    "洗发水",
    "和可口可乐。您需要哪一个？",
    "好的，",
    "正在为您处理，",
    "请稍候……",
    "操作完成。",
]

def mock_gemini_producer(buffer: SentenceBuffer, stop_event: threading.Event):
    """
    模拟Gemini Agent，持续生成文本片段并添加到SentenceBuffer。
    """
    print("🤖 [生产者] Gemini模拟器已启动...")
    for fragment in SIMULATED_GEMINI_FRAGMENTS:
        if stop_event.is_set():
            break
        
        # 模拟网络延迟和不规则的文本到达时间
        time.sleep(random.uniform(0.2, 1.5))
        
        print(f"🤖 [生产者] -> 接收到片段: '{fragment}'")
        buffer.add_text(fragment)
    
    # 所有片段发送完毕后，调用flush确保缓冲区剩余内容被处理
    buffer.flush()
    print("🤖 [生产者] 所有片段已发送，模拟器关闭。")


def speech_consumer(buffer: SentenceBuffer, speech_system: SpeechSystem, stop_event: threading.Event):
    """
    消费者线程，从SentenceBuffer获取完整句子并交给SpeechSystem播放。
    """
    print("🗣️ [消费者] 语音播报消费者已启动...")
    sentence_count = 0
    while not stop_event.is_set():
        # 非阻塞地从队列中获取一个完整的句子
        sentence = buffer.get_sentence(block=False)
        
        if sentence:
            sentence_count += 1
            print(f"🗣️ [消费者] <- 获取到完整句子 #{sentence_count}: '{sentence}'")
            print("   ...正在提交给语音合成系统...")
            
            # 使用正确的异步调用方式提交到语音系统
            try:
                # 创建新的事件循环来处理异步调用
                from concurrent.futures import ThreadPoolExecutor
                
                def run_speech_task(text_to_speak):
                    """在新线程中运行语音合成任务"""
                    try:
                        if not text_to_speak or not text_to_speak.strip():
                            print(f"   ...空文本，跳过播放。")
                            return
                            
                        # 为这个线程创建新的事件循环
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        # 异步调用 speech_system.say
                        result = loop.run_until_complete(speech_system.say(text_to_speak))
                        
                        # 打印结果
                        if result.get("success"):
                            print(f"   ...'{text_to_speak[:20]}...' 播放完成。")
                        else:
                            print(f"   ...'{text_to_speak[:20]}...' 播放失败: {result.get('message', '未知错误')}")
                        
                        loop.close()
                    except Exception as e:
                        print(f"   ...'{text_to_speak[:20] if text_to_speak else 'unknown'}...' 播放错误: {e}")
                
                # 在独立线程中启动语音任务（fire-and-forget）
                import threading as thread_module
                speech_thread = thread_module.Thread(target=run_speech_task, args=(sentence,))
                speech_thread.daemon = True
                speech_thread.start()
                
                print(f"   ...'{sentence[:20]}...' 已提交到播放队列。")
                
            except Exception as e:
                print(f"   ...语音播报时出错: {e}")
        else:
            # 如果没有获取到句子，检查生产者是否还在运行
            producer_alive = False
            for t in threading.enumerate():
                if t.name == "ProducerThread":
                    producer_alive = t.is_alive()
                    break
            
            # 如果生产者已停止且队列为空，退出
            if not producer_alive and buffer.sentence_queue.empty():
                print("🗣️ [消费者] 生产者已停止且队列为空，退出。")
                break
            
            # 短暂等待再检查
            time.sleep(0.1)
    
    print(f"🗣️ [消费者] 总共处理了 {sentence_count} 个句子")


async def main():
    """
    主函数，负责初始化系统并编排测试流程。
    """
    print("="*50)
    print("开始测试SentenceBuffer与SpeechSystem的集成流水线")
    print("="*50)

    # 初始化日志和配置
    setup_logging("INFO")
    config = load_config()

    # 1. 初始化核心组件
    print("\n[1/3] 初始化语音系统和句子缓冲区...")
    try:
        speech_system = SpeechSystem(config.speech)
        sentence_buffer = SentenceBuffer()
        print("✅ 初始化成功。")
    except Exception as e:
        print(f"❌ 初始化失败: {e}")
        return

    # 2. 创建并启动生产者和消费者线程
    print("\n[2/3] 启动模拟生产者和语音消费者线程...")
    stop_event = threading.Event()
    
    producer_thread = threading.Thread(
        target=mock_gemini_producer, 
        args=(sentence_buffer, stop_event),
        name="ProducerThread"
    )
    
    consumer_thread = threading.Thread(
        target=speech_consumer, 
        args=(sentence_buffer, speech_system, stop_event),
        name="ConsumerThread"
    )
    
    producer_thread.start()
    consumer_thread.start()
    print("✅ 线程已启动。")

    # 3. 等待测试完成
    print("\n[3/3] 测试正在运行... 请注意听取语音输出。")
    print("      (可以 Ctrl+C 提前终止测试)")
    
    try:
        # 等待生产者线程结束
        producer_thread.join()
        
        # 再给消费者一些时间来处理队列中剩余的句子
        time.sleep(5)
        
        # 等待消费者线程结束
        consumer_thread.join(timeout=10)

    except KeyboardInterrupt:
        print("\n🚫 用户请求中断测试...")
        stop_event.set()
    finally:
        # 确保所有资源都被正确关闭
        print("\n[清理] 正在停止所有组件...")
        stop_event.set()
        sentence_buffer.stop()
        speech_system.stop_speech_system()
        
        # 等待线程完全退出
        if producer_thread.is_alive():
            producer_thread.join()
        if consumer_thread.is_alive():
            consumer_thread.join()
            
        print("="*50)
        print("测试结束。")
        print("="*50)


if __name__ == "__main__":
    # 在Docker容器中运行时，可能需要确保Pulseaudio或ALSA配置正确
    # 如果遇到音频问题，请检查 `scripts/setup_docker_audio.sh`
    asyncio.run(main())
