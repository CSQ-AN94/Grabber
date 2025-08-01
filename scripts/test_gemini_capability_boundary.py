#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gemini能力边界测试脚本
测试Gemini在工具调用、依赖理解、语义推理等方面的能力边界
"""

import sys
import os
import asyncio
import logging
from typing import List, Dict, Any

# 添加项目根目录到Python路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from intelligence.gemini_agent import GeminiAgent
from intelligence.competition_tools import get_competition_tools


class GeminiCapabilityTester:
    """Gemini能力边界测试器"""
    
    def __init__(self):
        self.agent = None
        self.tools = get_competition_tools()
        self.test_results = []
    
    async def setup_agent(self) -> bool:
        """设置带有比赛工具的Gemini代理"""
        try:
            print("🔧 初始化Gemini代理...")
            self.agent = GeminiAgent(enable_tools=True)
            
            if not self.agent.is_ready():
                print("❌ Gemini代理初始化失败")
                return False
            
            # 注册所有比赛工具函数
            tool_definitions = self.tools.get_tool_definitions()
            
            for tool_def in tool_definitions:
                self.agent.register_tool(
                    name=tool_def["name"],
                    description=tool_def["description"],
                    func=tool_def["function"],
                    parameters=tool_def["parameters"]
                )
            
            print(f"✅ 成功注册{len(tool_definitions)}个工具函数")
            print("📋 已注册工具:", [tool["name"] for tool in tool_definitions])
            return True
            
        except Exception as e:
            print(f"❌ 代理设置失败: {e}")
            return False
    
    async def run_test_case(self, test_name: str, user_input: str, expected_behaviors: List[str]) -> Dict[str, Any]:
        """
        运行单个测试用例
        
        Args:
            test_name: 测试用例名称
            user_input: 用户输入
            expected_behaviors: 期望的行为列表
            
        Returns:
            测试结果字典
        """
        print(f"\n🧪 测试: {test_name}")
        print(f"👤 用户输入: \"{user_input}\"")
        print(f"🎯 期望行为: {', '.join(expected_behaviors)}")
        print("-" * 60)
        
        try:
            result = await self.agent.process_text(user_input)
            
            test_result = {
                "test_name": test_name,
                "user_input": user_input,
                "expected_behaviors": expected_behaviors,
                "success": result["success"],
                "response_text": result.get("text", ""),
                "tool_calls": result.get("tool_calls", 0),
                "model": result.get("model", ""),
                "analysis": {}
            }
            
            if result["success"]:
                print(f"✅ 执行成功")
                print(f"🤖 AI回复: {result['text']}")
                print(f"🔧 工具调用次数: {result.get('tool_calls', 0)}")
                
                # 分析行为
                analysis = self.analyze_behavior(result, expected_behaviors)
                test_result["analysis"] = analysis
                
                print(f"📊 行为分析:")
                for behavior, achieved in analysis.items():
                    status = "✅" if achieved else "❌"
                    print(f"   {status} {behavior}")
                
            else:
                print(f"❌ 执行失败: {result.get('error', '未知错误')}")
                test_result["error"] = result.get("error", "")
            
            print("-" * 60)
            return test_result
            
        except Exception as e:
            print(f"❌ 测试异常: {e}")
            return {
                "test_name": test_name,
                "user_input": user_input, 
                "success": False,
                "error": str(e),
                "analysis": {}
            }
    
    def analyze_behavior(self, result: Dict[str, Any], expected_behaviors: List[str]) -> Dict[str, bool]:
        """分析AI行为是否符合期望"""
        analysis = {}
        response_text = result.get("text", "").lower()
        tool_calls = result.get("tool_calls", 0)
        
        for behavior in expected_behaviors:
            if behavior == "调用工具函数":
                analysis[behavior] = tool_calls > 0
            elif behavior == "先查询再抓取":
                # 这个需要更复杂的分析，目前简化为检查是否有多次工具调用
                analysis[behavior] = tool_calls > 1
            elif behavior == "理解语义需求":
                # 检查是否包含相关关键词
                keywords = ["饮料", "水", "渴", "商品", "价格"]
                analysis[behavior] = any(keyword in response_text for keyword in keywords)
            elif behavior == "适合TTS播报":
                # 检查文本是否自然，包含完整信息
                analysis[behavior] = (
                    len(response_text.strip()) > 10 and
                    not response_text.startswith("error") and
                    "成功" in response_text or "完成" in response_text or "找到" in response_text
                )
            elif behavior == "理解相对位置":
                analysis[behavior] = any(word in response_text for word in ["上方", "下方", "左边", "右边", "旁边"])
            elif behavior == "商品推荐":
                analysis[behavior] = "推荐" in response_text or "建议" in response_text
            elif behavior == "价格计算":
                analysis[behavior] = "元" in response_text and ("总" in response_text or "共" in response_text)
            else:
                analysis[behavior] = False
        
        return analysis
    
    async def run_all_capability_tests(self):
        """运行所有能力边界测试"""
        print("🚀 开始Gemini能力边界测试")
        print("=" * 80)
        
        # 定义测试用例
        test_cases = [
            {
                "name": "基础工具调用",
                "input": "请扫描货架",
                "expected": ["调用工具函数", "适合TTS播报"]
            },
            {
                "name": "语义理解-渴了要水",
                "input": "我渴了，请给我水",  
                "expected": ["理解语义需求", "先查询再抓取", "调用工具函数"]
            },
            {
                "name": "直接商品请求",
                "input": "我要买苹果",
                "expected": ["先查询再抓取", "调用工具函数", "适合TTS播报"]
            },
            {
                "name": "相对位置理解",
                "input": "给我可口可乐上面的那个商品",
                "expected": ["理解相对位置", "先查询再抓取", "调用工具函数"]
            },
            {
                "name": "类别查询",
                "input": "货架上有什么水果？",
                "expected": ["调用工具函数", "理解语义需求", "适合TTS播报"]
            },
            {
                "name": "商品推荐",
                "input": "推荐一些便宜的饮料",
                "expected": ["商品推荐", "调用工具函数", "理解语义需求"]
            },
            {
                "name": "结账功能",
                "input": "帮我结账",
                "expected": ["调用工具函数", "价格计算", "适合TTS播报"]
            },
            {
                "name": "复杂组合任务",
                "input": "先扫描货架，然后告诉我第二层有什么，再给我拿个最便宜的水果",
                "expected": ["先查询再抓取", "调用工具函数", "理解语义需求", "适合TTS播报"]
            }
        ]
        
        # 执行所有测试
        for i, test_case in enumerate(test_cases, 1):
            print(f"\n[{i}/{len(test_cases)}]")
            result = await self.run_test_case(
                test_case["name"],
                test_case["input"], 
                test_case["expected"]
            )
            self.test_results.append(result)
            
            # 测试间隔
            await asyncio.sleep(2)
        
        # 生成测试报告
        self.generate_test_report()
    
    def generate_test_report(self):
        """生成测试报告"""
        print("\n" + "=" * 80)
        print("📊 Gemini能力边界测试报告")
        print("=" * 80)
        
        total_tests = len(self.test_results)
        successful_tests = sum(1 for result in self.test_results if result["success"])
        
        print(f"总测试数: {total_tests}")
        print(f"成功执行: {successful_tests}")
        print(f"成功率: {successful_tests/total_tests*100:.1f}%")
        
        # 能力分析
        print("\n🎯 能力分析:")
        capability_stats = {}
        
        for result in self.test_results:
            if "analysis" in result:
                for behavior, achieved in result["analysis"].items():
                    if behavior not in capability_stats:
                        capability_stats[behavior] = {"total": 0, "achieved": 0}
                    capability_stats[behavior]["total"] += 1
                    if achieved:
                        capability_stats[behavior]["achieved"] += 1
        
        for capability, stats in capability_stats.items():
            success_rate = stats["achieved"] / stats["total"] * 100 if stats["total"] > 0 else 0
            print(f"  {capability}: {stats['achieved']}/{stats['total']} ({success_rate:.1f}%)")
        
        # 详细结果
        print("\n📋 详细测试结果:")
        for i, result in enumerate(self.test_results, 1):
            status = "✅" if result["success"] else "❌"
            print(f"{i:2d}. {status} {result['test_name']}")
            if not result["success"] and "error" in result:
                print(f"     错误: {result['error']}")
        
        print("\n🔍 关键发现:")
        self.analyze_key_findings()
    
    def analyze_key_findings(self):
        """分析关键发现"""
        findings = []
        
        # 工具调用能力
        tool_call_tests = [r for r in self.test_results if r["success"] and r.get("tool_calls", 0) > 0]
        if len(tool_call_tests) >= len(self.test_results) * 0.8:
            findings.append("✅ Gemini具备良好的工具调用能力")
        else:
            findings.append("⚠️ Gemini的工具调用能力需要改进")
        
        # 依赖理解能力
        dependency_tests = [r for r in self.test_results if r.get("analysis", {}).get("先查询再抓取", False)]
        if len(dependency_tests) >= 2:
            findings.append("✅ Gemini能够理解工具调用的依赖关系")
        else:
            findings.append("⚠️ Gemini可能不理解工具调用的依赖关系，需要更明确的指导")
        
        # 语义理解能力
        semantic_tests = [r for r in self.test_results if r.get("analysis", {}).get("理解语义需求", False)]
        if len(semantic_tests) >= 3:
            findings.append("✅ Gemini具备较强的语义理解能力")
        else:
            findings.append("⚠️ Gemini的语义理解能力有限")
        
        # TTS适配能力
        tts_tests = [r for r in self.test_results if r.get("analysis", {}).get("适合TTS播报", False)]
        if len(tts_tests) >= len(self.test_results) * 0.7:
            findings.append("✅ Gemini的文本输出适合TTS播报")
        else:
            findings.append("⚠️ Gemini的文本输出需要优化以适配TTS")
        
        for finding in findings:
            print(f"  • {finding}")


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description="Gemini能力边界测试")
    parser.add_argument("--mode", default="full", choices=["full", "single"],
                       help="测试模式：full(全部测试) 或 single(单个测试)")
    parser.add_argument("--input", help="单个测试的用户输入")
    
    args = parser.parse_args()
    
    # 设置日志
    logging.basicConfig(
        level=logging.WARNING,  # 减少噪音
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    try:
        tester = GeminiCapabilityTester()
        
        if not await tester.setup_agent():
            return
        
        if args.mode == "full":
            await tester.run_all_capability_tests()
        elif args.mode == "single" and args.input:
            result = await tester.run_test_case(
                "单个测试",
                args.input,
                ["调用工具函数", "适合TTS播报"]
            )
            print(f"\n测试结果: {'成功' if result['success'] else '失败'}")
        else:
            print("单个测试模式需要指定 --input 参数")
    
    except KeyboardInterrupt:
        print("\n👋 用户中断测试")
    except Exception as e:
        print(f"❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())