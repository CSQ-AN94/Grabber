#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
模拟多轮对话系统测试
不依赖真实麦克风输入，使用模拟语音命令测试整个对话流程
"""

import sys
import os
import asyncio
import logging
import threading
import time
from typing import Optional, List

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.gemini_agent import RobotCommand
from intelligence.speech import SpeechSystem, SentenceBuffer
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from utils.config import load_config, setup_logging
from utils.state import WorldState

class MockDialogueAgent:
    """
    模拟对话Agent - 不使用真实Gemini API
    用于测试语音输出和工具调用流程
    """
    
    def __init__(self, tool_registry: ToolRegistry):
        self.tool_registry = tool_registry
        self.logger = logging.getLogger(__name__)
        self.command_callback = None
        
        # 模拟对话序列
        self.dialogue_scenarios = [
            {
                "user_intent": "用户问候",
                "response": "您好！欢迎来到智能零售店。我可以为您扫描货架商品、推荐商品或帮您抓取商品。请告诉我您需要什么帮助？",
                "action": "speak"
            },
            {
                "user_intent": "请求扫描货架",
                "response": "好的，我来为您扫描货架上的所有商品。",
                "action": "scan_inventory",
                "tool_call": True
            },
            {
                "user_intent": "要求抓取牙膏",
                "response": "我来为您抓取牙膏。",
                "action": "grab_item_by_name",
                "tool_call": True,
                "parameters": {"item_name": "牙膏"}
            },
            {
                "user_intent": "要求抓取雀巢咖啡右边的商品",
                "response": "我来为您抓取雀巢咖啡右边的商品。",
                "action": "grab_item_by_position", 
                "tool_call": True,
                "parameters": {"reference_item": "雀巢咖啡", "direction": "右边"}
            },
            {
                "user_intent": "请求结账",
                "response": "好的，我来为您计算结账金额。",
                "action": "calculate_checkout",
                "tool_call": True
            },
            {
                "user_intent": "感谢",
                "response": "不客气！很高兴为您服务。如果您还需要其他帮助，请随时告诉我。",
                "action": "speak"
            }
        ]
        
        self.current_scenario = 0
    
    async def simulate_conversation(self, command_callback):
        """模拟完整对话流程"""
        self.command_callback = command_callback
        self.logger.info("🎭 开始模拟对话流程")
        
        for i, scenario in enumerate(self.dialogue_scenarios):
            self.logger.info(f"[对话 {i+1}] 用户意图: {scenario['user_intent']}")
            
            # 等待一下模拟用户思考时间
            await asyncio.sleep(2)
            
            # 处理工具调用
            if scenario.get("tool_call"):
                await self._handle_tool_call(scenario)
            else:
                # 直接文本响应
                await self._handle_text_response(scenario)
            
            # 等待语音播放完成
            await asyncio.sleep(3)
        
        self.logger.info("🎭 模拟对话流程完成")
    
    async def _handle_tool_call(self, scenario):
        """处理工具调用"""
        action = scenario["action"]
        parameters = scenario.get("parameters", {})
        
        self.logger.info(f"🛠️ 执行工具调用: {action}")
        
        try:
            # 执行工具函数
            result = await self.tool_registry.execute_tool(action, parameters)
            
            # 创建命令对象
            command = RobotCommand(
                action=action,
                parameters=parameters,
                response_text=result.get("message", "操作完成"),
                confidence=1.0 if result.get("success") else 0.5
            )
            
            # 发送给回调函数
            if self.command_callback:
                self.command_callback(command)
                
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
        response_text = scenario["response"]
        
        command = RobotCommand(
            action="speak",
            parameters={"text": response_text},
            response_text=response_text,
            confidence=1.0
        )
        
        if self.command_callback:
            self.command_callback(command)


class SimulatedDialogueSystem:
    """
    模拟多轮对话系统
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
        self.mock_agent = MockDialogueAgent(self.tool_registry)
        
        # 状态管理
        self.is_running = False
        self.dialogue_count = 0
        
        # 初始化世界状态
        self.world_state.initialize_world_map(mock_data=True)
        
        self.logger.info("模拟对话系统初始化完成")
    
    async def start_simulation(self):
        """启动对话模拟"""
        if self.is_running:
            self.logger.warning("模拟已在运行")
            return
        
        self.is_running = True
        self.logger.info("🎬 启动对话模拟")
        
        try:
            # 启动语音输出消费者
            self._start_speech_consumer()
            
            # 启动模拟对话
            await self.mock_agent.simulate_conversation(self._handle_agent_response)
            
        except Exception as e:
            self.logger.error(f"对话模拟失败: {e}")
            raise
        finally:
            await self.stop_simulation()
    
    def _handle_agent_response(self, command: RobotCommand):
        """处理Agent响应"""
        try:
            self.dialogue_count += 1
            self.logger.info(f"[对话 #{self.dialogue_count}] 收到响应: {command.action}")
            
            # 将响应文本加入语音输出队列
            if command.response_text:
                self._queue_speech_output(command.response_text)
                
        except Exception as e:
            self.logger.error(f"处理Agent响应时出错: {e}")
    
    def _queue_speech_output(self, text: str):
        """将文本加入语音输出队列"""
        try:
            if text and text.strip():
                self.logger.info(f"📢 语音输出队列: {text[:50]}...")
                # 将文本加入句子缓冲区，并添加句号确保被正确分割
                text_with_punctuation = text.strip()
                if not text_with_punctuation.endswith(('。', '！', '？', '……')):
                    text_with_punctuation += '。'
                self.sentence_buffer.add_text(text_with_punctuation)
                    
        except Exception as e:
            self.logger.error(f"语音输出队列错误: {e}")
    
    def _start_speech_consumer(self):
        """启动语音输出消费者线程"""
        try:
            self._speech_consumer_thread = threading.Thread(
                target=self._speech_consumer_worker,
                daemon=True
            )
            self._speech_consumer_thread.start()
            self.logger.info("语音输出消费者线程已启动")
        except Exception as e:
            self.logger.error(f"启动语音消费者线程失败: {e}")
    
    def _speech_consumer_worker(self):
        """语音输出消费者工作线程"""
        self.logger.info("🗣️ 语音输出消费者开始工作")
        sentence_count = 0
        
        while self.is_running:
            try:
                # 非阻塞获取完整句子
                sentence = self.sentence_buffer.get_sentence(block=False)
                
                if sentence:
                    sentence_count += 1
                    self.logger.info(f"🎵 [句子 #{sentence_count}] 语音输出: {sentence}")
                    
                    # 异步提交到语音系统
                    try:
                        # 创建新的事件循环
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        # 执行语音合成
                        result = loop.run_until_complete(self.speech_system.say(sentence))
                        
                        if result.get("success"):
                            self.logger.info(f"✅ [句子 #{sentence_count}] 语音播放成功")
                        else:
                            self.logger.warning(f"❌ [句子 #{sentence_count}] 语音播放失败: {result.get('message')}")
                        
                        loop.close()
                    except Exception as e:
                        self.logger.error(f"语音合成错误: {e}")
                else:
                    # 短暂等待
                    time.sleep(0.1)
                    
            except Exception as e:
                self.logger.error(f"语音消费者工作线程错误: {e}")
                time.sleep(0.5)
        
        self.logger.info(f"🗣️ 语音输出消费者工作线程结束 (共处理 {sentence_count} 个句子)")
    
    async def stop_simulation(self):
        """停止模拟"""
        if not self.is_running:
            return
        
        self.logger.info("🛑 停止对话模拟")
        self.is_running = False
        
        try:
            # 确保所有句子都被处理
            self.sentence_buffer.flush()
            await asyncio.sleep(2)  # 等待语音播放完成
            
            # 停止语音系统
            self.sentence_buffer.stop()
            self.speech_system.stop_speech_system()
            
            self.logger.info("✅ 对话模拟已停止")
            
        except Exception as e:
            self.logger.error(f"停止对话模拟时出错: {e}")
    
    def get_simulation_stats(self) -> dict:
        """获取模拟统计信息"""
        return {
            "dialogue_count": self.dialogue_count,
            "is_running": self.is_running,
            "speech_queue_size": self.sentence_buffer.sentence_queue.qsize(),
            "world_map_items": len(self.world_state.get_world_map().get("items", [])),
        }


async def main():
    """主函数 - 模拟多轮对话系统测试"""
    print("🎭 模拟多轮连续对话系统测试")
    print("=" * 60)
    
    # 设置日志
    setup_logging("DEBUG")
    
    print("\n🎯 启动模拟对话系统...")
    
    # 创建对话系统
    dialogue_system = SimulatedDialogueSystem()
    
    try:
        # 启动对话模拟
        await dialogue_system.start_simulation()
        
    except KeyboardInterrupt:
        print("\n🛑 用户中断模拟...")
    except Exception as e:
        print(f"❌ 系统错误: {e}")
        logging.error(f"系统错误: {e}", exc_info=True)
    finally:
        # 显示统计信息
        stats = dialogue_system.get_simulation_stats()
        print(f"\n📊 模拟统计:")
        print(f"  对话轮数: {stats['dialogue_count']}")
        print(f"  语音队列大小: {stats['speech_queue_size']}")
        print(f"  世界地图商品数: {stats['world_map_items']}")
        
        # 停止模拟
        await dialogue_system.stop_simulation()
        
        print("\n🎉 模拟对话系统测试完成！")


if __name__ == "__main__":
    asyncio.run(main())