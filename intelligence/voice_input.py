"""
语音输入系统 - VAD版本
支持语音活动检测(VAD)的实时语音识别
"""

import threading
import time
import logging
from typing import Callable, Optional
import speech_recognition as sr
import webrtcvad
import pyaudio
import numpy as np

logger = logging.getLogger(__name__)


class VADDetector:
    """VAD检测器 - 检测语音活动"""
    
    def __init__(self, sample_rate: int = 16000, frame_duration: int = 30):
        """
        初始化VAD检测器
        
        Args:
            sample_rate: 采样率 (8000, 16000, 32000, 48000)
            frame_duration: 帧长度毫秒 (10, 20, 30)
        """
        self.sample_rate = sample_rate
        self.frame_duration = frame_duration
        self.frame_bytes = int(sample_rate * frame_duration / 1000) * 2  # 16-bit
        
        # 创建VAD实例 (aggressiveness: 0-3, 3最激进)
        self.vad = webrtcvad.Vad(1)
        
        # VAD状态
        self.is_speech_active = False
        self.speech_frames = []
        self.silence_frames = 0
        self.speech_frames_required = 4  # 连续4帧检测到语音才认为开始(120ms)
        self.silence_frames_required = 10  # 连续10帧静音才认为结束(300ms)
        
    def process_frame(self, frame_data: bytes) -> bool:
        """
        处理音频帧，返回是否检测到语音活动
        
        Args:
            frame_data: 音频帧数据
            
        Returns:
            bool: True表示检测到语音活动变化
        """
        if len(frame_data) != self.frame_bytes:
            return False
        
        try:
            # VAD检测
            is_speech = self.vad.is_speech(frame_data, self.sample_rate)
            
            if is_speech:
                self.speech_frames.append(frame_data)
                self.silence_frames = 0
                
                # 检测语音开始
                if not self.is_speech_active and len(self.speech_frames) >= self.speech_frames_required:
                    self.is_speech_active = True
                    logger.info("VAD: 检测到语音开始")
                    return True
                    
            else:
                self.silence_frames += 1
                
                # 检测语音结束
                if self.is_speech_active and self.silence_frames >= self.silence_frames_required:
                    self.is_speech_active = False
                    self.speech_frames = []
                    logger.info("VAD: 检测到语音结束")
                    return True
                    
        except Exception as e:
            logger.error(f"VAD处理帧错误: {e}")
            
        return False


class VoiceRecognizer:
    """语音识别器"""
    
    def __init__(self):
        self.recognizer = sr.Recognizer()
        # 调整环境噪音
        try:
            with sr.Microphone(sample_rate=16000) as source:
                logger.info("正在调整麦克风环境噪音...")
                self.recognizer.adjust_for_ambient_noise(source, duration=1)
                logger.info("环境噪音调整完成")
        except Exception as e:
            logger.warning(f"环境噪音调整失败: {e}")
    
    def recognize_audio(self, audio_data: sr.AudioData) -> str:
        """识别音频数据"""
        try:
            text = self.recognizer.recognize_google(audio_data, language='zh-CN')
            logger.info(f"语音识别结果: {text}")
            return text
        except sr.UnknownValueError:
            logger.warning("语音识别：无法理解音频")
            return ""
        except sr.RequestError as e:
            logger.error(f"语音识别服务错误: {e}")
            return ""


class VoiceInputManager:
    """VAD语音输入管理器"""
    
    def __init__(self, on_speech_detected: Optional[Callable[[str], None]] = None):
        """
        初始化语音输入管理器
        
        Args:
            on_speech_detected: 语音识别结果回调函数
        """
        self.on_speech_detected = on_speech_detected
        
        # 音频参数
        self.sample_rate = 16000
        self.chunk_size = 480  # 30ms at 16kHz
        self.format = pyaudio.paInt16
        self.channels = 1
        
        # 组件
        self.vad_detector = VADDetector(self.sample_rate)
        self.voice_recognizer = VoiceRecognizer()
        
        # 音频流
        self.audio = pyaudio.PyAudio()
        self.stream = None
        
        # 控制变量
        self.is_listening = False
        self.is_recording = False
        self.is_paused = False  # 暂停标志
        self.listen_thread = None
        self.audio_frames = []
        
    def start_listening(self):
        """开始持续监听"""
        if self.is_listening:
            logger.warning("已经在监听中")
            return
            
        try:
            # 打开音频流
            self.stream = self.audio.open(
                format=self.format,
                channels=self.channels,
                rate=self.sample_rate,
                input=True,
                frames_per_buffer=self.chunk_size
            )
            
            self.is_listening = True
            self.listen_thread = threading.Thread(target=self._listen_loop, daemon=True)
            self.listen_thread.start()
            
            logger.info("VAD监听已启动")
            
        except Exception as e:
            logger.error(f"启动监听失败: {e}")
            self.stop_listening()
    
    def stop_listening(self):
        """停止监听"""
        self.is_listening = False
        
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
            self.stream = None
            
        if self.listen_thread:
            self.listen_thread.join(timeout=2)
            
        logger.info("VAD监听已停止")
    
    def pause_listening(self):
        """暂停监听（用于语音播报期间）"""
        self.is_paused = True
        logger.debug("VAD监听已暂停")
    
    def resume_listening(self):
        """恢复监听"""
        self.is_paused = False
        logger.debug("VAD监听已恢复")
    
    def _listen_loop(self):
        """监听循环"""
        while self.is_listening:
            try:
                # 读取音频数据（即使暂停也要读取，避免缓冲区溢出）
                audio_chunk = self.stream.read(self.chunk_size, exception_on_overflow=False)
                
                # 如果暂停，跳过处理
                if self.is_paused:
                    time.sleep(0.01)
                    continue
                
                # VAD检测
                speech_change = self.vad_detector.process_frame(audio_chunk)
                
                if speech_change:
                    if self.vad_detector.is_speech_active:
                        # 开始录音
                        self._start_recording()
                    else:
                        # 结束录音并识别
                        self._stop_recording_and_recognize()
                
                # 如果在录音中，保存音频数据
                if self.is_recording:
                    self.audio_frames.append(audio_chunk)
                    
            except Exception as e:
                logger.error(f"监听循环错误: {e}")
                time.sleep(0.01)  # 避免错误循环
    
    def _start_recording(self):
        """开始录音"""
        if not self.is_recording:
            self.is_recording = True
            self.audio_frames = []
            # 包含VAD检测到的语音帧
            self.audio_frames.extend(self.vad_detector.speech_frames)
            logger.info("开始录音...")
    
    def _stop_recording_and_recognize(self):
        """停止录音并进行语音识别"""
        if not self.is_recording:
            return
            
        self.is_recording = False
        logger.info("录音结束，开始识别...")
        
        # 处理音频数据
        if self.audio_frames:
            # 合并音频数据
            audio_data = b''.join(self.audio_frames)
            
            # 转换为AudioData对象
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            audio_data_sr = sr.AudioData(
                audio_array.tobytes(), 
                self.sample_rate, 
                2  # 16-bit
            )
            
            # 异步识别
            threading.Thread(
                target=self._recognize_async, 
                args=(audio_data_sr,), 
                daemon=True
            ).start()
        
        self.audio_frames = []
    
    def _recognize_async(self, audio_data: sr.AudioData):
        """异步语音识别"""
        text = self.voice_recognizer.recognize_audio(audio_data)
        if text and self.on_speech_detected:
            self.on_speech_detected(text)
    
    def __del__(self):
        """析构函数"""
        self.stop_listening()
        if hasattr(self, 'audio'):
            self.audio.terminate()


def main():
    """测试VAD语音输入"""
    print("=== VAD语音输入测试 ===")
    
    def on_speech(text: str):
        print(f"识别到语音: {text}")
    
    # 创建管理器
    manager = VoiceInputManager(on_speech_detected=on_speech)
    
    try:
        # 开始监听
        manager.start_listening()
        print("正在监听语音，请说话...")
        print("按 Ctrl+C 退出")
        
        # 保持运行
        while True:
            time.sleep(0.1)
            
    except KeyboardInterrupt:
        print("\n退出VAD测试")
    finally:
        manager.stop_listening()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()