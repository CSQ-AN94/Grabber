#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试Live API对话系统 - 自动化测试版本
模拟用户输入来测试完整的对话流程
"""

import sys
import os
import asyncio
import logging
import threading
import time
from typing import List

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.live_api_dialogue_system import LiveAPIDialogueSystem
from utils.config import setup_logging


class AutomatedLiveAPITest:
    """自动化Live API对话测试"""
    
    def __init__(self):
        self.dialogue_system = LiveAPIDialogueSystem()
        self.logger = logging.getLogger(__name__)
        
        # 测试消息序列
        self.test_messages = [
            "你好，我是新用户",
            "你能做什么？",
            "请扫描货架商品",
            "我想要牙膏",
            "雀巢咖啡右边是什么？",
            "帮我结账",
            "谢谢你的帮助"
        ]
        
        self.current_message_index = 0
        self.test_running = False
        
    async def run_automated_test(self):
        """运行自动化测试"""
        self.logger.info("🧪 开始自动化Live API对话测试")
        
        # 修改对话系统的发送消息方法
        original_send_messages = self.dialogue_system._send_messages
        self.dialogue_system._send_messages = self._automated_send_messages
        
        try:
            # 启动对话系统
            await self.dialogue_system.start_dialogue()
            
        except Exception as e:
            self.logger.error(f"自动化测试错误: {e}")
            raise
        finally:
            # 恢复原始方法
            self.dialogue_system._send_messages = original_send_messages
    
    async def _automated_send_messages(self):
        """自动化发送消息"""
        self.test_running = True
        self.logger.info("🤖 开始自动化消息发送...")
        
        for i, message in enumerate(self.test_messages):
            if not self.dialogue_system.is_running:
                break
            
            self.logger.info(f"[测试消息 {i+1}/{len(self.test_messages)}] 发送: {message}")
            
            # 发送到Live API
            await self.dialogue_system.session.send_client_content(
                turns={"role": "user", "parts": [{"text": message}]}, 
                turn_complete=True
            )
            
            self.dialogue_system.dialogue_count += 1
            
            # 等待响应处理
            await asyncio.sleep(3)
        
        self.logger.info("✅ 所有测试消息已发送")
        self.test_running = False
        
        # 等待一段时间让最后的响应处理完成
        await asyncio.sleep(5)
    
    def get_test_stats(self) -> dict:
        """获取测试统计信息"""
        stats = self.dialogue_system.get_dialogue_stats()
        stats.update({
            "test_messages_sent": len(self.test_messages),
            "test_completed": not self.test_running,
        })
        return stats


async def main():
    """主函数 - 自动化Live API测试"""
    print("🧪 Live API对话系统 - 自动化测试")
    print("=" * 60)
    print("自动发送测试消息 → Live API处理 → 语音输出")
    print("=" * 60)
    
    # 设置日志
    setup_logging("INFO")
    
    # 创建自动化测试
    test_system = AutomatedLiveAPITest()
    
    try:
        # 运行自动化测试
        await test_system.run_automated_test()
        
    except Exception as e:
        print(f"❌ 测试错误: {e}")
        logging.error(f"测试错误: {e}", exc_info=True)
    finally:
        # 显示统计信息
        stats = test_system.get_test_stats()
        print(f"\n📊 测试统计:")
        print(f"  测试消息数: {stats['test_messages_sent']}")
        print(f"  对话轮数: {stats['dialogue_count']}")
        print(f"  运行时间: {stats['uptime_seconds']:.1f}秒")
        print(f"  语音队列大小: {stats['speech_queue_size']}")
        print(f"  处理句子数: {stats['speech_consumer_stats']['sentences_processed']}")
        print(f"  测试完成: {'✅' if stats['test_completed'] else '❌'}")
        
        # 停止系统
        await test_system.dialogue_system.stop_dialogue()
        
        print("\n🎉 Live API自动化测试完成！")


if __name__ == "__main__":
    asyncio.run(main())