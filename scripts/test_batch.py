#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能购物助手批量测试
标准用例回归测试，性能和稳定性验证，API限流友好
"""

import sys
import os
import asyncio
import logging
import time

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.gemini_agent import GeminiAgent
from intelligence.robot_tools import (
    scan_shelf, buy_product, get_checkout_summary
)


# 标准测试用例
STANDARD_TEST_CASES = [
    {
        "name": "系统初始化",
        "input": "请扫描货架",
        "expected": "成功扫描货架，显示8个商品布局",
        "category": "基础功能"
    },
    {
        "name": "直接商品购买",
        "input": "我要买苹果",
        "expected": "找到苹果并成功抓取",
        "category": "核心功能"
    },
    {
        "name": "需求语义理解",
        "input": "我渴了，给我点水",
        "expected": "推荐合适的解渴商品并抓取",
        "category": "智能推荐"
    },
    {
        "name": "维生素补充需求",
        "input": "补充维生素",
        "expected": "智能推荐含维生素的商品（如水果）",
        "category": "智能推荐"
    },
    {
        "name": "价格敏感需求",
        "input": "我要便宜点的饮料",
        "expected": "结合价格推荐性价比高的饮料",
        "category": "智能推荐"
    },
    {
        "name": "复合条件理解",
        "input": "给我个便宜的解渴饮料",
        "expected": "综合考虑价格和功能进行推荐",
        "category": "智能推荐"
    },
    {
        "name": "提神功能需求",
        "input": "我困了，需要提神的东西",
        "expected": "推荐咖啡或红牛等提神商品",
        "category": "智能推荐"
    },
    {
        "name": "购物车查看",
        "input": "帮我结账，看看买了什么",
        "expected": "显示购物车清单和总价",
        "category": "基础功能"
    }
]


async def run_batch_test(test_cases=None, request_interval=5):
    """
    运行批量测试
    
    Args:
        test_cases: 测试用例列表，默认使用标准用例
        request_interval: 请求间隔秒数，避免API限流
    """
    if test_cases is None:
        test_cases = STANDARD_TEST_CASES
    
    print("🧪 智能购物助手批量测试")
    print("=" * 60)
    print(f"测试用例数量: {len(test_cases)}")
    print(f"请求间隔: {request_interval}秒 (避免API限流)")
    print("=" * 60)
    
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
        
        print(f"✅ 已注册 {len(tools)} 个工具函数")
        
        # 测试统计
        total_tests = len(test_cases)
        passed_tests = 0
        failed_tests = 0
        api_limited_tests = 0
        
        # 执行测试用例
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n[测试 {i}/{total_tests}] {test_case['name']} ({test_case['category']})")  
            print(f"👤 输入: \"{test_case['input']}\"")
            print(f"🎯 期望: {test_case['expected']}")
            print("-" * 50)
            
            start_time = time.time()
            
            try:
                result = await agent.process_text(test_case["input"])
                
                if result["success"]:
                    print(f"✅ 执行成功 ({time.time() - start_time:.1f}s)")
                    print(f"🤖 回复: {result['text']}")
                    
                    # 检查执行模式
                    if result.get("auto_function_calls"):
                        print("🧠 使用了LLM驱动的自动函数调用")
                    elif result.get("tool_calls", 0) > 0:
                        print(f"🔧 执行了{result['tool_calls']}个工具调用")
                    
                    passed_tests += 1
                    
                else:
                    error_msg = result.get('error', '未知错误')
                    if "429" in str(error_msg) or "RESOURCE_EXHAUSTED" in str(error_msg):
                        print(f"⏰ API限流: {error_msg}")
                        api_limited_tests += 1
                    else:
                        print(f"❌ 执行失败: {error_msg}")
                        failed_tests += 1
                        
            except Exception as e:
                print(f"❌ 测试异常: {e}")
                failed_tests += 1
            
            print("-" * 50)
            
            # 测试间隔，避免API限流
            if i < total_tests:  # 最后一个测试不需要等待
                print(f"⏳ 等待 {request_interval} 秒...")
                await asyncio.sleep(request_interval)
        
        # 测试结果总结
        print(f"\n{'='*60}")
        print("🏁 批量测试完成")
        print(f"📊 测试统计:")
        print(f"   总测试数: {total_tests}")
        print(f"   ✅ 成功: {passed_tests}")
        print(f"   ❌ 失败: {failed_tests}")
        print(f"   ⏰ API限流: {api_limited_tests}")
        
        success_rate = (passed_tests / total_tests) * 100 if total_tests > 0 else 0
        print(f"   🎯 成功率: {success_rate:.1f}%")
        
        if api_limited_tests > 0:
            print(f"\n💡 建议: 检测到API限流，可以增加请求间隔时间")
        
        print("=" * 60)
        
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()


async def run_quick_test():
    """运行快速测试（只测试核心功能）"""
    quick_cases = [
        STANDARD_TEST_CASES[0],  # 系统初始化
        STANDARD_TEST_CASES[1],  # 直接商品购买
        STANDARD_TEST_CASES[2],  # 需求语义理解
    ]
    
    print("⚡ 快速测试模式")
    await run_batch_test(quick_cases, request_interval=3)


if __name__ == "__main__":
    # 设置日志级别
    logging.basicConfig(
        level=logging.WARNING,  # 减少噪音
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    import argparse
    parser = argparse.ArgumentParser(description='智能购物助手批量测试')
    parser.add_argument('--quick', action='store_true', help='运行快速测试（3个核心用例）')
    parser.add_argument('--interval', type=int, default=5, help='请求间隔秒数（默认5秒）')
    
    args = parser.parse_args()
    
    try:
        if args.quick:
            asyncio.run(run_quick_test())
        else:
            asyncio.run(run_batch_test(request_interval=args.interval))
    except KeyboardInterrupt:
        print("\n👋 用户中断测试")
    except Exception as e:
        print(f"❌ 程序异常: {e}")