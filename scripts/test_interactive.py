#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能购物助手交互式测试
实时对话测试，用户体验验证和边界情况探索
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.gemini_agent import GeminiAgent
from intelligence.robot_tools import (
    scan_shelf, buy_product, get_checkout_summary
)


async def run_interactive_test():
    """运行交互式测试"""
    print("🤖 智能购物助手交互式测试")
    print("=" * 50)
    
    try:
        # 初始化代理
        agent = GeminiAgent(enable_tools=True)
        
        if not agent.is_ready():
            print("❌ 代理初始化失败")
            return
        
        # 注册简化的工具函数集 - 只保留LLM驱动的核心功能
        tools = [
            scan_shelf,          # 系统初始化
            buy_product,         # 核心LLM驱动购买功能 - 处理所有购买需求
            get_checkout_summary # 结账功能
        ]
        
        for func in tools:
            agent.register_function(func)
        
        print(f"✅ 智能购物助手准备就绪")
        print(f"已注册 {len(tools)} 个LLM驱动工具函数")
        print("\n💡 建议先输入：'请扫描货架' 来初始化系统")
        print("🔥 试试这些智能功能（全部由buy_product()处理）：")
        print("   - 我要买苹果")
        print("   - 我渴了，给我点水")  
        print("   - 我要便宜的解渴饮料")
        print("   - 补充维生素")  # 测试刚才失败的用例
        print("   - 我困了，需要提神的东西")
        print("   - 帮我结账")
        print("\n输入 'quit' 退出测试")
        print("=" * 50)
        
        # 交互循环
        while True:
            try:
                user_input = input("\n👤 您: ").strip()
                
                if user_input.lower() in ['quit', 'exit', 'q', '退出']:
                    print("👋 感谢使用智能购物助手！")
                    break
                
                if not user_input:
                    continue
                
                print("🤖 处理中...")
                result = await agent.process_text(user_input)
                
                if result["success"]:
                    print(f"🤖 助手: {result['text']}")
                    
                    # 显示执行模式
                    if result.get("auto_function_calls"):
                        print("   🧠 [使用了LLM驱动的自动函数调用]")
                    elif result.get("tool_calls", 0) > 0:
                        print(f"   🔧 [执行了{result['tool_calls']}个工具调用]")
                else:
                    print(f"❌ 错误: {result.get('error', '未知错误')}")
                    if "429" in str(result.get('error', '')):
                        print("   ⏰ API请求过于频繁，请稍后再试")
                        
            except KeyboardInterrupt:
                print("\n👋 用户中断，退出测试")
                break
            except Exception as e:
                print(f"❌ 发生错误: {e}")
        
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 设置日志级别
    logging.basicConfig(
        level=logging.WARNING,  # 减少噪音
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        asyncio.run(run_interactive_test())
    except KeyboardInterrupt:
        print("\n👋 用户中断测试")
    except Exception as e:
        print(f"❌ 程序异常: {e}")