#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试大模型驱动的智能推荐系统
验证大模型是否能基于丰富上下文做出智能购买决策
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


async def test_llm_driven_recommendation():
    """测试大模型驱动的智能推荐系统"""
    print("🧠 测试大模型驱动的智能推荐系统")
    print("=" * 70)
    
    try:
        # 初始化代理，只注册高级函数
        agent = GeminiAgent(enable_tools=True)
        
        if not agent.is_ready():
            print("❌ 代理初始化失败")
            return
        
        # 注册精简的高级工具集
        high_level_tools = [
            scan_shelf,              # 基础：扫描货架
            buy_product,            # 核心：大模型驱动的智能购买
            get_checkout_summary    # 结账：查看购物车
        ]
        
        for func in high_level_tools:
            agent.register_function(func)
        
        print(f"✅ 已注册{len(high_level_tools)}个高级工具")
        print(f"工具列表: {[f.__name__ for f in high_level_tools]}")
        
        # 关键测试用例 - 验证大模型的智能推荐能力
        test_cases = [
            {
                "name": "基础扫描",
                "input": "请扫描货架",
                "expected": "初始化货架信息"
            },
            {
                "name": "直接商品名购买",
                "input": "我要买苹果",
                "expected": "大模型应该识别具体商品名，直接推荐苹果"
            },
            {
                "name": "需求描述购买",
                "input": "我渴了，给我点水",
                "expected": "大模型应该理解解渴需求，推荐水类商品"
            },
            {
                "name": "价格敏感需求",
                "input": "我要便宜点的饮料",
                "expected": "大模型应该结合价格和功能，推荐性价比高的饮料"
            },
            {
                "name": "复合条件需求",
                "input": "给我个便宜的解渴饮料",
                "expected": "大模型应该综合考虑价格和解渴功能"
            },
            {
                "name": "提神需求",
                "input": "我困了，需要提神的东西",
                "expected": "大模型应该推荐咖啡或红牛等提神商品"
            },
            {
                "name": "位置描述（高难度）",
                "input": "给我第一层最便宜的那个",
                "expected": "大模型应该分析第一层商品并选择最便宜的"
            },
            {
                "name": "结账查看",
                "input": "帮我结账，看看买了什么",
                "expected": "显示购物车清单和总价"
            }
        ]
        
        # 执行测试
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n[测试 {i}/{len(test_cases)}] {test_case['name']}")
            print(f"👤 输入: \"{test_case['input']}\"")
            print(f"🎯 期望: {test_case['expected']}")
            print("-" * 50)
            
            result = await agent.process_text(test_case["input"])
            
            if result["success"]:
                print(f"✅ 执行成功")
                print(f"🤖 回复: {result['text']}")
                
                # 检查是否使用了自动函数调用
                if result.get("auto_function_calls"):
                    print("🧠 使用了大模型驱动的自动函数调用")
                else:
                    print("⚠️ 使用了兼容模式")
                    
            else:
                print(f"❌ 执行失败: {result.get('error', '未知错误')}")
            
            print("-" * 50)
            
            # 测试间隔
            await asyncio.sleep(3)
        
        print(f"\n{'='*70}")
        print("🏁 大模型驱动推荐系统测试完成")
        print("\n🔍 关键观察点：")
        print("1. 大模型是否能准确理解不同类型的用户需求？")
        print("2. 推荐是否结合了商品描述、价格、功能等多维信息？")
        print("3. 复合条件（如'便宜的解渴饮料'）是否能正确处理？")
        print("4. 是否体现了比关键词匹配更高级的语义理解？")
        
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    # 设置日志级别
    logging.basicConfig(
        level=logging.WARNING,  # 减少噪音，专注于测试结果
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        asyncio.run(test_llm_driven_recommendation())
    except KeyboardInterrupt:
        print("\n👋 用户中断测试")
    except Exception as e:
        print(f"❌ 程序异常: {e}")