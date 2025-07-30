#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini 2.5 Flash-Lite智能体
基于原生音频输入的智能零售机器人代理 - 使用新版google-genai API
"""

import asyncio
import logging
import time
import json
from typing import Callable, Dict, Any, Optional, List
from dataclasses import dataclass

# Google GenAI API (新版本)
from google import genai
from google.genai import types

from utils.config import AgentConfig, LLMConfig
from sensors.improved_vad import ImprovedVAD
from intelligence.speech_local import iFlyTekTTS


@dataclass
class RobotCommand:
    """机器人命令结构"""
    action: str
    parameters: Dict[str, Any]
    response_text: str
    confidence: float = 1.0


class FlashLiteAgent:
    """
    基于Gemini 2.5 Flash-Lite的智能体 (新API版本)
    
    特性：
    1. 原生音频输入支持（无需STT）
    2. 稳定的工具函数调用
    3. 批量音频处理（基于VAD事件）  
    4. 并行TTS播报和工具执行
    5. 完整的错误处理和恢复机制
    """
    
    def __init__(self, llm_config: LLMConfig, agent_config: AgentConfig, tool_registry=None):
        self.llm_config = llm_config
        self.agent_config = agent_config
        self.tool_registry = tool_registry
        
        # 初始化Gemini客户端 (新API)
        self.client = genai.Client(api_key=llm_config.gemini_api_key)
        self.model_name = "gemini-2.5-flash-lite"
        
        # 改进的VAD系统
        self.vad = ImprovedVAD(
            sample_rate=agent_config.audio_sample_rate,  # 16kHz
            chunk_size=agent_config.audio_chunk_size,    # 1024
            speech_timeout=2.0,  # 2秒静音后结束语音
            min_speech_duration=0.3,  # 最小0.3秒语音
            speech_threshold=100
        )
        
        # TTS系统（复用现有实现）
        self.tts_system = None  # 将在start时初始化
        
        # 会话状态
        self.is_running = False
        self.command_callback: Optional[Callable[[RobotCommand], None]] = None
        self.processing_utterance = False
        
        # 统计信息
        self.session_stats = {
            'start_time': None,
            'utterances_processed': 0,
            'tool_calls_made': 0,
            'tts_responses': 0,
            'errors': 0
        }
        
        # 日志
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.INFO)
    
    def _create_system_instruction(self) -> str:
        """创建系统指令"""
        return """你是参加中国机器人与人工智能大赛的智能零售机器人助手。你的任务是协助用户完成零售购物相关的各项任务。

核心功能：
1. 库存管理：扫描货架商品并播报位置信息  
2. 商品推荐：基于用户需求推荐合适商品
3. 智能抓取：根据商品名称、相对位置或语义分类抓取商品
4. 结账服务：计算购物车总价并生成清单

交互规则：
- 请始终用中文友好地回应用户
- 主动使用提供的工具函数来完成用户请求
- 对于抓取任务，优先询问用户具体需求以选择最合适的抓取方式
- 执行工具后，要向用户说明操作结果和下一步建议
- 保持专业但亲切的服务态度

货架布局（供参考）：
- 第一层（下层）：可口可乐、薯片、农夫山泉矿泉水、红牛
- 第二层（上层）：雀巢咖啡、苹果、奥利奥饼干、橘子

请准备好协助用户完成购物任务！"""
    
    def _create_tools(self) -> List[types.Tool]:
        """创建工具定义（新API格式）"""
        if not self.tool_registry:
            return []
        
        # 从现有工具注册器获取定义并转换为新API格式
        tools = []
        tool_defs = self.tool_registry.get_tool_definitions()
        
        function_declarations = []
        for tool_group in tool_defs:
            if "function_declarations" in tool_group:
                for func_def in tool_group["function_declarations"]:
                    # 转换为新API的FunctionDeclaration格式
                    function_declaration = types.FunctionDeclaration(
                        name=func_def["name"],
                        description=func_def["description"],
                        parameters=self._convert_parameters_schema(func_def["parameters"])
                    )
                    function_declarations.append(function_declaration)
        
        if function_declarations:
            tool = types.Tool(function_declarations=function_declarations)
            tools.append(tool)
        
        self.logger.info(f"已注册 {len(function_declarations)} 个工具函数")
        return tools
    
    def _convert_parameters_schema(self, old_params: Dict) -> types.Schema:
        """转换参数schema到新API格式"""
        try:
            properties = {}
            required = old_params.get("required", [])
            
            for prop_name, prop_def in old_params.get("properties", {}).items():
                prop_type = prop_def.get("type", "string")
                
                # 映射类型
                type_mapping = {
                    "string": types.Type.STRING,
                    "boolean": types.Type.BOOLEAN,
                    "integer": types.Type.INTEGER,
                    "number": types.Type.NUMBER,
                    "object": types.Type.OBJECT,
                    "array": types.Type.ARRAY
                }
                
                schema_type = type_mapping.get(prop_type, types.Type.STRING)
                
                prop_schema = types.Schema(
                    type=schema_type,
                    description=prop_def.get("description", "")
                )
                
                # 处理枚举值
                if "enum" in prop_def:
                    prop_schema.enum = prop_def["enum"]
                
                properties[prop_name] = prop_schema
            
            return types.Schema(
                type=types.Type.OBJECT,
                properties=properties,
                required=required
            )
            
        except Exception as e:
            self.logger.error(f"参数schema转换失败: {e}")
            return types.Schema(type=types.Type.OBJECT)
    
    def _create_generation_config(self) -> types.GenerateContentConfig:
        """创建生成配置"""
        return types.GenerateContentConfig(
            temperature=0.7,
            top_p=0.8,
            top_k=40,
            max_output_tokens=2048,
            system_instruction=self._create_system_instruction(),
            tools=self._create_tools()
        )
    
    def _setup_vad_callbacks(self):
        """设置VAD事件回调"""
        def on_speech_start():
            if not self.processing_utterance:
                self.logger.debug("🎤 检测到语音开始")
            
        def on_complete_utterance(audio_data: bytes, duration: float):
            if not self.processing_utterance:
                self.logger.debug(f"🤫 接收到完整语句: {duration:.2f}秒, {len(audio_data)/1024:.1f}KB")
                # 触发语音处理
                asyncio.create_task(self._process_complete_utterance(audio_data, duration))
        
        self.vad.set_callbacks(
            speech_start=on_speech_start,
            complete_utterance=on_complete_utterance
        )
    
    async def start_interactive_session(self, command_callback: Callable[[RobotCommand], None]):
        """
        启动交互式会话
        
        Args:
            command_callback: 接收机器人命令的回调函数
        """
        if self.is_running:
            self.logger.warning("会话已在运行中")
            return
        
        self.command_callback = command_callback
        self.is_running = True
        self.session_stats['start_time'] = time.time()
        
        try:
            # 初始化TTS系统
            if not self.tts_system:
                from utils.config import load_config
                config = load_config()
                self.tts_system = iFlyTekTTS(config.speech)
                self.logger.info("TTS系统初始化完成")
            
            # 设置VAD回调
            self._setup_vad_callbacks()
            
            # 启动VAD录制
            await self.vad.start_recording()
            self.logger.info("✅ Flash-Lite智能体会话启动成功")
            self.logger.info(f"🎯 使用模型: {self.model_name}")
            self.logger.info("🎤 音频录制已启动，支持原生音频理解")
            
            # 保持会话运行（VAD通过回调处理）
            await self._keep_session_alive()
            
        except Exception as e:
            self.logger.error(f"会话启动失败: {e}")
            raise
        finally:
            await self.stop_session()
    
    async def _keep_session_alive(self):
        """保持会话运行"""
        self.logger.info("开始监听完整语句...")
        
        while self.is_running:
            try:
                # 简单的心跳检查
                await asyncio.sleep(1)
                
            except Exception as e:
                self.logger.error(f"会话保持错误: {e}")
                self.session_stats['errors'] += 1
                await asyncio.sleep(0.1)
    
    async def _process_complete_utterance(self, audio_data: bytes, duration: float):
        """处理完整语句"""
        if self.processing_utterance:
            return
        
        self.processing_utterance = True
        processing_start = time.time()
        
        try:
            self.logger.info(f"🔄 处理语音片段: {duration:.2f}秒, {len(audio_data)/1024:.1f}KB")
            
            # 准备输入内容（新API格式）
            contents = [
                {
                    "mime_type": "audio/pcm",
                    "data": audio_data
                },
                "请理解用户的语音指令并提供相应的帮助。如果需要执行特定操作，请调用相应的工具函数。"
            ]
            
            # 调用Gemini 2.5 Flash-Lite (新API)
            response = await self._call_gemini_with_retry(contents)
            
            if response:
                # 并行处理：TTS播报 + 工具执行
                await asyncio.gather(
                    self._handle_text_response(response),
                    self._handle_function_calls(response),
                    return_exceptions=True
                )
                
                self.session_stats['utterances_processed'] += 1
                processing_time = time.time() - processing_start
                self.logger.info(f"✅ 语音处理完成，耗时: {processing_time:.2f}秒")
            
        except Exception as e:
            self.logger.error(f"语音处理失败: {e}")
            self.session_stats['errors'] += 1
            
            # 发送错误提示
            await self._speak_error_message("抱歉，我没有理解您的话，请您再说一遍。")
            
        finally:
            self.processing_utterance = False
    
    async def _call_gemini_with_retry(self, contents: List, max_retries: int = 3):
        """带重试的Gemini API调用（新API）"""
        config = self._create_generation_config()
        
        for attempt in range(max_retries):
            try:
                # 使用新API调用
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    self.client.models.generate_content,
                    self.model_name,
                    contents,
                    config
                )
                return response
                
            except Exception as e:
                self.logger.warning(f"Gemini API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 ** attempt)  # 指数退避
                else:
                    self.logger.error("Gemini API调用最终失败")
                    return None
    
    async def _handle_text_response(self, response):
        """处理文本响应"""
        try:
            if hasattr(response, 'text') and response.text:
                text = response.text.strip()
                if text:
                    self.logger.info(f"🗣️ AI响应: {text}")
                    await self._speak_text(text)
                    self.session_stats['tts_responses'] += 1
        except Exception as e:
            self.logger.error(f"文本响应处理失败: {e}")
    
    async def _handle_function_calls(self, response):
        """处理函数调用（新API格式）"""
        try:
            if hasattr(response, 'candidates') and response.candidates:
                for candidate in response.candidates:
                    if hasattr(candidate, 'content') and candidate.content:
                        if hasattr(candidate.content, 'parts') and candidate.content.parts:
                            for part in candidate.content.parts:
                                if hasattr(part, 'function_call') and part.function_call:
                                    await self._execute_function_call(part.function_call)
                                    self.session_stats['tool_calls_made'] += 1
        except Exception as e:
            self.logger.error(f"函数调用处理失败: {e}")
    
    async def _execute_function_call(self, function_call):
        """执行函数调用"""
        try:
            function_name = function_call.name
            function_args = {}
            
            # 转换参数格式
            if hasattr(function_call, 'args') and function_call.args:
                for key, value in function_call.args.items():
                    function_args[key] = value
            
            self.logger.info(f"🔧 执行工具: {function_name}({function_args})")
            
            if self.tool_registry:
                result = await self.tool_registry.execute_tool(function_name, function_args)
                
                if result.get('success'):
                    self.logger.info(f"✅ 工具执行成功: {result.get('message', '无消息')}")
                    
                    # 发送命令回调
                    if self.command_callback:
                        command = RobotCommand(
                            action=function_name,
                            parameters=function_args,
                            response_text=result.get('message', ''),
                            confidence=1.0
                        )
                        self.command_callback(command)
                else:
                    self.logger.warning(f"⚠️ 工具执行失败: {result.get('error', '未知错误')}")
                    await self._speak_error_message(f"执行操作时出现问题: {result.get('error', '未知错误')}")
            else:
                self.logger.warning("未配置工具注册器，无法执行函数调用")
                
        except Exception as e:
            self.logger.error(f"函数调用执行失败: {e}")
            await self._speak_error_message("执行操作时出现内部错误")
    
    async def _speak_text(self, text: str):
        """TTS语音播报"""
        try:
            if self.tts_system:
                # 使用临时文件进行TTS
                import tempfile
                import os
                
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp_file:
                    temp_path = tmp_file.name
                
                # 调用iFlyTek TTS
                success = await self.tts_system.synthesize_speech(text, temp_path)
                
                if success:
                    # 播放音频文件（简化版本，实际可能需要更复杂的音频播放）
                    self.logger.info(f"🔊 TTS合成成功: {text[:30]}...")
                    # 这里可以添加实际的音频播放逻辑
                    os.unlink(temp_path)  # 清理临时文件
                else:
                    self.logger.warning(f"TTS合成失败: {text}")
                    
            else:
                self.logger.warning("TTS系统未初始化")
        except Exception as e:
            self.logger.error(f"TTS播报失败: {e}")
    
    async def _speak_error_message(self, message: str):
        """播报错误信息"""
        await self._speak_text(message)
    
    async def stop_session(self):
        """停止会话"""
        if not self.is_running:
            return
        
        self.is_running = False
        self.logger.info("正在停止Flash-Lite智能体会话...")
        
        try:
            # 停止VAD录制
            await self.vad.stop_recording()
            
            # 显示会话统计
            self._print_session_stats()
            
        except Exception as e:
            self.logger.error(f"会话停止错误: {e}")
        
        self.logger.info("Flash-Lite智能体会话已停止")
    
    def _print_session_stats(self):
        """显示会话统计信息"""
        if self.session_stats['start_time']:
            duration = time.time() - self.session_stats['start_time']
            
            self.logger.info("📊 会话统计:")
            self.logger.info(f"   持续时间: {duration:.1f}秒")
            self.logger.info(f"   处理语句: {self.session_stats['utterances_processed']}")
            self.logger.info(f"   工具调用: {self.session_stats['tool_calls_made']}")
            self.logger.info(f"   TTS响应: {self.session_stats['tts_responses']}")
            self.logger.info(f"   错误次数: {self.session_stats['errors']}")
    
    def get_session_stats(self) -> Dict[str, Any]:
        """获取会话统计信息"""
        stats = self.session_stats.copy()
        if stats['start_time']:
            stats['duration'] = time.time() - stats['start_time']
        return stats