#!/usr/bin/env python3
"""
音频输入接口定义
定义了音频输入组件必须实现的标准接口
"""

from abc import ABC, abstractmethod
from typing import Optional, Tuple, Dict, Any, Callable


class AudioInputInterface(ABC):
    """
    音频输入接口
    
    所有音频输入组件必须实现此接口，以确保与GeminiAgent的解耦
    """
    
    @abstractmethod
    async def start_recording(self) -> None:
        """
        开始录音
        
        Raises:
            RuntimeError: 如果无法启动录音
        """
        pass
    
    @abstractmethod
    async def stop_recording(self) -> None:
        """
        停止录音
        """
        pass
    
    @abstractmethod
    async def get_audio_event(self) -> Optional[Tuple[str, Optional[bytes]]]:
        """
        获取音频事件
        
        Returns:
            tuple: (事件类型, 数据)
            - ('audio', bytes): 音频数据
            - ('silence_end', None): 静音结束事件
            - ('speech_start', None): 语音开始事件
            - ('speech_end', None): 语音结束事件
            - None: 无事件
        """
        pass
    
    @abstractmethod
    def get_stats(self) -> Dict[str, Any]:
        """
        获取音频输入统计信息
        
        Returns:
            统计信息字典，必须包含：
            - is_running: bool - 是否正在录音
            - audio_source: str - 音频源类型
            - chunks_received: int - 接收的音频块数
            - bytes_received: int - 接收的字节数
            - speech_events: int - 语音事件数
            - silence_events: int - 静音事件数
        """
        pass
    
    @abstractmethod
    def set_event_callbacks(self, 
                          speech_start: Optional[Callable] = None,
                          speech_end: Optional[Callable] = None,
                          silence_end: Optional[Callable] = None) -> None:
        """
        设置事件回调函数
        
        Args:
            speech_start: 语音开始回调
            speech_end: 语音结束回调
            silence_end: 静音结束回调
        """
        pass


class RealAudioInput(AudioInputInterface):
    """
    真实音频输入实现
    
    基于SmartMicrophone的真实音频输入，只使用真实麦克风
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化真实音频输入
        
        Args:
            config: 配置字典，包含采样率、块大小等
        """
        from sensors.smart_microphone import SmartMicrophoneInput
        
        self.config = config
        
        # 创建SmartMicrophone实例
        self.microphone = SmartMicrophoneInput(
            sample_rate=config.get('sample_rate', 16000),
            chunk_size=config.get('chunk_size', 1024),
            silence_threshold=config.get('silence_threshold', 1.0),
            speech_threshold=config.get('speech_threshold', 100)
        )
        
        # 验证音频源
        if self.microphone.audio_source is None:
            raise RuntimeError("无可用的真实音频源")
        
        if self.microphone.audio_source == "mock":
            raise RuntimeError("禁止使用模拟音频源")
    
    async def start_recording(self) -> None:
        """开始录音"""
        await self.microphone.start_recording()
    
    async def stop_recording(self) -> None:
        """停止录音"""
        await self.microphone.stop_recording()
    
    async def get_audio_event(self) -> Optional[Tuple[str, Optional[bytes]]]:
        """获取音频事件"""
        return await self.microphone.get_audio_event()
    
    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.microphone.get_stats()
    
    def set_event_callbacks(self, 
                          speech_start: Optional[Callable] = None,
                          speech_end: Optional[Callable] = None,
                          silence_end: Optional[Callable] = None) -> None:
        """设置事件回调"""
        self.microphone.set_event_callbacks(
            speech_start=speech_start,
            speech_end=speech_end,
            silence_end=silence_end
        )