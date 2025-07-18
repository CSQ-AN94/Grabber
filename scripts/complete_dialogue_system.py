#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
完整的多轮对话系统 - 大胆重构版本
基于test_sentence_buffer_pipeline.py的成功经验，完全重新设计
"""

import sys
import os
import asyncio
import logging
import threading
import time
import random
from typing import Optional, Dict, Any

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.speech import SpeechSystem, SentenceBuffer
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from utils.config import load_config, setup_logging
from utils.state import WorldState

class DialogueTextProducer:
    """
    对话文本生产者 - 模拟Agent响应
    基于成功的test_sentence_buffer_pipeline.py设计模式
    """
    
    def __init__(self, sentence_buffer: SentenceBuffer, tool_registry: ToolRegistry):
        self.sentence_buffer = sentence_buffer
        self.tool_registry = tool_registry
        self.logger = logging.getLogger(__name__)
        
        # 预定义对话场景
        self.dialogue_scenarios = [
            {
                "trigger": "启动",
                "fragments": [
                    "您好，", "我是您的智能", "零售助手。", "今天天气不错！", 
                    "请问有什么可以帮您的吗？", "我们店里有牙膏、", "雀巢咖啡、", 
                    "洗发水", "和可口可乐。您需要哪一个？"
                ]
            },
            {
                "trigger": "扫描货架",
                "tool_call": "scan_inventory",
                "fragments": [
                    "好的，", "正在为您", "扫描货架商品……"
                ]
            },
            {
                "trigger": "抓取牙膏",
                "tool_call": "grab_item_by_name",
                "tool_params": {"item_name": "牙膏"},
                "fragments": [
                    "好的，", "正在为您", "抓取牙膏……"
                ]
            },
            {
                "trigger": "抓取咖啡",
                "tool_call": "grab_item_by_name", 
                "tool_params": {"item_name": "雀巢咖啡"},
                "fragments": [
                    "好的，", "正在为您", "抓取雀巢咖啡……"
                ]
            },
            {
                "trigger": "结账",
                "tool_call": "calculate_checkout",
                "fragments": [
                    "好的，", "正在为您", "计算结账金额……"
                ]
            },
            {
                "trigger": "再见",
                "fragments": [
                    "感谢您的购买！", "祝您购物愉快。", "欢迎下次光临！"
                ]
            }
        ]
    
    async def simulate_dialogue_sequence(self, stop_event: threading.Event):
        """
        模拟完整对话序列
        使用与test_sentence_buffer_pipeline.py相同的生产者模式
        """
        self.logger.info("🤖 [对话生产者] 开始模拟对话序列...")
        
        for scenario_idx, scenario in enumerate(self.dialogue_scenarios):
            if stop_event.is_set():
                break
            
            self.logger.info(f"🤖 [对话生产者] 场景 {scenario_idx + 1}: {scenario['trigger']}")
            
            # 执行工具调用（如果有）
            if "tool_call" in scenario:
                await self._execute_tool_call(scenario)
            
            # 发送文本片段到sentence buffer
            await self._send_text_fragments(scenario["fragments"], stop_event)
            
            # 场景间等待
            await asyncio.sleep(random.uniform(2.0, 4.0))
        
        # 完成后刷新缓冲区
        self.sentence_buffer.flush()
        self.logger.info("🤖 [对话生产者] 所有对话片段已发送，模拟器关闭。")
    
    async def _execute_tool_call(self, scenario: Dict[str, Any]):
        """执行工具调用"""
        tool_name = scenario["tool_call"]
        tool_params = scenario.get("tool_params", {})
        
        try:
            self.logger.info(f"🛠️ [工具调用] 执行: {tool_name}")
            result = await self.tool_registry.execute_tool(tool_name, tool_params)
            
            if result.get("success"):
                # 将工具执行结果也加入对话流
                result_message = result.get("message", "操作完成")
                result_fragments = self._split_message_to_fragments(result_message)
                await self._send_text_fragments(result_fragments, threading.Event())
            else:
                self.logger.warning(f"🛠️ [工具调用] 失败: {result.get('message')}")
                
        except Exception as e:
            self.logger.error(f"🛠️ [工具调用] 错误: {e}")
    
    def _split_message_to_fragments(self, message: str) -> list:
        """将消息分割为片段（模拟流式响应）"""
        # 简单按逗号和句号分割
        import re
        parts = re.split(r'([，。！？])', message)
        fragments = []
        current = ""
        
        for part in parts:
            current += part
            if part in "，。！？" or len(current) > 10:
                if current.strip():
                    fragments.append(current.strip())
                current = ""
        
        if current.strip():
            fragments.append(current.strip())
        
        return fragments if fragments else [message]
    
    async def _send_text_fragments(self, fragments: list, stop_event: threading.Event):
        """发送文本片段到sentence buffer"""
        for fragment in fragments:
            if stop_event.is_set():
                break
            
            # 模拟网络延迟和不规则的文本到达时间
            await asyncio.sleep(random.uniform(0.3, 1.2))
            
            self.logger.info(f"🤖 [对话生产者] -> 发送片段: '{fragment}'")
            self.sentence_buffer.add_text(fragment)


class DialogueSpeechConsumer:
    """
    对话语音消费者 - 基于成功的test_sentence_buffer_pipeline.py模式
    """
    
    def __init__(self, sentence_buffer: SentenceBuffer, speech_system: SpeechSystem):
        self.sentence_buffer = sentence_buffer
        self.speech_system = speech_system
        self.logger = logging.getLogger(__name__)
        self.sentence_count = 0
        self.is_running = False
    
    def start_consuming(self, stop_event: threading.Event):
        """
        启动语音消费者线程
        完全复用test_sentence_buffer_pipeline.py的成功逻辑
        """
        self.is_running = True
        self.logger.info("🗣️ [语音消费者] 语音播报消费者已启动...")
        
        while not stop_event.is_set() and self.is_running:
            # 非阻塞地从队列中获取一个完整的句子
            sentence = self.sentence_buffer.get_sentence(block=False)
            
            if sentence:
                self.sentence_count += 1
                self.logger.info(f"🗣️ [语音消费者] <- 获取到完整句子 #{self.sentence_count}: '{sentence}'")
                self.logger.info("   ...正在提交给语音合成系统...")
                
                # 使用与test_sentence_buffer_pipeline.py完全相同的异步调用方式
                try:
                    # 创建新的事件循环来处理异步调用
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
                # 检查生产者是否还在运行
                producer_alive = False
                for t in threading.enumerate():
                    if "DialogueProducer" in t.name:
                        producer_alive = t.is_alive()
                        break
                
                # 如果生产者已停止且队列为空，退出
                if not producer_alive and self.sentence_buffer.sentence_queue.empty():
                    self.logger.info("🗣️ [语音消费者] 生产者已停止且队列为空，退出。")
                    break
                
                # 短暂等待再检查
                time.sleep(0.1)
        
        self.logger.info(f"🗣️ [语音消费者] 总共处理了 {self.sentence_count} 个句子")
        self.is_running = False


class CompleteDialogueSystem:
    """
    完整多轮对话系统 - 重构版本
    基于test_sentence_buffer_pipeline.py的成功架构
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
        
        # 对话组件
        self.dialogue_producer = DialogueTextProducer(self.sentence_buffer, self.tool_registry)
        self.speech_consumer = DialogueSpeechConsumer(self.sentence_buffer, self.speech_system)
        
        # 状态管理
        self.stop_event = threading.Event()
        
        # 初始化世界状态
        self.world_state.initialize_world_map(mock_data=True)
        
        self.logger.info("完整对话系统初始化完成")
    
    async def run_complete_dialogue(self):
        """
        运行完整的多轮对话
        使用与test_sentence_buffer_pipeline.py相同的线程模式
        """
        self.logger.info("==================================================")
        self.logger.info("开始多轮对话系统测试")
        self.logger.info("==================================================")
        
        try:
            # 创建并启动生产者和消费者线程
            self.logger.info("\n[1/2] 启动对话生产者和语音消费者线程...")
            
            # 生产者线程
            producer_thread = threading.Thread(
                target=self._run_producer_async,
                name="DialogueProducerThread"
            )
            
            # 消费者线程
            consumer_thread = threading.Thread(
                target=self.speech_consumer.start_consuming,
                args=(self.stop_event,),
                name="DialogueConsumerThread"
            )
            
            producer_thread.start()
            consumer_thread.start()
            self.logger.info("✅ 线程已启动。")
            
            # 等待对话完成
            self.logger.info("\n[2/2] 对话正在进行... 请注意听取语音输出。")
            self.logger.info("      (可以 Ctrl+C 提前终止对话)")
            
            # 等待生产者线程结束
            producer_thread.join()
            
            # 再给消费者一些时间来处理队列中剩余的句子
            time.sleep(5)
            
            # 等待消费者线程结束
            consumer_thread.join(timeout=10)
            
        except KeyboardInterrupt:
            self.logger.info("\n🚫 用户请求中断对话...")
            self.stop_event.set()
        finally:
            # 确保所有资源都被正确关闭
            self.logger.info("\n[清理] 正在停止所有组件...")
            self.stop_event.set()
            self.sentence_buffer.stop()
            self.speech_system.stop_speech_system()
            
            self.logger.info("==================================================")
            self.logger.info("多轮对话系统测试结束。")
            self.logger.info("==================================================")
    
    def _run_producer_async(self):
        """在生产者线程中运行异步对话生成"""
        asyncio.run(self.dialogue_producer.simulate_dialogue_sequence(self.stop_event))
    
    def get_dialogue_stats(self) -> dict:
        """获取对话统计信息"""
        return {
            "sentences_processed": self.speech_consumer.sentence_count,
            "queue_size": self.sentence_buffer.sentence_queue.qsize(),
            "world_map_items": len(self.world_state.get_world_map().get("items", [])),
            "is_running": not self.stop_event.is_set()
        }


async def main():
    """主函数 - 完整对话系统测试"""
    print("🎭 完整多轮连续对话系统")
    print("=" * 60)
    print("基于test_sentence_buffer_pipeline.py成功经验的重构版本")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 创建对话系统
    dialogue_system = CompleteDialogueSystem()
    
    try:
        # 运行完整对话
        await dialogue_system.run_complete_dialogue()
        
    except Exception as e:
        print(f"❌ 系统错误: {e}")
        logging.error(f"系统错误: {e}", exc_info=True)
    finally:
        # 显示统计信息
        stats = dialogue_system.get_dialogue_stats()
        print(f"\n📊 对话统计:")
        print(f"  处理句子数: {stats['sentences_processed']}")
        print(f"  剩余队列大小: {stats['queue_size']}")
        print(f"  世界地图商品数: {stats['world_map_items']}")
        
        print("\n🎉 完整对话系统测试完成！")


if __name__ == "__main__":
    asyncio.run(main())