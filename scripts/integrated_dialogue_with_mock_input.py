#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
集成对话系统 - 模拟音频输入版本
测试GeminiAgent响应处理和语音输出集成
不依赖真实麦克风输入，使用模拟语音命令触发对话流程
"""

import sys
import os
import asyncio
import logging
import threading
import time
from typing import Optional, Dict, Any

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.speech import SpeechSystem, SentenceBuffer
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from intelligence.gemini_agent import RobotCommand
from utils.config import load_config, setup_logging
from utils.state import WorldState


class MockGeminiAgent:
    """
    模拟GeminiAgent - 用于测试语音输出集成
    模拟真实Agent的响应模式
    """
    
    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry
        self.logger = logging.getLogger(__name__)
        self.command_callback = None
        
        # 模拟对话场景（更丰富的响应）
        self.dialogue_scenarios = [
            {
                "user_speech": "你好",
                "agent_response": "您好！欢迎来到智能零售店。我是您的专属购物助手，可以为您扫描货架商品、推荐商品、抓取商品或帮您结账。请告诉我您需要什么帮助？",
                "action": "speak"
            },
            {
                "user_speech": "请扫描货架上的商品",
                "agent_response": "好的，我来为您扫描货架上的所有商品。",
                "action": "scan_inventory",
                "tool_call": True
            },
            {
                "user_speech": "我需要牙膏",
                "agent_response": "明白了，我来为您抓取牙膏。",
                "action": "grab_item_by_name",
                "tool_call": True,
                "parameters": {"item_name": "牙膏"}
            },
            {
                "user_speech": "雀巢咖啡右边的是什么商品",
                "agent_response": "我来帮您查看雀巢咖啡右边的商品并为您抓取。",
                "action": "grab_item_by_position",
                "tool_call": True,
                "parameters": {"reference_item": "雀巢咖啡", "direction": "右边"}
            },
            {
                "user_speech": "推荐一些商品给我",
                "agent_response": "基于您的购物历史，我推荐几样商品给您。",
                "action": "recommend_items",
                "tool_call": True
            },
            {
                "user_speech": "帮我结账",
                "agent_response": "好的，我来为您计算总价并处理结账。",
                "action": "calculate_checkout",
                "tool_call": True
            },
            {
                "user_speech": "谢谢你",
                "agent_response": "不客气！很高兴为您服务。如果您还需要其他帮助，请随时告诉我。祝您购物愉快！",
                "action": "speak"
            }
        ]
    
    async def simulate_voice_interaction(self, command_callback):
        """模拟完整的语音交互流程"""
        self.command_callback = command_callback
        self.logger.info("🎭 开始模拟语音交互流程")
        
        for i, scenario in enumerate(self.dialogue_scenarios):
            self.logger.info(f"[交互 {i+1}/7] 模拟用户语音: '{scenario['user_speech']}'")
            
            # 等待模拟用户思考和说话时间
            await asyncio.sleep(2)
            
            # 处理Agent响应
            if scenario.get("tool_call"):
                await self._handle_tool_call_response(scenario)
            else:
                await self._handle_text_response(scenario)
            
            # 等待语音播放完成
            await asyncio.sleep(3)
        
        self.logger.info("🎭 模拟语音交互流程完成")
    
    async def _handle_tool_call_response(self, scenario):
        """处理工具调用响应"""
        action = scenario["action"]
        parameters = scenario.get("parameters", {})
        agent_response = scenario["agent_response"]
        
        self.logger.info(f"🛠️ 执行工具调用: {action}")
        
        try:
            # 先发送Agent的响应
            speak_command = RobotCommand(
                action="speak",
                parameters={"text": agent_response},
                response_text=agent_response,
                confidence=1.0
            )
            
            if self.command_callback:
                self.command_callback(speak_command)
            
            # 等待一下再执行工具
            await asyncio.sleep(1)
            
            # 执行工具函数
            result = await self.tool_registry.execute_tool(action, parameters)
            
            # 创建工具执行结果命令
            tool_command = RobotCommand(
                action=action,
                parameters=parameters,
                response_text=result.get("message", "操作完成"),
                confidence=1.0 if result.get("success") else 0.5
            )
            
            # 发送工具执行结果
            if self.command_callback:
                self.command_callback(tool_command)
                
        except Exception as e:
            self.logger.error(f"工具调用失败: {e}")
            # 发送错误响应
            error_command = RobotCommand(
                action="speak",
                parameters={"text": f"抱歉，执行{action}时出现错误"},
                response_text=f"抱歉，执行{action}时出现错误",
                confidence=0.0
            )
            if self.command_callback:
                self.command_callback(error_command)
    
    async def _handle_text_response(self, scenario):
        """处理文本响应"""
        response_text = scenario["agent_response"]
        
        command = RobotCommand(
            action="speak",
            parameters={"text": response_text},
            response_text=response_text,
            confidence=1.0
        )
        
        if self.command_callback:
            self.command_callback(command)


class IntegratedDialogueWithMockInput:
    """
    集成对话系统 - 模拟音频输入版本
    测试语音输出和工具调用的完整流程
    """
    
    def __init__(self, config_path: str = "config.ini"):
        self.config = load_config(config_path)
        self.logger = logging.getLogger(__name__)
        
        # 核心组件
        self.world_state = WorldState()
        self.speech_system = SpeechSystem(self.config.speech)
        self.sentence_buffer = SentenceBuffer()
        self.robot_tools = MockRobotTools(self.world_state, self.config)
        self.tool_registry = ToolRegistry(self.robot_tools)
        
        # 模拟Agent
        self.mock_agent = MockGeminiAgent(self.tool_registry)
        
        # 语音输出消费者（基于成功模式）
        self.speech_consumer = VoiceOutputConsumer(self.sentence_buffer, self.speech_system)
        
        # 状态管理
        self.stop_event = threading.Event()
        self.is_running = False
        
        # 统计信息
        self.dialogue_count = 0
        self.start_time = None
        
        # 初始化世界状态
        self.world_state.initialize_world_map(mock_data=True)
        
        self.logger.info("集成对话系统（模拟输入版）初始化完成")
    
    async def start_dialogue_simulation(self):
        """启动对话模拟"""
        if self.is_running:
            self.logger.warning("对话模拟已在运行")
            return
        
        self.is_running = True
        self.start_time = time.time()
        
        self.logger.info("=================================================")
        self.logger.info("启动集成对话系统（模拟音频输入版）")
        self.logger.info("=================================================")
        
        try:
            # 启动语音输出消费者线程
            self.logger.info("启动语音输出消费者...")
            consumer_thread = threading.Thread(
                target=self.speech_consumer.start_consuming,
                args=(self.stop_event,),
                name="VoiceOutputConsumerThread"
            )
            consumer_thread.daemon = True
            consumer_thread.start()
            
            # 启动模拟语音交互
            self.logger.info("启动模拟语音交互...")
            self.logger.info("🎤 模拟多轮语音对话流程...")
            
            # 开始模拟对话
            await self.mock_agent.simulate_voice_interaction(self._handle_agent_response)
            
        except KeyboardInterrupt:
            self.logger.info("\n🛑 用户请求停止对话...")
        except Exception as e:
            self.logger.error(f"对话模拟错误: {e}")
            raise
        finally:
            await self.stop_dialogue_simulation()
    
    def _handle_agent_response(self, command: RobotCommand):
        """
        处理Agent响应
        将响应文本加入语音输出队列
        """
        try:
            self.dialogue_count += 1
            self.logger.info(f"[对话 #{self.dialogue_count}] 收到Agent响应: {command.action}")
            
            # 将响应文本加入语音输出队列
            if command.response_text:
                self._queue_speech_output(command.response_text)
            
            # 记录工具调用
            if command.action != "speak":
                self.logger.info(f"🛠️ 工具调用: {command.action} - {command.parameters}")
        
        except Exception as e:
            self.logger.error(f"处理Agent响应时出错: {e}")
    
    def _queue_speech_output(self, text: str):
        """将文本加入语音输出队列"""
        try:
            if text and text.strip():
                self.logger.info(f"📢 语音输出队列: {text[:50]}...")
                
                # 确保文本有正确的句号结尾以便正确分割
                text_with_punctuation = text.strip()
                if not text_with_punctuation.endswith(('。', '！', '？', '……')):
                    text_with_punctuation += '。'
                
                # 加入sentence buffer进行处理
                self.sentence_buffer.add_text(text_with_punctuation)
                
        except Exception as e:
            self.logger.error(f"语音输出队列错误: {e}")
    
    async def stop_dialogue_simulation(self):
        """停止对话模拟"""
        if not self.is_running:
            return
        
        self.logger.info("🛑 停止集成对话系统...")
        self.is_running = False
        self.stop_event.set()
        
        try:
            # 刷新sentence buffer确保所有句子都被处理
            self.sentence_buffer.flush()
            
            # 等待语音输出完成
            await asyncio.sleep(3)
            
            # 停止语音组件
            self.sentence_buffer.stop()
            self.speech_system.stop_speech_system()
            
            self.logger.info("✅ 集成对话系统已停止")
            
        except Exception as e:
            self.logger.error(f"停止对话系统时出错: {e}")
    
    def get_dialogue_stats(self) -> dict:
        """获取对话统计信息"""
        uptime = time.time() - self.start_time if self.start_time else 0
        
        return {
            "dialogue_count": self.dialogue_count,
            "is_running": self.is_running,
            "uptime_seconds": uptime,
            "speech_queue_size": self.sentence_buffer.sentence_queue.qsize(),
            "world_map_items": len(self.world_state.get_world_map().get("items", [])),
            "speech_consumer_stats": {
                "sentences_processed": self.speech_consumer.sentence_count,
                "is_running": self.speech_consumer.is_running
            }
        }


class VoiceOutputConsumer:
    """
    语音输出消费者
    复用complete_dialogue_system.py中成功的DialogueSpeechConsumer逻辑
    """
    
    def __init__(self, sentence_buffer: SentenceBuffer, speech_system: SpeechSystem):
        self.sentence_buffer = sentence_buffer
        self.speech_system = speech_system
        self.logger = logging.getLogger(__name__)
        self.sentence_count = 0
        self.is_running = False
    
    def start_consuming(self, stop_event: threading.Event):
        """启动语音消费者线程"""
        self.is_running = True
        self.logger.info("🗣️ [语音消费者] 语音播报消费者已启动...")
        
        while not stop_event.is_set() and self.is_running:
            # 非阻塞地从队列中获取一个完整的句子
            sentence = self.sentence_buffer.get_sentence(block=False)
            
            if sentence:
                self.sentence_count += 1
                self.logger.info(f"🗣️ [语音消费者] <- 获取到完整句子 #{self.sentence_count}: '{sentence}'")
                self.logger.info("   ...正在提交给语音合成系统...")
                
                # 使用与complete_dialogue_system.py完全相同的异步调用方式
                try:
                    import threading as thread_module
                    
                    def run_speech_task(text_to_speak):
                        """在新线程中运行语音合成任务"""
                        try:
                            if not text_to_speak or not text_to_speak.strip():
                                self.logger.info(f"   ...空文本，跳过播放。")
                                return
                                
                            # 为这个线程创建新的事件循环
                            loop = asyncio.new_event_loop()
                            asyncio.set_event_loop(loop)
                            
                            # 异步调用 speech_system.say
                            result = loop.run_until_complete(self.speech_system.say(text_to_speak))
                            
                            # 打印结果
                            if result.get("success"):
                                self.logger.info(f"   ...'{text_to_speak[:20]}...' 播放完成。")
                            else:
                                self.logger.info(f"   ...'{text_to_speak[:20]}...' 播放失败: {result.get('message', '未知错误')}")
                            
                            loop.close()
                        except Exception as e:
                            self.logger.error(f"   ...'{text_to_speak[:20] if text_to_speak else 'unknown'}...' 播放错误: {e}")
                    
                    # 在独立线程中启动语音任务（fire-and-forget）
                    speech_thread = thread_module.Thread(target=run_speech_task, args=(sentence,))
                    speech_thread.daemon = True
                    speech_thread.start()
                    
                    self.logger.info(f"   ...'{sentence[:20]}...' 已提交到播放队列。")
                    
                except Exception as e:
                    self.logger.error(f"   ...语音播报时出错: {e}")
            else:
                # 短暂等待再检查
                time.sleep(0.1)
        
        self.logger.info(f"🗣️ [语音消费者] 总共处理了 {self.sentence_count} 个句子")
        self.is_running = False


async def main():
    """主函数 - 集成对话系统（模拟输入版）"""
    print("🎤 集成对话系统 - 模拟音频输入版")
    print("=" * 60)
    print("模拟语音输入 → Agent处理 → 语音输出")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 创建集成对话系统
    dialogue_system = IntegratedDialogueWithMockInput()
    
    try:
        # 启动对话模拟
        await dialogue_system.start_dialogue_simulation()
        
    except Exception as e:
        print(f"❌ 系统错误: {e}")
        logging.error(f"系统错误: {e}", exc_info=True)
    finally:
        # 显示统计信息
        stats = dialogue_system.get_dialogue_stats()
        print(f"\n📊 对话统计:")
        print(f"  对话轮数: {stats['dialogue_count']}")
        print(f"  运行时间: {stats['uptime_seconds']:.1f}秒")
        print(f"  语音队列大小: {stats['speech_queue_size']}")
        print(f"  处理句子数: {stats['speech_consumer_stats']['sentences_processed']}")
        print(f"  世界地图商品数: {stats['world_map_items']}")
        
        # 停止系统
        await dialogue_system.stop_dialogue_simulation()
        
        print("\n🎉 集成对话系统测试完成！")


if __name__ == "__main__":
    asyncio.run(main())