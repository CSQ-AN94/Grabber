#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grabber智能零售机器人 - Agent驱动版本
基于完善的Agent系统实现智能语音交互和硬件控制
"""

import sys
import os
import logging

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from intelligence.gemini_agent import GeminiAgent

def main():
    """Agent驱动的Grabber主程序"""
    print("=== Grabber智能零售机器人===")
    
    # 配置日志
    logging.basicConfig(level=logging.INFO)
    
    # 选择工具模式
    mode = input("选择模式 - 1:文本对话模式 2:机器人工具模式 (默认2): ").strip()
    enable_tools = mode != "1"  # 默认启用工具模式
    
    # 选择交互方式
    voice_mode = input("选择交互方式 - 1:文本交互 2:语音交互 (默认2): ").strip()
    enable_voice = voice_mode != "1"  # 默认启用语音交互
    
    try:
        # 初始化Agent
        agent = GeminiAgent(enable_tools=enable_tools, enable_voice=enable_voice)
        
        if not agent.is_ready():
            print("Agent初始化失败")
            return
        
        mode_text = '机器人工具模式' if enable_tools else '文本对话模式'
        voice_text = '语音交互' if enable_voice else '文本交互'
        print(f"Grabber系统初始化成功 ({mode_text} + {voice_text})")
        
        if enable_voice:
            # 语音交互模式
            print("\n语音交互模式已启用")
            print("- 系统将自动检测您的语音并智能回复")
            print("- 请对着麦克风说话，AI会自动回应")
            if enable_tools:
                print("- 可以语音指令机器人进行抓取、移动等操作")
            print("- 输入 'quit' 退出程序")
            
            # 启动VAD监听
            agent.start_vad_listening()
            
            try:
                while True:
                    user_input = input("\n输入 'quit' 退出: ").strip()
                    if user_input.lower() in ['quit', 'exit', 'q']:
                        break
            except KeyboardInterrupt:
                print("\n程序被用户中断")
            finally:
                agent.stop_vad_listening()
        else:
            # 文本交互模式
            print("\n文本交互模式")
            print("- 直接输入文本与AI对话")
            if enable_tools:
                print("- 可以文本指令机器人进行抓取、移动等操作")
            print("- 输入 'quit' 退出程序")
            
            while True:
                user_input = input("\n请输入文本: ").strip()
                if user_input.lower() in ['quit', 'exit', 'q']:
                    break
                
                if not user_input:
                    continue
                
                # 处理文本输入
                result = agent.process_text(user_input)
                
                if result["success"]:
                    print(f"AI回复: {result['text']}")
                else:
                    print(f"处理失败: {result['error']}")
    
    except KeyboardInterrupt:
        print("\n用户中断，退出")
    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()