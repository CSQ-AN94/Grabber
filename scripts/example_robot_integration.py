#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
示例：如何将GeminiAgent与RobotTools集成
展示完整的机器人语音控制系统
"""

import sys
import os
import asyncio
import logging

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.gemini_agent import GeminiAgent
from intelligence.robot_tools import get_robot_tools


async def setup_robot_agent():
    """设置带有机器人功能的Gemini代理"""
    print("=== 设置智能机器人助手 ===")
    
    # 创建启用工具调用的代理
    agent = GeminiAgent(enable_tools=True)
    
    if not agent.is_ready():
        print("❌ Gemini代理初始化失败")
        return None
    
    # 获取机器人工具实例
    robot_tools = get_robot_tools()
    
    # 注册所有机器人工具函数
    tool_definitions = robot_tools.get_available_tools()
    
    for tool_def in tool_definitions:
        tool_name = tool_def["name"]
        tool_desc = tool_def["description"]
        tool_params = tool_def["parameters"]
        
        # 创建工具函数的包装器
        async def create_tool_wrapper(name):
            async def tool_wrapper(**kwargs):
                return await robot_tools.execute_tool(name, **kwargs)
            return tool_wrapper
        
        tool_func = await create_tool_wrapper(tool_name)
        
        # 注册工具函数
        agent.register_tool(
            name=tool_name,
            description=tool_desc,
            func=tool_func,
            parameters=tool_params
        )
    
    print(f"✅ 成功注册{len(tool_definitions)}个机器人工具函数")
    return agent


async def interactive_robot_demo():
    """交互式机器人演示"""
    print("\n=== 智能机器人助手演示 ===")
    print("支持的语音命令示例：")
    print("- '扫描货架'")
    print("- '抓取1-1区域的商品'")
    print("- '查询奥利奥的价格'")
    print("- '移动到扫描位置'")
    print("输入 'quit' 退出\n")
    
    # 设置机器人代理
    agent = await setup_robot_agent()
    if not agent:
        return
    
    while True:
        try:
            user_input = input("👤 用户: ").strip()
            
            if user_input.lower() in ['quit', 'q', 'exit']:
                print("👋 再见！")
                break
            
            if not user_input:
                continue
            
            print("🤖 处理中...")
            result = await agent.process_text(user_input)
            
            if result["success"]:
                print(f"🤖 机器人: {result['text']}")
                if result.get("tool_calls", 0) > 0:
                    print(f"   (执行了 {result['tool_calls']} 个工具调用)")
            else:
                print(f"❌ 错误: {result['error']}")
                
        except KeyboardInterrupt:
            print("\n👋 再见！")
            break
        except Exception as e:
            print(f"❌ 发生错误: {e}")


async def batch_robot_demo():
    """批量命令演示"""
    print("\n=== 批量机器人命令演示 ===")
    
    # 设置机器人代理
    agent = await setup_robot_agent()
    if not agent:
        return
    
    # 预设命令序列
    commands = [
        "请先移动到扫描位置",
        "开始扫描货架",
        "查询苹果的价格信息",
        "抓取3-1区域的商品", 
        "移动到投放位置",
        "任务完成，回到初始位置"
    ]
    
    print(f"将执行 {len(commands)} 个命令:\n")
    
    for i, command in enumerate(commands, 1):
        print(f"[{i}/{len(commands)}] 👤 用户: {command}")
        
        result = await agent.process_text(command)
        
        if result["success"]:
            print(f"✅ 🤖 机器人: {result['text']}")
            if result.get("tool_calls", 0) > 0:
                print(f"   (执行了 {result['tool_calls']} 个工具调用)")
        else:
            print(f"❌ 错误: {result['error']}")
        
        print("-" * 60)
        
        # 模拟用户间隔
        await asyncio.sleep(1)
    
    print("✅ 批量演示完成")


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="机器人集成演示")
    parser.add_argument("mode", nargs="?", default="interactive",
                       choices=["interactive", "batch"],
                       help="运行模式: interactive(交互式), batch(批量演示)")
    
    args = parser.parse_args()
    
    # 设置日志
    logging.basicConfig(
        level=logging.WARNING,  # 减少日志输出
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        if args.mode == "interactive":
            asyncio.run(interactive_robot_demo())
        elif args.mode == "batch":
            asyncio.run(batch_robot_demo())
    
    except KeyboardInterrupt:
        print("\n👋 用户中断退出")
    except Exception as e:
        print(f"❌ 程序异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()