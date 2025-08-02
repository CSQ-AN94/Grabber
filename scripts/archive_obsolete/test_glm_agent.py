#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本 - GLM Agent 基本功能验证
基于智谱AI GLM-4V-Flash模型
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.glm_agent import GLMAgent


async def test_basic_functionality():
    """测试基本功能"""
    print("=== 测试GLM基本功能 ===")
    
    try:
        # 初始化代理
        print("1. 初始化GLM代理...")
        agent = GLMAgent()
        
        if not agent.is_ready():
            print("❌ 代理初始化失败")
            return False
        
        print("✅ 代理初始化成功")
        
        # 测试简单对话
        test_inputs = [
            "你好",
            "请简单介绍一下你自己",
            "1+1等于多少？",
            "作为智能零售机器人，你可以做什么？"
        ]
        
        print("\n2. 测试基本对话...")
        for i, test_input in enumerate(test_inputs, 1):
            print(f"\n测试 {i}: {test_input}")
            result = await agent.process_text(test_input)
            
            if result["success"]:
                print(f"✅ 回复: {result['text'][:150]}...")
                if 'usage' in result:
                    print(f"   Token: {result['usage']['total_tokens']}")
            else:
                print(f"❌ 失败: {result['error']}")
                return False
        
        print("\n✅ 基本功能测试通过")
        return True
        
    except Exception as e:
        print(f"❌ 测试过程中发生错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_error_handling():
    """测试错误处理"""
    print("\n=== 测试错误处理 ===")
    
    try:
        agent = GLMAgent()
        
        # 测试空输入
        print("1. 测试空输入...")
        result = await agent.process_text("")
        if not result["success"]:
            print("✅ 空输入处理正确")
        else:
            print("❌ 空输入应该返回错误")
            return False
        
        # 测试纯空格输入
        print("2. 测试纯空格输入...")
        result = await agent.process_text("   ")
        if not result["success"]:
            print("✅ 纯空格输入处理正确")
        else:
            print("❌ 纯空格输入应该返回错误")
            return False
        
        print("✅ 错误处理测试通过")
        return True
        
    except Exception as e:
        print(f"❌ 错误处理测试失败: {e}")
        return False


async def test_retail_robot_scenarios():
    """测试零售机器人场景"""
    print("\n=== 测试零售机器人场景 ===")
    
    try:
        agent = GLMAgent()
        
        if not agent.is_ready():
            print("❌ 代理未就绪")
            return False
        
        # 零售场景测试用例
        scenarios = [
            "请扫描货架上的商品",
            "奥利奥饼干多少钱？",
            "帮我抓取1-1区域的商品",
            "移动到扫描位置",
            "播报当前货架商品清单",
            "谢谢你的帮助"
        ]
        
        passed = 0
        total = len(scenarios)
        
        for i, scenario in enumerate(scenarios, 1):
            print(f"\n[{i}/{total}] 场景: {scenario}")
            
            result = await agent.process_text(scenario)
            
            if result["success"]:
                print(f"✅ 回复: {result['text'][:200]}...")
                if 'usage' in result:
                    print(f"   Token使用: {result['usage']['total_tokens']}")
                passed += 1
            else:
                print(f"❌ 失败: {result['error']}")
        
        print(f"\n零售场景测试结果: {passed}/{total} 通过")
        return passed == total
        
    except Exception as e:
        print(f"❌ 零售场景测试错误: {e}")
        return False


async def interactive_mode():
    """交互式模式"""
    print("\n=== GLM交互式模式 ===")
    print("提示: 输入 'quit' 或 'q' 退出")
    
    try:
        agent = GLMAgent()
        
        if not agent.is_ready():
            print("❌ 代理未就绪")
            return
        
        print("✅ 进入交互模式...")
        
        while True:
            try:
                user_input = input("\n👤 您: ").strip()
                
                if user_input.lower() in ['quit', 'q', 'exit']:
                    print("👋 再见!")
                    break
                
                if not user_input:
                    continue
                
                print("🤖 GLM思考中...")
                result = await agent.process_text(user_input)
                
                if result["success"]:
                    print(f"🤖 GLM: {result['text']}")
                    if 'usage' in result:
                        print(f"💰 Token: {result['usage']['total_tokens']}")
                else:
                    print(f"❌ 错误: {result['error']}")
                    
            except KeyboardInterrupt:
                print("\n👋 再见!")
                break
    
    except Exception as e:
        print(f"❌ 交互模式错误: {e}")


async def run_all_tests():
    """运行所有测试"""
    print("开始运行所有GLM Agent自动化测试...")
    
    tests = [
        ("基本功能", test_basic_functionality()),
        ("错误处理", test_error_handling()),
        ("零售场景", test_retail_robot_scenarios())
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_coro in tests:
        print(f"\n{'='*50}")
        print(f"执行测试: {test_name}")
        print('='*50)
        
        try:
            result = await test_coro
            if result:
                print(f"✅ {test_name} 通过")
                passed += 1
            else:
                print(f"❌ {test_name} 失败")
        except Exception as e:
            print(f"❌ {test_name} 异常: {e}")
    
    print(f"\n{'='*50}")
    print(f"GLM Agent测试总结: {passed}/{total} 通过")
    print('='*50)
    
    return passed == total


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="GLM Agent 测试工具")
    parser.add_argument("mode", nargs="?", default="interactive", 
                       choices=["interactive", "test", "retail"],
                       help="运行模式: interactive(交互), test(自动测试), retail(零售场景)")
    
    args = parser.parse_args()
    
    # 设置日志
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        if args.mode == "interactive":
            asyncio.run(interactive_mode())
        elif args.mode == "test":
            asyncio.run(run_all_tests())
        elif args.mode == "retail":
            asyncio.run(test_retail_robot_scenarios())
    
    except KeyboardInterrupt:
        print("\n👋 用户中断退出")
    except Exception as e:
        print(f"❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()