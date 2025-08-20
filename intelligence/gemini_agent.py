#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini Agent
"""

import logging
from typing import Dict, Any

from google import genai
from google.genai import types
from utils.items_info import get_item_price
from intelligence import robot_tools

logger = logging.getLogger(__name__)

class GeminiAgent:
    """基于自动函数调用和chat连续调用的Gemini代理"""
    
    def __init__(self, enable_tools: bool = False, enable_voice: bool = False, use_real_hardware: bool = False):
        """初始化Gemini客户端"""
        try:
            self.client = genai.Client(api_key="AIzaSyDoRYk_kU61IIeEsCuAUaRft2iaeKXtoFE")
            self.model_name = "gemini-2.5-flash"
            self.enable_tools = enable_tools
            self.enable_voice = enable_voice
            self.use_real_hardware = use_real_hardware
            self.speech = None
            self.voice_manager = None
            
            # 初始化语音系统（如果启用）
            if self.enable_voice:
                from intelligence.speech import Speech
                from intelligence.voice_input import VoiceInputManager
                
                self.speech = Speech()
                self.voice_manager = VoiceInputManager(
                    on_speech_detected=self._on_voice_input,
                    on_agent_response_ready=self._on_agent_ready
                )
                logger.info("语音系统初始化成功")
            
            # 创建chat会话
            self._create_chat_session()
            
            logger.info(f"Gemini客户端初始化成功，模型: {self.model_name}，工具调用: {enable_tools}，语音模式: {enable_voice}")
            
        except Exception as e:
            logger.error(f"Gemini客户端初始化失败: {e}")
            raise
    
    def process_text(self, user_input: str) -> Dict[str, Any]:
        """处理文本输入，返回AI响应（使用多轮对话）"""
        if not self.chat or not user_input.strip():
            return {"success": False, "error": "无效输入或chat未初始化", "text": ""}
        
        try:
            # 根据是否启用工具构建不同的输入
            if self.enable_tools:
                # 工具模式：生成系统上下文
                context_text = self._get_system_context()
                enhanced_input = f"""用户说："{user_input}"

[系统信息]
{context_text}"""
            else:
                # 无工具模式：直接使用用户输入
                enhanced_input = user_input
            
            print(f"[处理文本] 输入: {enhanced_input}")
            
            # 发送消息并直接返回响应
            response = self.chat.send_message(enhanced_input)
            
            response_text = response.text.strip() if response.text else "响应为空"
            
            return {
                "success": True,
                "text": response_text
            }
            
        except Exception as e:
            logger.error(f"处理文本时发生错误: {e}")
            return {"success": False, "error": str(e), "text": ""}
    
    
    def _get_system_context(self) -> str:
        """
        生成系统上下文信息
        格式: 货架上有: 商品列表  购物车内有: 商品列表
        让大模型快速了解可用商品和购买历史
        """
        context_parts = []
        
        # 货架商品信息 - 从robot_tools获取动态available_items
        available_items = robot_tools.get_available_items()
        if available_items:
            shelf_items = []
            for item in available_items:
                price = get_item_price(item)
                shelf_items.append(f"{item}({price}元)")
            context_parts.append(f"有: {', '.join(shelf_items)}")
        else:
            context_parts.append("货架上有: 空，提示用户先允许你扫描货架来获知最新商品信息")
        
        # 购物车商品信息 - 从robot_tools获取动态购物车状态
        cart_items = robot_tools.get_shopping_cart()
        if cart_items:
            cart_list = []
            total_price = 0
            for item_name, price in cart_items:
                cart_list.append(f"{item_name}({price}元)")
                total_price += price
            context_parts.append(f"购物车内有: {', '.join(cart_list)}，总价: {total_price}元")
        else:
            context_parts.append("购物车内有: 空，总价: 0元")
        
        return "\n".join(context_parts)
    
    def _get_tools(self):
        """根据硬件模式选择工具集"""
        if self.use_real_hardware:
            return [robot_tools.scan_shelf, robot_tools.execute_grab]
        else:
            return [robot_tools.scan_shelf_mock, robot_tools.execute_grab_mock]
    
    def _get_system_instruction(self) -> str:
        """生成详细的系统指令"""
        base_instruction = """你是名为“小浦”的智能零售机器人。

## 核心工具函数

### 1. scan_shelf()
- 功能：实时扫描货架，以注重获取当前货架上所有可见商品信息

### 2. execute_grab(item_name: str) 
- 功能：基于商品名称智能抓取
- 内部流程：自动扫描 → 定位目标 → 执行抓取
- 参数：商品名称（如"苹果"、"可口可乐"）

## 核心行为原则

### 1. 智能推荐与决策

作为智能零售机器人，你拥有实时的货架内容和购物车内容作为系统信息，可以结合用户输入对商品的理解直接进行智能推荐和决策。

**推荐理由要求**：每次推荐商品时，请简要说明推荐理由，让用户理解为什么选择这个商品。

参考示例：
**货架为空**（引导用户）:
- "货架上没有商品，我可以扫描货架以获取最新商品信息，好么？" → scan_shelf() → 回复"已扫描货架，当前可见商品有：苹果、橘子、可乐等"

**明确商品需求**（直接执行）:
- 具体商品名: "我要买苹果" → 系统信息中"苹果"存在 → execute_grab("苹果") → 回复"已抓取苹果到购物车"
- 功能描述: "我想要解渴的饮料 → 根据系统信息推荐合适饮料，如农夫山泉矿泉水 → execute_grab("农夫山泉矿泉水") → 回复"已抓取农夫山泉矿泉水，帮您解渴"

**模糊需求**（引导用户决定）:
- 询问商品: "有什么好吃的？" → 系统信息中多个相关物品存在 → 回复"货架上有苹果、薯片等好吃的，您想要哪个？"
- 价格导向: "便宜的东西" → 系统信息中多个相关物品存在 → 回复"货架上有苹果、可乐等高性价比的商品，您想要哪个？"

### 2. 推荐行为准则

- 用户第一次使用前，提示用户先扫描货架
- 基于系统信息中货架内商品进行推荐，确保商品可用性
- 使用execute_grab(item_name)驱动机器人进行抓取，系统会自动定位
- 避免提及位置ID等技术细节，专注商品名称交互

### 3. 用户体验第一

始终保持友好自然的语气，避免使用过于技术化的术语。确保用户能够理解推荐和操作。
用户的每个输入都应该被视为潜在的购买意图。可以和用户进行有限的闲聊，但即使是闲聊，也要尝试引导用户表达具体需求。
你的文本输出会被转换为语音播报，所以请避免任何复杂的格式或符号，保持简洁明了。
"""

        if self.enable_tools:
            return base_instruction
        else:
            return "你是一个智能零售机器人助手。请用简洁、友好的方式回答用户问题。"
    
    def _create_chat_session(self):
        """创建chat会话"""
        try:
            # 创建chat配置
            chat_config = types.GenerateContentConfig(
                temperature=0.8,
                max_output_tokens=1024,
                system_instruction=self._get_system_instruction(),
                tools=self._get_tools() if self.enable_tools else None
            )
            
            # 创建chat会话
            self.chat = self.client.chats.create(
                model=self.model_name,
                config=chat_config
            )
            
            logger.info("Chat会话创建成功")
            
        except Exception as e:
            logger.error(f"Chat会话创建失败: {e}")
            raise
    
    def is_ready(self) -> bool:
        """检查Agent是否就绪"""
        return self.client is not None and self.chat is not None
    
    
    def _say_response(self, text: str):
        """语音播报响应（状态机会自动管理唤醒词检测）"""
        if not self.enable_voice or not self.speech or not text:
            return
        
        try:
            self.speech.say(text)
            print(f"[Agent] 播报完成: {text}")
            
        except Exception as e:
            logger.warning(f"语音播报失败: {e}")
        
        # 通知语音系统Agent响应完成，可以恢复唤醒词监听
        if self.voice_manager:
            self.voice_manager.agent_response_complete()
    
    def _on_voice_input(self, text: str):
        """语音输入回调处理 - 接收来自唤醒词系统的用户语音"""
        if text:
            print(f"\n[Agent] 收到用户语音: '{text}'")
            print("[Agent] AI思考中...")
            
            # 处理语音输入
            result = self.process_text(text)
            
            if result["success"]:
                response_text = result['text']
                print(f"[Agent] AI响应: {response_text}")
                # 语音播报并通知状态机系统
                self._say_response(response_text)
            else:
                print(f"[Agent] 处理失败: {result['error']}")
                # 处理失败也要恢复唤醒词监听
                if self.voice_manager:
                    self.voice_manager.agent_response_complete()
    
    def _on_agent_ready(self):
        """Agent响应完成回调 - 可选的额外处理"""
        print("[Agent] 响应处理完成，系统准备下次交互")
    
    def start_voice_system(self):
        """启动语音系统（唤醒词状态机）"""
        if self.voice_manager:
            self.voice_manager.start_system()
            print("[Agent] 语音系统已启动，说 '小浦' 激活对话")
        else:
            print("[Agent] 语音系统未启用")
    
    def stop_voice_system(self):
        """停止语音系统"""
        if self.voice_manager:
            self.voice_manager.stop_system()
            print("[Agent] 语音系统已停止")