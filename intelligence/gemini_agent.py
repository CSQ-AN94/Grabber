#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简洁的Gemini Agent - 专注于text in/text out基本功能
使用新的google-genai库实现最简单可靠的API调用
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List

from google import genai
from google.genai import types

from utils.config import load_config

logger = logging.getLogger(__name__)


class GeminiAgent:
    """简洁的Gemini代理 - 纯文本输入输出"""
    
    def __init__(self, config_path: str = "config.yaml"):
        """初始化Gemini客户端"""
        self.client = None
        self.model_name = "gemini-2.5-flash-lite"
        self.enable_tools = False  # 控制是否启用工具调用
        
        try:
            # 加载配置
            config = load_config(config_path)
            api_key = config.llm.gemini_api_key
            
            if not api_key or api_key == "your_gemini_api_key":
                raise ValueError("请在config.yaml中设置有效的gemini_api_key")
            
            # 初始化客户端
            self.client = genai.Client(api_key=api_key)
            self.model_name = config.llm.model_name or self.model_name
            
            logger.info(f"Gemini客户端初始化成功，模型: {self.model_name}")
            
        except Exception as e:
            logger.error(f"Gemini客户端初始化失败: {e}")
            raise
    
    async def process_text(self, user_input: str) -> Dict[str, Any]:
        """处理文本输入，返回AI响应"""
        if self.enable_tools:
            return await self.process_text_with_tools(user_input)
        else:
            return await self.process_text_simple(user_input)
    
    async def process_text_simple(self, user_input: str) -> Dict[str, Any]:
        """处理文本输入，返回AI响应（不使用工具）"""
        
        if not self.client:
            return {
                "success": False,
                "error": "Gemini客户端未初始化",
                "text": ""
            }
        
        if not user_input.strip():
            return {
                "success": False,
                "error": "输入文本为空",
                "text": ""
            }
        
        try:
            # 准备请求内容
            contents = [user_input.strip()]
            
            # 创建配置
            config = types.GenerateContentConfig(
                temperature=0.8,
                max_output_tokens=1024,
                system_instruction="你是一个智能零售机器人助手。请用简洁、友好的方式回答用户问题。"
            )
            
            # 调用API
            logger.debug(f"发送请求到Gemini: {user_input[:50]}...")
            response = await self._call_gemini_api(contents, config)
            
            if response and response.text:
                result_text = response.text.strip()
                logger.info(f"收到Gemini响应: {result_text[:100]}...")
                
                return {
                    "success": True,
                    "text": result_text,
                    "model": self.model_name
                }
            else:
                return {
                    "success": False,
                    "error": "API返回空响应",
                    "text": ""
                }
                
        except Exception as e:
            logger.error(f"处理文本时发生错误: {e}")
            return {
                "success": False,
                "error": str(e),
                "text": ""
            }
    
    async def process_text_with_tools(self, user_input: str) -> Dict[str, Any]:
        """处理文本输入，支持工具调用"""
        
        if not self.client:
            return {
                "success": False,
                "error": "Gemini客户端未初始化",
                "text": ""
            }
        
        if not user_input.strip():
            return {
                "success": False,
                "error": "输入文本为空",
                "text": ""
            }
        
        try:
            # 准备消息 - 使用简单的字符串格式
            contents = [user_input.strip()]
            
            # 准备工具定义
            tools = self._create_tool_definitions()
            
            # 创建配置
            config = types.GenerateContentConfig(
                temperature=0.8,
                max_output_tokens=1024,
                system_instruction="你是一个智能零售机器人助手。当用户需要问候或查询状态时，请使用相应的工具函数。",
                tools=tools
            )
            
            # 调用API
            logger.debug(f"发送请求到Gemini (with tools): {user_input[:50]}...")
            response = await self._call_gemini_api(contents, config)
            
            # 处理响应和工具调用
            return await self._process_response_with_tools(response)
            
        except Exception as e:
            logger.error(f"处理文本时发生错误: {e}")
            return {
                "success": False,
                "error": str(e),
                "text": ""
            }
    
    async def _call_gemini_api(self, contents, config, max_retries: int = 3):
        """调用Gemini API，带重试机制"""
        
        for attempt in range(max_retries):
            try:
                # 使用executor包装同步API为异步
                response = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self.client.models.generate_content(
                        model=self.model_name,
                        contents=contents,
                        config=config
                    )
                )
                return response
                
            except Exception as e:
                logger.warning(f"API调用失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                
                if attempt < max_retries - 1:
                    # 指数退避
                    wait_time = 2 ** attempt
                    logger.info(f"等待 {wait_time} 秒后重试...")
                    await asyncio.sleep(wait_time)
                else:
                    # 最后一次尝试失败
                    raise e
    
    def is_ready(self) -> bool:
        """检查代理是否就绪"""
        return self.client is not None
    
    def enable_function_calling(self, enable: bool = True):
        """启用或禁用工具调用功能"""
        self.enable_tools = enable
        if enable:
            logger.info("已启用Function Calling功能")
        else:
            logger.info("已禁用Function Calling功能")
    
    # 工具函数定义
    async def say_hello(self, name: str = "用户") -> Dict[str, Any]:
        """简单的问候工具函数"""
        try:
            logger.info(f"执行问候工具: {name}")
            await asyncio.sleep(0.3)  # 模拟处理时间
            
            message = f"你好，{name}！我是智能零售机器人助手。"
            return {
                "success": True,
                "message": message,
                "data": {"greeted_name": name}
            }
        except Exception as e:
            return {
                "success": False,
                "message": "问候功能出现错误",
                "error": str(e)
            }
    
    async def get_robot_status(self) -> Dict[str, Any]:
        """获取机器人状态工具函数"""
        try:
            logger.info("查询机器人状态")
            await asyncio.sleep(0.5)  # 模拟状态检查
            
            status_info = {
                "status": "正常运行",
                "battery": "85%", 
                "position": "待命位置"
            }
            
            message = f"机器人状态：{status_info['status']}，电量{status_info['battery']}，位置：{status_info['position']}"
            return {
                "success": True,
                "message": message,
                "data": status_info
            }
        except Exception as e:
            return {
                "success": False,
                "message": "无法获取机器人状态",
                "error": str(e)
            }
    
    def get_available_tools(self) -> List[Dict[str, Any]]:
        """获取可用工具定义"""
        return [
            {
                "name": "say_hello",
                "description": "向用户问候",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "要问候的用户名称"
                        }
                    }
                }
            },
            {
                "name": "get_robot_status",
                "description": "获取机器人当前状态信息",
                "parameters": {
                    "type": "object",
                    "properties": {}
                }
            }
        ]
    
    async def execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """执行指定工具函数"""
        try:
            if tool_name == "say_hello":
                return await self.say_hello(**kwargs)
            elif tool_name == "get_robot_status":
                return await self.get_robot_status(**kwargs)
            else:
                return {
                    "success": False,
                    "message": f"未知工具: {tool_name}",
                    "error": f"不支持的工具函数: {tool_name}"
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"工具{tool_name}执行失败",
                "error": str(e)
            }
    
    def _create_tool_definitions(self) -> List[types.Tool]:
        """创建工具函数定义"""
        available_tools = self.get_available_tools()
        
        function_declarations = []
        for tool in available_tools:
            function_declaration = types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        param_name: types.Schema(
                            type=types.Type.STRING,
                            description=param_info.get("description", "")
                        )
                        for param_name, param_info in tool["parameters"]["properties"].items()
                    },
                    required=tool["parameters"].get("required", [])
                )
            )
            function_declarations.append(function_declaration)
        
        return [types.Tool(function_declarations=function_declarations)]
    
    async def _process_response_with_tools(self, response) -> Dict[str, Any]:
        """处理包含工具调用的响应"""
        try:
            if not response.candidates or len(response.candidates) == 0:
                return {
                    "success": False,
                    "error": "响应中没有候选结果",
                    "text": ""
                }
            
            candidate = response.candidates[0]
            text_parts = []
            tool_results = []
            
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    # 处理文本部分
                    if hasattr(part, 'text') and part.text:
                        text_parts.append(part.text)
                    
                    # 处理工具调用
                    if hasattr(part, 'function_call') and part.function_call:
                        function_call = part.function_call
                        tool_name = function_call.name
                        
                        # 提取参数
                        args = {}
                        if function_call.args:
                            args = dict(function_call.args)
                        
                        logger.info(f"执行工具函数: {tool_name} with args: {args}")
                        
                        # 执行工具函数
                        tool_result = await self.execute_tool(tool_name, **args)
                        tool_results.append(tool_result)
            
            # 组合最终文本
            final_text = ""
            if text_parts:
                final_text = " ".join(text_parts)
            
            # 添加工具执行结果
            if tool_results:
                for tool_result in tool_results:
                    if tool_result["success"]:
                        if final_text:
                            final_text += "\n\n"
                        final_text += f"✅ {tool_result['message']}"
                    else:
                        if final_text:
                            final_text += "\n\n"
                        final_text += f"❌ {tool_result['message']}"
            
            if not final_text:
                final_text = "操作已完成。"
            
            return {
                "success": True,
                "text": final_text.strip(),
                "model": self.model_name,
                "tool_calls": len(tool_results),
                "tool_results": tool_results
            }
            
        except Exception as e:
            logger.error(f"处理工具调用响应时发生错误: {e}")
            return {
                "success": False,
                "error": f"响应处理失败: {str(e)}",
                "text": ""
            }


async def main():
    """简单的测试函数"""
    print("=== Gemini Agent 简单测试 ===")
    
    try:
        # 初始化代理
        agent = GeminiAgent()
        
        if not agent.is_ready():
            print("❌ 代理初始化失败")
            return
        
        print("✅ 代理初始化成功")
        
        # 交互式测试
        while True:
            user_input = input("\n请输入文本 (输入 'quit' 退出): ").strip()
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                break
            
            if not user_input:
                continue
            
            print("🤖 处理中...")
            result = await agent.process_text(user_input)
            
            if result["success"]:
                print(f"✅ AI回复: {result['text']}")
            else:
                print(f"❌ 错误: {result['error']}")
    
    except KeyboardInterrupt:
        print("\n👋 用户中断，退出")
    except Exception as e:
        print(f"❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 设置日志级别
    logging.basicConfig(level=logging.INFO)
    
    # 运行测试
    asyncio.run(main())