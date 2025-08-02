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
    
    def __init__(self, config_path: str = "config.yaml", enable_tools: bool = False):
        """初始化Gemini客户端"""
        self.client = None
        self.model_name = "gemini-2.5-flash-lite"
        self.enable_tools = enable_tools
        self.tools = []  # 存储注册的工具函数
        
        try:
            # 加载配置
            config = load_config(config_path)
            api_key = config.llm.gemini_api_key
            
            if not api_key or api_key == "your_gemini_api_key":
                raise ValueError("请在config.yaml中设置有效的gemini_api_key")
            
            # 初始化客户端
            self.client = genai.Client(api_key=api_key)
            self.model_name = config.llm.model_name or self.model_name
            
            logger.info(f"Gemini客户端初始化成功，模型: {self.model_name}，工具调用: {enable_tools}")
            
        except Exception as e:
            logger.error(f"Gemini客户端初始化失败: {e}")
            raise
    
    async def process_text(self, user_input: str) -> Dict[str, Any]:
        """处理文本输入，返回AI响应"""
        if not self.client or not user_input.strip():
            return {"success": False, "error": "无效输入", "text": ""}
        
        try:
            contents = [user_input.strip()]
            config = types.GenerateContentConfig(
                temperature=0.8,
                max_output_tokens=1024,
                system_instruction=self._get_system_instruction(),
                tools=self._get_tool_definitions() if self.enable_tools else None
            )
            
            response = await self._call_gemini_api(contents, config)
            return await self._process_response(response)
            
        except Exception as e:
            logger.error(f"处理文本时发生错误: {e}")
            return {"success": False, "error": str(e), "text": ""}
    
    def register_tool(self, name: str, description: str, func, parameters: Dict = None):
        """注册工具函数（兼容模式）"""
        tool_info = {
            "name": name,
            "description": description,
            "func": func,
            "parameters": parameters or {"type": "object", "properties": {}}
        }
        self.tools.append(tool_info)
        logger.info(f"已注册工具函数: {name}")
    
    def register_function(self, func):
        """
        注册Python函数用于自动调用（新的推荐方式）
        
        Args:
            func: Python函数，必须有类型提示和文档字符串
        
        示例:
            def buy_item(item_name: str) -> dict:
                '''购买指定商品'''
                return {"success": True, "message": f"购买了{item_name}"}
            
            agent.register_function(buy_item)
        """
        # 将函数包装为工具格式，但保存原始函数引用
        tool_info = {
            "name": func.__name__,
            "description": func.__doc__ or f"执行{func.__name__}函数",
            "func": func,
            "auto_function": True,  # 标记为自动函数
            "parameters": {"type": "object", "properties": {}}  # 简化参数处理
        }
        self.tools.append(tool_info)
        logger.info(f"已注册自动函数: {func.__name__}")
    
    def _get_system_instruction(self) -> str:
        """生成详细的系统指令"""
        base_instruction = """你是Grabber，一个智能零售机器人助手，负责帮助顾客浏览商品和完成购买。

## 核心工具架构（LLM驱动）

你只有3个核心工具函数可以使用：

### 1. scan_shelf()
- 功能：扫描并初始化货架系统
- 用途：用户首次使用时必须先扫描货架
- 返回：8个商品的布局信息

### 2. buy_product(user_query: str) 【核心智能函数】
- 功能：LLM驱动的通用智能购买函数
- 用途：处理ALL购买需求，无论简单还是复杂
- 支持的输入类型：
  * 具体商品名：我要买苹果、可口可乐、薯片
  * 需求描述：我渴了、我饿了、补充维生素、我困了
  * 价格导向：便宜的饮料、性价比高的零食
  * 复合条件：便宜的解渴饮料、提神又不贵的
  * 位置描述：第一层第二个、可口可乐旁边的
- 内部机制：自动分析用户意图 → 结合货架信息智能推荐 → 执行抓取操作

### 3. get_checkout_summary()
- 功能：查看购物车清单和总价
- 用途：结账时显示已购买的商品

## 核心行为原则

### 1. 统一使用buy_product()
- ❗ 重要：对于任何购买需求，都使用buy_product()函数
- 不要尝试"分解"用户需求，直接将用户的原始表达传给buy_product()
- buy_product()内部会自动处理复杂的语义理解和推荐逻辑

### 2. 任务执行流程
标准流程：
1. 用户首次使用：提醒scan_shelf()
2. 任何购买需求：直接调用buy_product(user_query)
3. 查看购物车：调用get_checkout_summary()

### 3. 用户需求示例
- "我要买苹果" → buy_product("我要买苹果")
- "我渴了" → buy_product("我渴了")
- "补充维生素" → buy_product("补充维生素")
- "便宜的解渴饮料" → buy_product("便宜的解渴饮料")
- "我困了，需要提神" → buy_product("我困了，需要提神")

### 4. 文本输出规范
- 自然流畅，适合语音播报
- 包含具体的商品名称和价格
- 说明执行的操作结果
- 使用友好的语气

### 5. 错误处理
- 货架未扫描：提醒用户先扫描货架
- 购买失败：说明原因，建议其他选择
- 购物车为空：提醒用户先选购商品

## 智能优势
- buy_product()使用LLM进行语义理解，比关键词匹配更智能
- 支持复杂的自然语言需求表达
- 能够综合考虑价格、功能、用户偏好进行推荐
- 自动完成从分析到抓取的完整流程

记住：相信LLM的智能，将用户的完整表达传递给buy_product()！"""

        if self.enable_tools:
            return base_instruction
        else:
            return "你是一个智能零售机器人助手。请用简洁、友好的方式回答用户问题。"
    
    def _get_tool_definitions(self):
        """获取工具定义，支持自动函数调用"""
        if not self.tools:
            return None
        
        # 检查是否有自动函数
        auto_functions = [tool["func"] for tool in self.tools if tool.get("auto_function", False)]
        
        if auto_functions:
            # 使用自动函数调用模式 - 直接返回Python函数列表
            logger.info(f"使用自动函数调用模式，函数数量: {len(auto_functions)}")
            return auto_functions
        
        # 兼容模式 - 使用手动函数声明
        function_declarations = []
        for tool in self.tools:
            function_declaration = types.FunctionDeclaration(
                name=tool["name"],
                description=tool["description"],
                parameters=types.Schema(
                    type=types.Type.OBJECT,
                    properties={
                        param_name: types.Schema(
                            type=types.Type.STRING if param_info.get("type") == "string" else
                                 types.Type.BOOLEAN if param_info.get("type") == "boolean" else types.Type.STRING,
                            description=param_info.get("description", "")
                        )
                        for param_name, param_info in tool["parameters"]["properties"].items()
                    },
                    required=tool["parameters"].get("required", [])
                )
            )
            function_declarations.append(function_declaration)
        
        return [types.Tool(function_declarations=function_declarations)]
    
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
    
    async def _execute_tool(self, tool_name: str, **kwargs) -> Dict[str, Any]:
        """执行指定工具函数"""
        for tool in self.tools:
            if tool["name"] == tool_name:
                logger.info(f"执行工具函数: {tool_name} with args: {kwargs}")
                return await tool["func"](**kwargs)
        
        return {
            "success": False,
            "message": f"未知工具: {tool_name}",
            "error": f"不支持的工具函数: {tool_name}"
        }
    
    
    async def _process_response(self, response) -> Dict[str, Any]:
        """处理Gemini响应（自动函数调用模式会自动处理函数调用）"""
        try:
            # 检查是否使用自动函数调用模式
            has_auto_functions = any(tool.get("auto_function", False) for tool in self.tools)
            
            if has_auto_functions:
                # 自动函数调用模式 - SDK已自动处理所有函数调用
                final_text = response.text if response.text else "操作已完成。"
                return {
                    "success": True,
                    "text": final_text.strip(),
                    "model": self.model_name,
                    "auto_function_calls": True
                }
            
            # 兼容模式 - 手动处理函数调用
            if not response.candidates or len(response.candidates) == 0:
                return {"success": False, "error": "响应中没有候选结果", "text": ""}
            
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
                        args = dict(function_call.args) if function_call.args else {}
                        
                        # 执行工具函数
                        tool_result = await self._execute_tool(tool_name, **args)
                        tool_results.append(tool_result)
            
            # 组合最终文本
            final_text = " ".join(text_parts) if text_parts else ""
            
            # 添加工具执行结果
            for tool_result in tool_results:
                if final_text:
                    final_text += "\n\n"
                status = "✅" if tool_result.get("success", False) else "❌"
                message = tool_result.get("message", "操作已完成")
                final_text += f"{status} {message}"
            
            if not final_text:
                final_text = "操作已完成。"
            
            return {
                "success": True,
                "text": final_text.strip(),
                "model": self.model_name,
                "tool_calls": len(tool_results)
            }
            
        except Exception as e:
            logger.error(f"处理响应时发生错误: {e}")
            return {"success": False, "error": f"响应处理失败: {str(e)}", "text": ""}


# 示例用法：
# 
# async def my_scan_function(announce: bool = True):
#     return {"success": True, "message": "扫描完成"}
#
# agent = GeminiAgent(enable_tools=True)
# agent.register_tool(
#     name="scan_shelf",
#     description="扫描货架商品",
#     func=my_scan_function,
#     parameters={
#         "type": "object",
#         "properties": {"announce": {"type": "boolean", "description": "是否播报"}}
#     }
# )

async def main():
    """简单的测试函数"""
    print("=== Gemini Agent 简单测试 ===")
    
    try:
        agent = GeminiAgent()
        
        if not agent.is_ready():
            print("❌ 代理初始化失败")
            return
        
        print("✅ 代理初始化成功")
        
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
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())