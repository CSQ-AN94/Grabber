#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试自动函数调用功能
验证Gemini的组合式函数调用是否能解决我们的工具依赖链问题
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.gemini_agent import GeminiAgent
from intelligence.simple_auto_tools import (
    scan_shelf, find_item, find_drinks, grab_item, 
    buy_item, get_water, get_checkout_summary
)


async def test_auto_function_calling():
    """测试自动函数调用功能"""
    print("🚀 测试Gemini自动函数调用功能")
    print("=" * 60)
    
    try:
        # 初始化代理
        agent = GeminiAgent(enable_tools=True)
        
        if not agent.is_ready():
            print("❌ 代理初始化失败")
            return
        
        # 注册自动函数（新方式）
        auto_functions = [
            scan_shelf,
            find_item, 
            find_drinks,
            grab_item,
            buy_item,      # 组合函数：查找+抓取
            get_water,     # 组合函数：查找饮料+选择水+抓取
            get_checkout_summary
        ]
        
        for func in auto_functions:
            agent.register_function(func)
        
        print(f"✅ 已注册{len(auto_functions)}个自动函数")
        print(f"函数列表: {[f.__name__ for f in auto_functions]}")
        
        # 测试用例 - 重点测试之前失败的场景
        test_cases = [
            {
                "name": "基础扫描",
                "input": "请扫描货架",
                "expected": "应该调用scan_shelf函数"
            },
            {
                "name": "直接购买（关键测试）",
                "input": "我要买苹果",
                "expected": "应该调用buy_item函数，或者依次调用find_item和grab_item"
            },
            {
                "name": "语义理解+组合调用（关键测试）",
                "input": "我渴了，请给我水",
                "expected": "应该调用get_water函数，或者找到水类饮料并抓取"
            },
            {
                "name": "简单查询",
                "input": "货架上有什么饮料？",
                "expected": "应该调用find_drinks函数"
            },
            {
                "name": "结账功能",
                "input": "帮我结账",
                "expected": "应该调用get_checkout_summary函数"
            }
        ]
        
        # 执行测试
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n[测试 {i}/{len(test_cases)}] {test_case['name']}")
            print(f"👤 输入: \"{test_case['input']}\"")
            print(f"🎯 期望: {test_case['expected']}")
            print("-" * 40)
            
            result = await agent.process_text(test_case["input"])
            
            if result["success"]:
                print(f"✅ 执行成功")
                print(f"🤖 回复: {result['text']}")
                
                # 检查是否使用了自动函数调用
                if result.get("auto_function_calls"):
                    print("🔧 使用了自动函数调用模式")
                else:
                    print("⚠️ 使用了兼容模式")
                    
            else:
                print(f"❌ 执行失败: {result.get('error', '未知错误')}")
            
            print("-" * 40)
            
            # 测试间隔
            await asyncio.sleep(2)
        
        print(f"\n{'='*60}")
        print("🏁 自动函数调用测试完成")
        print("请观察上述结果，重点关注：")
        print("1. 是否成功使用自动函数调用模式")
        print("2. 复杂任务是否能自动分解为多个函数调用")
        print("3. '我要买苹果'和'我渴了'是否能完整执行")
        
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
        asyncio.run(test_auto_function_calling())
    except KeyboardInterrupt:
        print("\n👋 用户中断测试")
    except Exception as e:
        print(f"❌ 程序异常: {e}")