"""
语音输入系统 - Agent集成版本
支持唤醒词->TTS响应->录音->识别->Gemini Agent工作流程
"""

import os
import sys
import threading
import time
from enum import Enum
from typing import Callable, Optional
import speech_recognition as sr
import pyaudio
import numpy as np
import sherpa_onnx

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from intelligence.speech import Speech


class VoiceState(Enum):
    """语音系统状态"""
    WAITING_WAKE_WORD = "waiting_wake_word"      # 待机状态，监听唤醒词
    RESPONDING = "responding"                     # TTS播报"我在"
    RECORDING = "recording"                       # 录音用户语音
    PROCESSING = "processing"                     # 语音识别处理
    WAITING_AGENT = "waiting_agent"              # 等待Gemini Agent响应


class VoiceInputManager:
    """Agent集成语音输入管理器"""
    
    def __init__(self, 
                 on_speech_detected: Optional[Callable[[str], None]] = None,
                 on_agent_response_ready: Optional[Callable[[], None]] = None):
        """
        初始化语音输入管理器
        
        Args:
            on_speech_detected: 语音识别结果回调函数
            on_agent_response_ready: Agent响应完成回调
        """
        self.on_speech_detected = on_speech_detected
        self.on_agent_response_ready = on_agent_response_ready
        
        # 状态管理
        self.current_state = VoiceState.WAITING_WAKE_WORD
        self.state_lock = threading.Lock()
        
        # Sherpa-ONNX 配置
        self.model_dir = "intelligence/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
        
        # 创建 Sherpa-ONNX 关键词检测器
        self.keyword_spotter = sherpa_onnx.KeywordSpotter(
            tokens=f"{self.model_dir}/tokens.txt",
            encoder=f"{self.model_dir}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
            decoder=f"{self.model_dir}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
            joiner=f"{self.model_dir}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
            keywords_file=f"{self.model_dir}/keywords.txt",
            keywords_score=1.5,
            keywords_threshold=0.25,
            provider="cpu",
        )
        
        # 音频参数
        self.sample_rate = 16000
        self.chunk_size = 1600  # 100ms
        self.format = pyaudio.paFloat32
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
        self.kws_stream = None
        
        # 录音配置
        self.recording_timeout = 5  # 5秒录音时长
        
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
        self.kws_stream = self.keyword_spotter.create_stream()
        
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
                print("[语音系统] 恢复唤醒词监听")
    
    def _main_loop(self):
        """主循环 - 状态机核心"""
        while self.is_active:
            try:
                audio_chunk = self.stream.read(self.chunk_size, exception_on_overflow=False)
                
                with self.state_lock:
                    current_state = self.current_state
                
                if current_state == VoiceState.WAITING_WAKE_WORD:
                    self._handle_wake_word_detection(audio_chunk)
                elif current_state == VoiceState.RECORDING:
                    self._handle_recording(audio_chunk)
                    
            except Exception as e:
                print(f"[语音系统] 主循环错误: {e}")
                time.sleep(0.1)
    
    def _handle_wake_word_detection(self, audio_chunk):
        """处理唤醒词检测"""
        audio_frame = np.frombuffer(audio_chunk, dtype=np.float32)
        self.kws_stream.accept_waveform(self.sample_rate, audio_frame)
        
        while self.keyword_spotter.is_ready(self.kws_stream):
            self.keyword_spotter.decode_stream(self.kws_stream)
            result = self.keyword_spotter.get_result(self.kws_stream)
            
            if result:
                print(f"[语音系统] 检测到唤醒词: {result}")
                self.keyword_spotter.reset_stream(self.kws_stream)
                self._transition_to_responding()
                break
    
    def _transition_to_responding(self):
        """转换到响应状态"""
        with self.state_lock:
            self.current_state = VoiceState.RESPONDING
        
        print("[语音系统] 检测到唤醒词，正在响应...")
        
        # 在单独线程中播报"我在"
        threading.Thread(target=self._play_response_and_start_recording, daemon=True).start()
    
    def _play_response_and_start_recording(self):
        """播报响应并开始录音"""
        try:
            # TTS播报"我在"
            if self.tts.say("我在"):
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
            audio_array = np.frombuffer(audio_data, dtype=np.float32)
            # 转换为 int16 格式供 speech_recognition 使用
            audio_array_int16 = (audio_array * 32768).astype(np.int16)
            audio_data_sr = sr.AudioData(audio_array_int16.tobytes(), self.sample_rate, 2)
            
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
                with self.state_lock:
                    self.current_state = VoiceState.WAITING_WAKE_WORD
                    
        except Exception as e:
            print(f"[语音系统] 语音识别失败: {e}")
            with self.state_lock:
                self.current_state = VoiceState.WAITING_WAKE_WORD
        
        finally:
            self.audio_frames = []
    
    def __del__(self):
        """析构函数"""
        try:
            self.stop_system()
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
        
        # 模拟Agent处理时间
        def agent_processing():
            time.sleep(3)
            print("[模拟Agent] 处理完成，发送响应")
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
    print("[测试] 系统会播报'我在'然后录音5秒")
    print("[测试] 按Ctrl+C退出测试")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[测试] 退出测试")
        manager.stop_system()


if __name__ == "__main__":
    main()