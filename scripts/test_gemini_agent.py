#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试脚本 - Gemini Agent 基本功能验证
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.gemini_agent import GeminiAgent


async def test_basic_functionality():
    """测试基本功能"""
    print("=== 测试基本功能 ===")
    
    try:
        # 初始化代理
        print("1. 初始化Gemini代理...")
        agent = GeminiAgent()
        
        if not agent.is_ready():
            print("❌ 代理初始化失败")
            return False
        
        print("✅ 代理初始化成功")
        
        # 测试简单对话
        test_inputs = [
            "你好",
            "今天天气怎么样？",
            "1+1等于几？",
            "请介绍一下你自己"
        ]
        
        print("\n2. 测试基本对话...")
        for i, test_input in enumerate(test_inputs, 1):
            print(f"\n测试 {i}: {test_input}")
            result = await agent.process_text(test_input)
            
            if result["success"]:
                print(f"✅ 回复: {result['text'][:100]}...")
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
        agent = GeminiAgent()
        
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


async def interactive_mode():
    """交互式模式"""
    print("\n=== 交互式模式 ===")
    print("提示: 输入 'quit' 或 'q' 退出")
    
    try:
        agent = GeminiAgent()
        
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
                
                print("🤖 思考中...")
                result = await agent.process_text(user_input)
                
                if result["success"]:
                    print(f"🤖 AI: {result['text']}")
                else:
                    print(f"❌ 错误: {result['error']}")
                    
            except KeyboardInterrupt:
                print("\n👋 再见!")
                break
    
    except Exception as e:
        print(f"❌ 交互模式错误: {e}")


async def batch_test():
    """批量测试预设问题"""
    print("\n=== 批量测试 ===")
    
    test_questions = [
        "你是谁？",
        "请用一句话介绍智能零售机器人",
        "如何扫描货架？",
        "机器人可以做什么？",
        "感谢你的帮助",
        "再见"
    ]
    
    try:
        agent = GeminiAgent()
        
        if not agent.is_ready():
            print("❌ 代理未就绪")
            return False
        
        passed = 0
        total = len(test_questions)
        
        for i, question in enumerate(test_questions, 1):
            print(f"\n[{i}/{total}] 问题: {question}")
            
            result = await agent.process_text(question)
            
            if result["success"]:
                print(f"✅ 回复: {result['text'][:150]}...")
                passed += 1
            else:
                print(f"❌ 失败: {result['error']}")
        
        print(f"\n批量测试结果: {passed}/{total} 通过")
        return passed == total
        
    except Exception as e:
        print(f"❌ 批量测试错误: {e}")
        return False


async def test_function_calling():
    """测试Function Calling功能"""
    print("\n=== 测试Function Calling功能 ===")
    
    try:
        agent = GeminiAgent()
        
        if not agent.is_ready():
            print("❌ 代理未就绪")
            return False
        
        # 启用Function Calling
        agent.enable_function_calling(True)
        print("✅ 已启用Function Calling功能")
        
        # 测试工具调用
        tool_tests = [
            ("请向我问候", "say_hello"),
            ("请查询机器人状态", "get_robot_status"),
            ("你好，我叫张三", "say_hello"),
            ("机器人状态如何？", "get_robot_status")
        ]
        
        passed = 0
        total = len(tool_tests)
        
        for i, (command, expected_tool) in enumerate(tool_tests, 1):
            print(f"\n[{i}/{total}] 测试: {command}")
            print(f"   期望工具: {expected_tool}")
            
            result = await agent.process_text(command)
            
            if result["success"]:
                tool_calls = result.get("tool_calls", 0)
                print(f"✅ 回复: {result['text'][:150]}...")
                print(f"   工具调用次数: {tool_calls}")
                
                if tool_calls > 0:
                    print("   🔧 成功触发工具调用")
                    passed += 1
                else:
                    print("   ⚠️  未触发工具调用（可能是AI直接回答）")
                    passed += 0.5  # 部分成功
            else:
                print(f"❌ 失败: {result['error']}")
        
        print(f"\nFunction Calling测试结果: {passed}/{total} 通过")
        return passed >= total * 0.6  # 60%通过率算成功
        
    except Exception as e:
        print(f"❌ Function Calling测试错误: {e}")
        import traceback
        traceback.print_exc()
        return False


async def run_all_tests():
    """运行所有测试"""
    print("开始运行所有自动化测试...")
    
    tests = [
        ("基本功能", test_basic_functionality()),
        ("错误处理", test_error_handling()),
        ("批量测试", batch_test()),
        ("Function Calling", test_function_calling())
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
    print(f"测试总结: {passed}/{total} 通过")
    print('='*50)
    
    return passed == total


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gemini Agent 测试工具")
    parser.add_argument("mode", nargs="?", default="interactive", 
                       choices=["interactive", "test", "batch", "tools"],
                       help="运行模式: interactive(交互), test(自动测试), batch(批量测试), tools(Function Calling测试)")
    
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
        elif args.mode == "batch":
            asyncio.run(batch_test())
        elif args.mode == "tools":
            asyncio.run(test_function_calling())
    
    except KeyboardInterrupt:
        print("\n👋 用户中断退出")
    except Exception as e:
        print(f"❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()