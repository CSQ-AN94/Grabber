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
        """注册工具函数
        
        Args:
            name: 工具名称
            description: 工具描述
            func: 要执行的函数（必须是async函数）
            parameters: 参数定义字典
        
        示例:
            agent.register_tool(
                name="scan_shelf",
                description="扫描货架商品", 
                func=my_scan_function,
                parameters={
                    "type": "object",
                    "properties": {"announce": {"type": "boolean", "description": "是否播报"}}
                }
            )
        """
        tool_info = {
            "name": name,
            "description": description,
            "func": func,
            "parameters": parameters or {"type": "object", "properties": {}}
        }
        self.tools.append(tool_info)
        logger.info(f"已注册工具函数: {name}")
    
    def _get_system_instruction(self) -> str:
        """生成详细的系统指令"""
        base_instruction = """你是一个智能零售机器人助手，负责帮助顾客浏览商品、查询信息和完成购买。

## 核心行为原则

### 1. 完整任务执行原则
- 当用户提出需求时，要完成用户的完整意图，不要只做一半
- 如果用户说"我要买苹果"，你需要：先查询苹果位置 → 然后抓取苹果
- 如果用户说"我渴了，请给我水"，你需要：先查询饮料 → 从中选择水类商品 → 然后抓取合适的水

### 2. 工具调用依赖链
重要：很多任务需要多个工具按顺序调用！

**抓取商品的标准流程：**
1. 先用 query_world_state 确认商品位置和状态
2. 再用 grasp_and_drop 执行抓取（必须提供准确的position_id和item_name）
3. 永远不要跳过查询步骤！

**用户需求类型识别：**
- "我要买X" = 查询X的信息 + 抓取X
- "我渴了/我饿了" = 查询对应类别 + 推荐并抓取合适商品
- "给我X旁边的商品" = 查询相对位置 + 抓取目标商品
- "货架上有什么X？" = 仅查询，无需抓取

### 3. 相对位置处理策略
当用户说"X上面/下面/左边/右边的商品"时：
1. 先用 query_world_state(query_type="by_name", item_name="X") 找到参考商品
2. 再用 query_world_state(query_type="relative_position", reference_item="X", direction="上方/下方/左侧/右侧")
3. 然后根据结果决定是否抓取

方向词汇对应：
- "上面/上层" → "上方"
- "下面/下层" → "下方"  
- "左边/左侧" → "左侧"
- "右边/右侧" → "右侧"

### 4. 语义理解和推荐
- "我渴了" → 查询"饮料"类别，推荐水、果汁等
- "便宜的" → 从查询结果中选择价格最低的
- "好吃的零食" → 查询"零食"类别
- "我要结账" → 调用 get_checkout_summary

### 5. 文本输出规范
所有回复都要：
- 自然流畅，适合语音播报
- 包含具体的商品名称和价格
- 说明执行的操作结果
- 使用友好的语气

### 6. 错误处理
- 如果货架未扫描，先提醒用户扫描货架
- 如果商品不存在，主动推荐类似商品
- 如果操作失败，说明原因并提供替代方案

## 工具使用示例

用户："我要买苹果"
正确流程：
1. query_world_state(query_type="by_name", item_name="苹果")
2. 如果找到，使用返回的position_id调用 grasp_and_drop(position_id=X, item_name="苹果")

用户："给我可口可乐上面的商品"  
正确流程：
1. query_world_state(query_type="relative_position", reference_item="可口可乐", direction="上方")
2. 根据返回结果调用 grasp_and_drop

记住：始终要完成用户的完整需求！"""

        if self.enable_tools:
            return base_instruction
        else:
            return "你是一个智能零售机器人助手。请用简洁、友好的方式回答用户问题。"
    
    def _get_tool_definitions(self) -> List[types.Tool]:
        """获取工具定义"""
        if not self.tools:
            return []
        
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
        """处理Gemini响应（包括工具调用）"""
        try:
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