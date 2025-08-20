"""
语音输入系统 - Agent集成版本
支持完整的唤醒词->TTS响应->录音->识别->Gemini Agent工作流程
"""

import os
import sys
import threading
import time
import logging
from enum import Enum
from typing import Callable, Optional
import speech_recognition as sr
import pyaudio
import numpy as np
import pvporcupine

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from intelligence.speech import Speech

logger = logging.getLogger(__name__)

class VoiceState(Enum):
    """语音系统状态"""
    WAITING_WAKE_WORD = "waiting_wake_word"      # 待机状态，监听唤醒词
    RESPONDING = "responding"                     # TTS播报"我在"
    RECORDING = "recording"                       # 录音用户语音
    PROCESSING = "processing"                     # 语音识别处理
    WAITING_AGENT = "waiting_agent"              # 等待Gemini Agent响应

class VoiceInputManager:
    """Agent集成语音输入管理器 - 状态机版本"""
    
    def __init__(self, 
                 on_speech_detected: Optional[Callable[[str], None]] = None,
                 on_agent_response_ready: Optional[Callable[[], None]] = None):
        """
        初始化语音输入管理器
        
        Args:
            on_speech_detected: 语音识别结果回调函数 - 将文本发送给Gemini Agent
            on_agent_response_ready: Agent响应完成回调 - 恢复唤醒词监听
        """
        self.on_speech_detected = on_speech_detected
        self.on_agent_response_ready = on_agent_response_ready
        
        # 状态管理
        self.current_state = VoiceState.WAITING_WAKE_WORD
        self.state_lock = threading.Lock()
        
        self.keywords = ['小浦']

        self.porcupine = pvporcupine.create(
            access_key="jWbXv+CcgzxJJs5O8y4NoGsT8+B1szn6U8G2FKzB5D0uYgymSuYjyg==",
            model_path="intelligence/models/porcupine_params_zh.pv",
            keyword_paths=['intelligence/models/小浦_zh_linux_v3_0_0.ppn'],
            keywords=self.keywords,
            sensitivities=[0.6]
        )
        
        # 获取音频参数
        self.sample_rate = self.porcupine.sample_rate
        self.chunk_size = self.porcupine.frame_length
        self.format = pyaudio.paInt16
        self.channels = 1
        
        # 语音识别器
        self.recognizer = sr.Recognizer()
        
        # TTS系统
        self.tts = Speech()
        
        # 音频流
        self.audio = pyaudio.PyAudio()
        self.stream = None
        
        # 控制变量
        self.is_active = False
        self.main_thread = None
        self.audio_frames = []
        
        # 录音配置
        self.recording_timeout = 3  # 固定录音时长3秒
        
    def start_system(self):
        """启动语音系统"""
        if self.is_active:
            return
        
        self.stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size
        )
        
        self.is_active = True
        self.current_state = VoiceState.WAITING_WAKE_WORD
        self.main_thread = threading.Thread(target=self._main_loop, daemon=True)
        self.main_thread.start()
        print(f"[语音系统] 启动完成，当前状态: {self.current_state.value}")
    
    def stop_system(self):
        """停止语音系统"""
        self.is_active = False
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        print("[语音系统] 已停止")
    
    def agent_response_complete(self):
        """Agent响应完成，恢复唤醒词监听"""
        with self.state_lock:
            if self.current_state == VoiceState.WAITING_AGENT:
                self.current_state = VoiceState.WAITING_WAKE_WORD
                print("[语音系统] Agent响应完成，恢复唤醒词监听")
    
    def _main_loop(self):
        """主循环 - 状态机核心"""
        print("[语音系统] 主循环启动")
        
        while self.is_active:
            try:
                audio_chunk = self.stream.read(self.chunk_size, exception_on_overflow=False)
                
                with self.state_lock:
                    current_state = self.current_state
                
                if current_state == VoiceState.WAITING_WAKE_WORD:
                    self._handle_wake_word_detection(audio_chunk)
                elif current_state == VoiceState.RECORDING:
                    self._handle_recording(audio_chunk)
                # 其他状态不处理音频
                    
            except Exception as e:
                print(f"[语音系统] 主循环错误: {e}")
                time.sleep(0.1)
    
    def _handle_wake_word_detection(self, audio_chunk):
        """处理唤醒词检测"""
        audio_frame = np.frombuffer(audio_chunk, dtype=np.int16)
        keyword_index = self.porcupine.process(audio_frame)
        
        if keyword_index >= 0:
            print(f"[语音系统] 检测到唤醒词: {self.keywords[keyword_index]}")
            self._transition_to_responding()
    
    def _transition_to_responding(self):
        """转换到响应状态"""
        with self.state_lock:
            self.current_state = VoiceState.RESPONDING
        
        print("[语音系统] 状态转换: 响应中...")
        
        # 在单独线程中播报"我在"
        threading.Thread(target=self._play_response_and_start_recording, daemon=True).start()
    
    def _play_response_and_start_recording(self):
        """播报响应并开始录音"""
        try:
            # TTS播报"我在"
            success = self.tts.say("我在")
            if success:
                print("[语音系统] TTS播报完成")
            else:
                print("[语音系统] TTS播报失败")
            
            # 转换到录音状态
            with self.state_lock:
                self.current_state = VoiceState.RECORDING
                self.audio_frames = []
            
            print(f"[语音系统] 开始录音，时长: {self.recording_timeout}秒")
            
            # 设置录音超时
            threading.Timer(self.recording_timeout, self._stop_recording).start()
            
        except Exception as e:
            print(f"[语音系统] 响应处理错误: {e}")
            # 出错回到等待状态
            with self.state_lock:
                self.current_state = VoiceState.WAITING_WAKE_WORD
    
    def _handle_recording(self, audio_chunk):
        """处理录音"""
        self.audio_frames.append(audio_chunk)
    
    def _stop_recording(self):
        """停止录音并开始处理"""
        with self.state_lock:
            if self.current_state != VoiceState.RECORDING:
                return
            self.current_state = VoiceState.PROCESSING
        
        print("[语音系统] 录音结束，开始语音识别...")
        threading.Thread(target=self._process_speech, daemon=True).start()
    
    def _process_speech(self):
        """处理语音识别"""
        if not self.audio_frames:
            print("[语音系统] 没有录音数据")
            with self.state_lock:
                self.current_state = VoiceState.WAITING_WAKE_WORD
            return
        
        try:
            # 合并音频数据
            audio_data = b''.join(self.audio_frames)
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            audio_data_sr = sr.AudioData(audio_array.tobytes(), self.sample_rate, 2)
            
            # 语音识别
            text = self.recognizer.recognize_google(audio_data_sr, language='zh-CN')
            
            print(f"[语音系统] 识别结果: '{text}'")
            
            # 转换到等待Agent状态
            with self.state_lock:
                self.current_state = VoiceState.WAITING_AGENT
            
            # 发送给Agent
            if text and self.on_speech_detected:
                self.on_speech_detected(text)
            else:
                # 没有识别结果，回到等待状态
                with self.state_lock:
                    self.current_state = VoiceState.WAITING_WAKE_WORD
                    
        except Exception as e:
            print(f"[语音系统] 语音识别失败: {e}")
            # 识别失败，回到等待状态
            with self.state_lock:
                self.current_state = VoiceState.WAITING_WAKE_WORD
        
        finally:
            self.audio_frames = []
    
    def __del__(self):
        """析构函数"""
        try:
            self.stop_system()
            self.porcupine.delete()
            self.audio.terminate()
        except:
            pass


def main():
    """测试完整的Agent语音交互流程"""
    print("=== Agent语音系统测试 ===")
    
    def on_speech_detected(text: str):
        """模拟发送给Gemini Agent"""
        print(f"[模拟Agent] 收到用户语音: '{text}'")
        print("[模拟Agent] 正在处理...")
        
        # 模拟Agent处理时间 (3秒)
        def agent_processing():
            time.sleep(3)
            print("[模拟Agent] 处理完成，发送响应")
            # 通知语音系统Agent响应完成
            manager.agent_response_complete()
        
        threading.Thread(target=agent_processing, daemon=True).start()
    
    def on_agent_ready():
        """Agent响应完成回调"""
        print("[语音系统] Agent响应完成，系统准备好下次交互")
    
    manager = VoiceInputManager(
        on_speech_detected=on_speech_detected,
        on_agent_response_ready=on_agent_ready
    )
    
    manager.start_system()
    print("\n[测试] 语音系统已启动")
    print("[测试] 说 '小浦' 激活系统")
    print("[测试] 系统会播报'我在'然后录音10秒")
    print("[测试] 按Ctrl+C退出测试")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[测试] 退出测试")
        manager.stop_system()


if __name__ == "__main__":
    main()