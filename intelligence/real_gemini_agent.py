#!/usr/bin/env python3
"""
真实GeminiAgent - 基于真实麦克风的语音交互代理
严格遵循：真实硬件优先、生产代码纯净、组件解耦、错误处理泛化
"""

import asyncio
import logging
import time
from typing import Optional, Callable, Dict, Any
from dataclasses import dataclass
import json

import google.genai as genai


@dataclass
class VoiceCommand:
    """语音命令数据结构"""
    action: str
    parameters: Dict[str, Any]
    response_text: str
    confidence: float
    timestamp: float


class RealGeminiAgent:
    """
    真实GeminiAgent - 基于真实麦克风的语音交互代理
    
    核心原则：
    1. 只使用真实麦克风，禁止任何模拟数据
    2. 完全独立的组件，不依赖具体的麦克风实现
    3. 所有配置通过配置文件传入
    4. 统一的错误处理和降级策略
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        初始化真实GeminiAgent
        
        Args:
            config: 配置字典，包含API密钥、模型设置等
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # 状态管理
        self.is_active = False
        self.session_id = None
        self.command_handler: Optional[Callable] = None
        
        # 音频接口 - 抽象化，不依赖具体实现
        self.audio_input = None
        
        # 统计信息
        self.commands_processed = 0
        self.start_time = None
        
        # 初始化Gemini API
        self._initialize_gemini()
        
        self.logger.info("真实GeminiAgent初始化完成")
    
    def _initialize_gemini(self):
        """初始化Gemini API"""
        try:
            api_key = self.config.get('api_key')
            if not api_key:
                raise ValueError("缺少Gemini API密钥")
            
            # 使用google-genai库
            self.client = genai.Client(api_key=api_key)
            
            model_name = self.config.get('model_name', 'gemini-2.0-flash-exp')
            self.model_name = model_name
            
            self.logger.info(f"Gemini API初始化成功: {model_name}")
            
        except Exception as e:
            self.logger.error(f"Gemini API初始化失败: {e}")
            raise
    
    def set_audio_input(self, audio_input):
        """
        设置音频输入接口
        
        Args:
            audio_input: 实现了音频输入接口的对象
                        必须有以下方法：
                        - start_recording() -> None
                        - stop_recording() -> None
                        - get_audio_event() -> Optional[Tuple[str, bytes]]
                        - get_stats() -> Dict[str, Any]
        """
        self.audio_input = audio_input
        self.logger.info("音频输入接口已设置")
    
    def set_command_handler(self, handler: Callable[[VoiceCommand], None]):
        """
        设置命令处理器
        
        Args:
            handler: 处理语音命令的回调函数
        """
        self.command_handler = handler
        self.logger.info("命令处理器已设置")
    
    async def start_session(self) -> str:
        """
        启动语音交互会话
        
        Returns:
            会话ID
            
        Raises:
            RuntimeError: 如果音频输入未设置或命令处理器未设置
        """
        if not self.audio_input:
            raise RuntimeError("音频输入接口未设置")
        
        if not self.command_handler:
            raise RuntimeError("命令处理器未设置")
        
        if self.is_active:
            self.logger.warning("会话已经在运行中")
            return self.session_id
        
        try:
            # 检查音频输入是否可用
            if not self._validate_audio_input():
                raise RuntimeError("音频输入设备不可用")
            
            # 启动音频录制
            await self.audio_input.start_recording()
            
            # 启动会话
            self.session_id = f"session_{int(time.time())}"
            self.is_active = True
            self.start_time = time.time()
            
            self.logger.info(f"语音交互会话已启动: {self.session_id}")
            
            # 启动音频处理循环
            asyncio.create_task(self._audio_processing_loop())
            
            return self.session_id
            
        except Exception as e:
            self.logger.error(f"启动会话失败: {e}")
            self.is_active = False
            raise
    
    async def stop_session(self):
        """停止语音交互会话"""
        if not self.is_active:
            return
        
        self.is_active = False
        
        try:
            # 停止音频录制
            if self.audio_input:
                await self.audio_input.stop_recording()
            
            # 记录会话统计
            if self.start_time:
                duration = time.time() - self.start_time
                self.logger.info(f"会话结束 - 时长: {duration:.1f}秒, 处理命令: {self.commands_processed}")
            
            self.logger.info(f"语音交互会话已停止: {self.session_id}")
            
        except Exception as e:
            self.logger.error(f"停止会话时出错: {e}")
        
        finally:
            self.session_id = None
            self.start_time = None
    
    def _validate_audio_input(self) -> bool:
        """验证音频输入设备是否可用"""
        try:
            # 检查音频输入接口是否具有必要的方法
            required_methods = ['start_recording', 'stop_recording', 'get_audio_event', 'get_stats']
            for method in required_methods:
                if not hasattr(self.audio_input, method):
                    self.logger.error(f"音频输入缺少必要方法: {method}")
                    return False
            
            # 检查音频输入状态
            stats = self.audio_input.get_stats()
            if not stats.get('is_running', False):
                self.logger.debug("音频输入未运行，准备启动")
            
            return True
            
        except Exception as e:
            self.logger.error(f"音频输入验证失败: {e}")
            return False
    
    async def _audio_processing_loop(self):
        """音频处理主循环"""
        self.logger.info("音频处理循环已启动")
        
        try:
            while self.is_active:
                try:
                    # 获取音频事件
                    event = await self.audio_input.get_audio_event()
                    
                    if event:
                        event_type, data = event
                        
                        if event_type == 'audio':
                            # 处理音频数据
                            await self._process_audio_data(data)
                        
                        elif event_type == 'silence_end':
                            # 处理静音结束事件
                            await self._process_silence_end()
                    
                    # 避免CPU过度使用
                    await asyncio.sleep(0.01)
                    
                except Exception as e:
                    self.logger.error(f"音频处理循环错误: {e}")
                    # 不中断循环，继续处理
                    await asyncio.sleep(0.1)
        
        except Exception as e:
            self.logger.error(f"音频处理循环致命错误: {e}")
        
        finally:
            self.logger.info("音频处理循环已停止")
    
    async def _process_audio_data(self, audio_data: bytes):
        """
        处理音频数据
        
        Args:
            audio_data: 音频数据字节
        """
        try:
            # 如果有活跃的Live会话，发送音频数据
            if hasattr(self, 'live_session') and self.live_session:
                await self._send_audio_to_live_api(audio_data)
            else:
                self.logger.debug(f"接收到音频数据: {len(audio_data)} 字节 (无Live会话)")
            
        except Exception as e:
            self.logger.error(f"音频数据处理错误: {e}")
    
    async def _process_silence_end(self):
        """处理静音结束事件"""
        try:
            self.logger.debug("检测到静音结束")
            # 静音结束时可以发送特殊标记或者等待响应
            
        except Exception as e:
            self.logger.error(f"静音结束处理错误: {e}")
    
    async def _start_live_api_session(self):
        """启动Gemini Live API会话"""
        try:
            self.logger.info("启动Gemini Live API会话...")
            
            # 创建Live API连接配置
            live_config = genai.types.LiveConnectConfig(
                model=self.model_name,
                # 添加系统指令
                system_instruction="你是一个智能零售机器人助手。请用简洁、友好的语言回应用户。当用户需要商品信息、位置查询或购买帮助时，你可以调用相应的工具函数。"
            )
            
            # 建立Live API连接
            self.live_session = await self.client.aio.live.connect(config=live_config)
            
            self.logger.info("Gemini Live API会话已建立")
            
            # 启动响应处理循环
            asyncio.create_task(self._live_response_loop())
            
            return True
            
        except Exception as e:
            self.logger.error(f"启动Live API会话失败: {e}")
            self.live_session = None
            return False
    
    async def _send_audio_to_live_api(self, audio_data: bytes):
        """发送音频数据到Live API"""
        try:
            if not self.live_session:
                return
            
            # 创建实时音频输入
            audio_input = genai.types.LiveClientRealtimeInput(
                media_chunks=[audio_data]
            )
            
            # 发送到Live API
            await self.live_session.send_realtime_input(audio_input)
            
        except Exception as e:
            self.logger.error(f"发送音频到Live API失败: {e}")
    
    async def _live_response_loop(self):
        """Live API响应处理循环"""
        try:
            self.logger.info("Live API响应循环已启动")
            
            async for message in self.live_session.receive():
                try:
                    await self._handle_live_response(message)
                except Exception as e:
                    self.logger.error(f"处理Live响应错误: {e}")
                    
        except Exception as e:
            self.logger.error(f"Live响应循环错误: {e}")
        finally:
            self.logger.info("Live API响应循环已停止")
    
    async def _handle_live_response(self, message):
        """处理Live API响应"""
        try:
            if hasattr(message, 'server_content') and message.server_content:
                content = message.server_content
                
                # 处理文本响应
                if hasattr(content, 'model_turn') and content.model_turn:
                    parts = content.model_turn.parts
                    for part in parts:
                        if hasattr(part, 'text') and part.text:
                            # 创建语音命令
                            command = VoiceCommand(
                                action="speak",
                                parameters={},
                                response_text=part.text,
                                confidence=1.0,
                                timestamp=time.time()
                            )
                            
                            # 调用命令处理器
                            if self.command_handler:
                                self.command_handler(command)
                                self.commands_processed += 1
                            
                            self.logger.info(f"收到Live API响应: {part.text[:50]}...")
                
                # 处理工具调用
                if hasattr(content, 'function_call') and content.function_call:
                    # TODO: 实现工具调用处理
                    self.logger.info("收到工具调用请求")
                    
        except Exception as e:
            self.logger.error(f"处理Live响应失败: {e}")
    
    async def _stop_live_api_session(self):
        """停止Live API会话"""
        try:
            if hasattr(self, 'live_session') and self.live_session:
                await self.live_session.close()
                self.live_session = None
                self.logger.info("Live API会话已关闭")
        except Exception as e:
            self.logger.error(f"关闭Live API会话错误: {e}")
    
    def get_session_stats(self) -> Dict[str, Any]:
        """
        获取会话统计信息
        
        Returns:
            统计信息字典
        """
        stats = {
            "session_id": self.session_id,
            "is_active": self.is_active,
            "commands_processed": self.commands_processed,
            "uptime_seconds": time.time() - self.start_time if self.start_time else 0,
        }
        
        # 如果有音频输入，添加音频统计
        if self.audio_input:
            try:
                audio_stats = self.audio_input.get_stats()
                stats.update({
                    "audio_source": audio_stats.get("audio_source"),
                    "audio_chunks": audio_stats.get("chunks_received", 0),
                    "speech_events": audio_stats.get("speech_events", 0),
                    "silence_events": audio_stats.get("silence_events", 0),
                })
            except Exception as e:
                self.logger.debug(f"获取音频统计失败: {e}")
        
        return stats
    
    def get_system_info(self) -> Dict[str, Any]:
        """
        获取系统信息
        
        Returns:
            系统信息字典
        """
        return {
            "agent_version": "1.0.0",
            "model_name": self.config.get('model_name', 'unknown'),
            "audio_input_available": self.audio_input is not None,
            "command_handler_available": self.command_handler is not None,
        }