#!/usr/bin/env python3
"""
测试唤醒词语音系统
"""

import os
import sys
import time

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from intelligence.voice_input import VoiceInputManager

def main():
    """测试唤醒词系统"""
    print("测试开始")
    
    def on_speech_detected(text: str):
        print(f"识别结果: '{text}'")
    
    try:
        manager = VoiceInputManager(on_speech_detected=on_speech_detected)
        manager.start_listening()
        print("监听中... 说 '小浦' 开始录音")
        
        while True:
            time.sleep(1)
            
    except Exception as e:
        print(f"错误: {e}")
        
    except KeyboardInterrupt:
        print("退出测试")
        
    finally:
        if 'manager' in locals():
            manager.stop_listening()

if __name__ == "__main__":
    main()