#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
重构后的Gemini Agent - 适配chat机制
使用新的google-genai库实现chat会话
"""

import logging
from typing import Dict, Any

from google import genai
from google.genai import types
from intelligence.robot_tools import get_robot_tools
logger = logging.getLogger(__name__)

class GeminiAgent:
    """基于chat的Gemini代理"""
    
    def __init__(self, enable_tools: bool = False, enable_voice: bool = False):
        """初始化Gemini客户端"""
        try:
            self.client = genai.Client(api_key="AIzaSyDoRYk_kU61IIeEsCuAUaRft2iaeKXtoFE")
            self.model_name = "gemini-2.5-flash-lite"
            self.enable_tools = enable_tools
            self.enable_voice = enable_voice
            self.speech = None
            self.vad_manager = None
            
            # 初始化语音系统（如果启用）
            if self.enable_voice:
                from intelligence.speech import Speech
                from intelligence.voice_input import VoiceInputManager
                
                self.speech = Speech()
                self.vad_manager = VoiceInputManager(on_speech_detected=self._on_voice_input)
                logger.info("语音系统初始化成功 (VAD+TTS)")
            
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
                # 工具模式：获取货架信息并构建增强提示
                from intelligence.world_state import get_world_state
                world_state = get_world_state()
                layout = world_state.query_full_layout()
                context_text = self._format_world_context(layout)
                enhanced_input = f"""用户说："{user_input}"

[系统信息：当前货架状况]
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
    
    
    def _format_world_context(self, world_context: dict) -> str:
        """格式化世界状态为文本描述（仅在工具模式下使用）"""
        if not world_context or not world_context.get("success", False):
            return "货架尚未扫描。无法进行任何推荐，请先提示用户扫描货架。"
        
        # 构建带价格的货架布局
        layout_items = world_context.get("layout", {})
        
        # 第一层
        layer1 = []
        for i, item in enumerate(world_context.get('layer1', [])):
            pos_id = i + 1
            if item == "空位":
                layer1.append(f"位置{pos_id}:空位")
            elif pos_id in layout_items:
                price = layout_items[pos_id]['price']
                layer1.append(f"位置{pos_id}:{item}({price}元)")
            else:
                layer1.append(f"位置{pos_id}:{item}")
        
        # 第二层
        layer2 = []
        for i, item in enumerate(world_context.get('layer2', [])):
            pos_id = i + 5
            if item == "空位":
                layer2.append(f"位置{pos_id}:空位")
            elif pos_id in layout_items:
                price = layout_items[pos_id]['price']
                layer2.append(f"位置{pos_id}:{item}({price}元)")
            else:
                layer2.append(f"位置{pos_id}:{item}")
        
        layout_text = "当前货架布局：\n"
        layout_text += f"第一层：{' | '.join(layer1)}\n"
        layout_text += f"第二层：{' | '.join(layer2)}"
        
        return layout_text.strip()
    
    def _get_system_instruction(self) -> str:
        """生成详细的系统指令"""
        base_instruction = """你是Grabber智能零售机器人。

## 可用工具函数

### 1. scan_shelf()
- 功能：扫描并初始化货架系统
- 用途：用户首次提出购买意向时，自动执行该函数来初始化货架商品信息

### 2. execute_grab(item_name: str, position_id: int)
- 功能：执行抓取指定商品的操作
- 用途：在明确用户需要的商品后驱动实体机器人系统从货架上抓取商品到购物车，并更新货架商品信息
- 参数：商品名称和位置ID

### 3. get_checkout_summary()
- 功能：查看购物车清单和总价
- 用途：用户提出结账时检查购物车内容和总价

## 核心行为原则

### 1. 智能推荐与决策

作为智能零售机器人，你拥有实时的货架布局，可以结合用户输入直接进行智能推荐和决策。

**推荐理由要求**：每次推荐商品时，请简要说明推荐理由，让用户理解为什么选择这个商品。

参考示例：
**高度明确意图**（直接执行）:
- 具体商品名: "我要买苹果" → "好的！苹果位置在第二层，富含维生素，健康营养" → execute_grab("苹果", 6)
- 明确位置+属性: "第一层最便宜的" → "第一层最便宜的是XX，只要X元，性价比很高" → execute_grab(最便宜商品, 位置)  
- 复合条件明确: "便宜的解渴饮料" → "推荐农夫山泉，X元，纯净解渴，价格实惠" → execute_grab(商品, 位置)

**中度明确意图**（推荐确认）:
- 功能需求: "我渴了" → "推荐农夫山泉矿泉水，纯净解渴，只要2.5元。是否为您抓取？"
- 类别需求: "给我个饮料" → "有可口可乐(经典口感，3.5元)和农夫山泉(纯净健康，2.5元)，您需要哪个？"

**低度明确意图**（信息收集）:
- 模糊表达: "我想要点什么" → "您想要什么样的商品？我们有解渴的饮料、香脆的零食、新鲜的水果，都能为您推荐合适的。"
- 缺乏条件: "便宜的东西" → "我们有很多实惠商品！橘子只要1.5元，农夫山泉2.5元，都很划算。您想要哪一类？"

### 2. 推荐分析准则

- 当进行商品推荐时，请严格结合提供的货架信息。
- 禁止推荐不在货架上的商品。
- 禁止推荐已经放到购物车的商品。
- 只要货架上存在商品，就可以进行推荐。货架上的空位是正常的，不影响推荐。
- 除了第一次扫描货架，其他时候不需要再执行scan_shelf()，除非用户明确要求。

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
                tools=get_robot_tools() if self.enable_tools else None
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
        """语音播报响应（期间暂停VAD监听）"""
        if not self.enable_voice or not self.speech or not text:
            return
        
        try:
            # 暂停VAD监听，避免检测到自己的语音
            if self.vad_manager:
                self.vad_manager.pause_listening()
            
            # 语音播报
            self.speech.say(text)
            
        except Exception as e:
            logger.warning(f"语音播报失败: {e}")
        finally:
            # 恢复VAD监听
            if self.vad_manager:
                self.vad_manager.resume_listening()
    
    def _on_voice_input(self, text: str):
        """VAD语音输入回调处理"""
        if text:
            print(f"\n[用户说] {text}")
            print("AI思考中...")
            
            # 处理语音输入
            result = self.process_text(text)
            
            if result["success"]:
                print(f"[AI回复] {result['text']}")
                # 语音播报（会自动暂停VAD监听）
                self._say_response(result['text'])
            else:
                print(f"[处理失败] {result['error']}")
    
    def start_vad_listening(self):
        """启动VAD监听"""
        if self.vad_manager:
            self.vad_manager.start_listening()
            print("VAD监听已启动，请说话...")
        else:
            print("VAD未启用")
    
    def stop_vad_listening(self):
        """停止VAD监听"""
        if self.vad_manager:
            self.vad_manager.stop_listening()
            print("VAD监听已停止")


def main():
    """交互测试"""
    print("=== Gemini Agent 智能对话系统 ===")
    
    # 选择工具模式
    mode = input("选择模式 - 1:文本对话模式 2:机器人工具模式 (默认1): ").strip()
    enable_tools = mode == "2"
    
    # 选择交互方式
    voice_mode = input("选择交互方式 - 1:文本交互 2:语音交互 (默认1): ").strip()
    enable_voice = voice_mode == "2"
    
    try:
        agent = GeminiAgent(enable_tools=enable_tools, enable_voice=enable_voice)
        
        if not agent.is_ready():
            print("代理初始化失败")
            return
        
        mode_text = '机器人工具模式' if enable_tools else '文本对话模式'
        voice_text = '语音交互' if enable_voice else '文本交互'
        print(f"代理初始化成功 ({mode_text} + {voice_text})")
        
        if enable_voice:
            # 语音交互模式
            print("\n语音交互模式已启用")
            print("- 系统将自动检测您的语音并智能回复")
            print("- 请对着麦克风说话，AI会自动回应")
            print("- 输入 'quit' 退出程序")
            
            # 启动VAD监听
            agent.start_vad_listening()
            
            try:
                while True:
                    user_input = input("\n输入 'quit' 退出: ").strip()
                    if user_input.lower() in ['quit', 'exit', 'q']:
                        break
            except KeyboardInterrupt:
                print("\n程序被用户中断")
            finally:
                agent.stop_vad_listening()
        else:
            # 文本交互模式
            print("\n文本交互模式")
            print("- 直接输入文本与AI对话")
            print("- 输入 'quit' 退出程序")
            
            while True:
                user_input = input("\n请输入文本: ").strip()
                if user_input.lower() in ['quit', 'exit', 'q']:
                    break
                
                if not user_input:
                    continue
                
                print("AI思考中...")
                
                # 处理文本输入
                result = agent.process_text(user_input)
                
                if result["success"]:
                    print(f"AI回复: {result['text']}")
                else:
                    print(f"处理失败: {result['error']}")
    
    except KeyboardInterrupt:
        print("\n用户中断，退出")
    except Exception as e:
        print(f"发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()