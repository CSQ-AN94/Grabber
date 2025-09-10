"""
语音系统管理器
"""

import os
import sys
import threading
import time
from enum import Enum
from typing import Callable, Optional
import pyaudio
import numpy as np
import sherpa_onnx

# 添加项目路径
project_root = os.path.dirname(os.path.dirname(__file__))
sys.path.insert(0, project_root)

from intelligence.speech import Speech


class VoiceState(Enum):
    """语音系统状态机
    
    状态职责：
    SLEEPING：待机，监听唤醒词       
    SPEAKING：TTS播报响应           
    RECORDING：VAD动态时间录音+非流式语音识别      
    ACTING：Agent思考和操作         
    
    状态转移路径：
    SLEEPING → SPEAKING: 检测到唤醒词，开始TTS播报"我在"
    SPEAKING → RECORDING: TTS播报完成，开始录音识别
    RECORDING → ACTING: VAD检测语音结束，识别完成，交给Agent
    ACTING → SPEAKING: Agent处理完成，有响应需要播报
    SPEAKING → SLEEPING: TTS播报完成，无后续对话，回到待机
    
    未来扩展：
    SPEAKING → RECORDING: 对话窗口检测，持续对话无需重复唤醒
    """
    
    SLEEPING = "sleeping"
    SPEAKING = "speaking"
    RECORDING = "recording"  
    ACTING = "acting"


class VoiceManager:
    """语音系统管理器
    
    状态转移流程：
    SLEEPING → SPEAKING → RECORDING → ACTING → SPEAKING → SLEEPING
    """
    
    def __init__(self, 
                 on_speech_detected: Optional[Callable[[str], None]] = None):
        """
        初始化语音系统管理器
        
        Args:
            on_speech_detected: 语音识别结果回调 (ACTING状态调用)
        """
        # 当前状态
        self.current_state = VoiceState.SLEEPING
        
        # 回调函数
        self.on_speech_detected = on_speech_detected
        
        # 音频设备
        self.audio = pyaudio.PyAudio()
        self.stream = None
        self.is_active = False
        
        # 音频参数
        self.sample_rate = 16000
        self.chunk_size = 1600
        self.format = pyaudio.paFloat32
        self.channels = 1
        
        # 模型路径
        self.model_dir = "./intelligence/audio_models"
        
        # KWS唤醒词检测 (SLEEPING状态使用)
        kws_dir = f"{self.model_dir}/sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01"
        self.keyword_spotter = sherpa_onnx.KeywordSpotter(
            tokens=f"{kws_dir}/tokens.txt",
            encoder=f"{kws_dir}/encoder-epoch-12-avg-2-chunk-16-left-64.onnx",
            decoder=f"{kws_dir}/decoder-epoch-12-avg-2-chunk-16-left-64.onnx",
            joiner=f"{kws_dir}/joiner-epoch-12-avg-2-chunk-16-left-64.onnx",
            keywords_file=f"{kws_dir}/keywords.txt",
            keywords_score=1.5,
            keywords_threshold=0.25,
            provider="cpu",
        )
        self.kws_stream = None
        
        # VAD+ASR语音识别 (RECORDING状态使用)
        self.vad = sherpa_onnx.VoiceActivityDetector(
            sherpa_onnx.VadModelConfig(
                silero_vad=sherpa_onnx.SileroVadModelConfig(
                    model=f"{self.model_dir}/silero_vad.onnx",
                    threshold=0.5,
                    min_silence_duration=0.25,
                    min_speech_duration=0.1,
                ),
                sample_rate=self.sample_rate
            ),
            buffer_size_in_seconds=30
        )
        
        sense_voice_dir = f"{self.model_dir}/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17"
        self.sense_voice = sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=f"{sense_voice_dir}/model.int8.onnx",
            tokens=f"{sense_voice_dir}/tokens.txt",
            num_threads=2,
            use_itn=True,
            debug=False
        )
        self.recording_buffer = []
        
        # TTS系统 (SPEAKING状态使用)
        self.tts = Speech()
        
        # 控制线程
        self.main_thread = None
        
        print("[语音系统] 语音系统初始化完成")
        
    def start_system(self):
        """启动语音系统"""
        if self.is_active:
            return
        
        print("[语音系统] 初始化音频流...")
        
        # 创建音频流
        self.stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.sample_rate,
            input=True,
            frames_per_buffer=self.chunk_size
        )
        
        # 创建KWS流
        self.kws_stream = self.keyword_spotter.create_stream()
        
        # 启动主循环
        self.is_active = True
        self.main_thread = threading.Thread(target=self._main_loop, daemon=True)
        self.main_thread.start()
        
        print(f"[语音系统] 启动完成，当前状态: {self.current_state.value}")
    
    def stop_system(self):
        """停止语音系统"""
        if not self.is_active:
            return
        
        self.is_active = False
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
        
        if self.main_thread:
            self.main_thread.join(timeout=2)
            self.main_thread = None
        
        print("[语音系统] 已停止")
    
    def agent_response_complete(self, response_text: Optional[str] = None):
        """Agent响应完成，触发状态转移
        
        Args:
            response_text: Agent的响应文本，如果有则进入SPEAKING状态，否则进入SLEEPING状态
        """
        if response_text:
            # ACTING → SPEAKING: 有响应需要播报
            print(f"[状态转移] ACTING → SPEAKING: 播报Agent响应")
            self.current_state = VoiceState.SPEAKING
            threading.Thread(target=self._speak_response, args=(response_text,), daemon=True).start()
        else:
            # ACTING → SLEEPING: 无响应，直接回到待机
            print(f"[状态转移] ACTING → SLEEPING: 无响应，回到待机")
            self.current_state = VoiceState.SLEEPING
    
    def _main_loop(self):
        """主循环 - 状态机核心
        
        根据当前状态处理音频：
        - SLEEPING: 监听唤醒词
        - RECORDING: 录音+识别
        - SPEAKING/ACTING: 不处理音频
        """
        while self.is_active:
            audio_chunk = self.stream.read(self.chunk_size, exception_on_overflow=False)
            current_state = self.current_state
            
            # 状态机音频处理
            if current_state == VoiceState.SLEEPING:
                self._handle_sleeping(audio_chunk)
            elif current_state == VoiceState.RECORDING:
                self._handle_recording(audio_chunk)
            # SPEAKING和ACTING状态不处理音频
    
    # 状态机处理方法
    
    def _handle_sleeping(self, audio_chunk):
        """SLEEPING状态处理：监听唤醒词
        
        状态转移：SLEEPING → SPEAKING (检测到唤醒词)
        """
        audio_frame = np.frombuffer(audio_chunk, dtype=np.float32)
        self.kws_stream.accept_waveform(self.sample_rate, audio_frame)
        
        while self.keyword_spotter.is_ready(self.kws_stream):
            self.keyword_spotter.decode_stream(self.kws_stream)
            result = self.keyword_spotter.get_result(self.kws_stream)
            
            if result:
                print(f"[语音系统] 检测到唤醒词: {result}")
                self.keyword_spotter.reset_stream(self.kws_stream)
                
                # SLEEPING → SPEAKING
                self.current_state = VoiceState.SPEAKING
                print(f"[状态转移] SLEEPING → SPEAKING")
                
                # 启动TTS播报
                threading.Thread(target=self._speak_wake_response, daemon=True).start()
                break
    
    def _handle_recording(self, audio_chunk):
        """RECORDING状态处理：录音+语音识别"""
        audio_frame = np.frombuffer(audio_chunk, dtype=np.float32)
        self.recording_buffer.append(audio_frame)
        
        # VAD处理
        self.vad.accept_waveform(audio_frame)
        
        # 处理检测到的语音段
        while not self.vad.empty():
            stream = self.sense_voice.create_stream()
            stream.accept_waveform(self.sample_rate, self.vad.front.samples)
            self.vad.pop()
            
            # 识别语音
            self.sense_voice.decode_stream(stream)
            text = stream.result.text.strip()
            
            if text:
                print(f"[语音系统] 识别结果: '{text}'")
                # RECORDING → ACTING
                self.current_state = VoiceState.ACTING
                print(f"[状态转移] RECORDING → ACTING")
                
                # 清理缓冲区
                self.recording_buffer = []
                
                # 调用回调函数
                if self.on_speech_detected:
                    self.on_speech_detected(text)
                break
    
    def _speak_wake_response(self):
        """SPEAKING状态处理：播报唤醒响应"""
        print(f"[语音系统] SPEAKING: 播报'我在'")
        
        # TTS播报"我在"
        self.tts.say("我在")
        print("[语音系统] TTS播报完成")
        
        # SPEAKING → RECORDING
        self.current_state = VoiceState.RECORDING
        self.recording_buffer = []
        print(f"[状态转移] SPEAKING → RECORDING")
        
        print("[语音系统] 开始录音，VAD智能截断模式")
    
    def _speak_response(self, response_text: str):
        """SPEAKING状态处理：播报Agent响应"""
        print(f"[语音系统] SPEAKING: 播报Agent响应 '{response_text}'")
        
        # TTS播报Agent响应
        self.tts.say(response_text)
        print("[语音系统] Agent响应播报完成")
        
        # SPEAKING → SLEEPING
        self.current_state = VoiceState.SLEEPING
        print(f"[状态转移] SPEAKING → SLEEPING")
        
        print("[语音系统] 回到待机状态")
    
    def __del__(self):
        """析构函数"""
        try:
            self.stop_system()
            self.audio.terminate()
        except:
            pass


def main():
    """测试语音系统状态机交互流程"""
    print("=== 语音系统状态机测试 ===")
    
    def on_speech_detected(text: str):
        """模拟发送给Gemini Agent (ACTING状态调用)"""
        print(f"[模拟Agent] 收到用户语音: '{text}'")
        print("[模拟Agent] 正在处理...")
        
        # 模拟Agent处理时间
        def agent_processing():
            time.sleep(2)
            response_text = "你好，我是小浦，很高兴为你服务！"
            print(f"[模拟Agent] 处理完成，响应: '{response_text}'")
            # Agent响应完成API：传递响应文本
            voice_manager.agent_response_complete(response_text)
        
        threading.Thread(target=agent_processing, daemon=True).start()
    
    voice_manager = VoiceManager(on_speech_detected=on_speech_detected)
    
    voice_manager.start_system()
    print("\n[测试] 语音系统已启动")
    print("[测试] 状态机流程: SLEEPING → SPEAKING → RECORDING → ACTING → SPEAKING → SLEEPING")
    print("[测试] 说 '小浦' 激活系统")
    print("[测试] 按Ctrl+C退出测试")
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n[测试] 退出测试")
        voice_manager.stop_system()


if __name__ == "__main__":
    main()