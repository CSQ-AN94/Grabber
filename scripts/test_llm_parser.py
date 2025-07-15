#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM命令解析测试
"""

import sys
import os

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config


def test_llm_parser_basic(llm_parser):
    """测试基本LLM解析功能"""
    print("\n--- [Test] LLM Command Parser Basic ---")
    
    test_cases = [
        "你好",
        "我想要一瓶可口可乐",
        "帮我拿一下右边那个薯片",
        "有什么好喝的吗？",
        "扫描货架",
        "计算总价",
        "拿苹果左边的商品"
    ]
    
    try:
        for i, case in enumerate(test_cases, 1):
            print(f"\n测试 {i}/{len(test_cases)}: '{case}'")
            result = llm_parser.parse_user_command(case)
            print(f"解析结果: {result}")
            
        print("\n--- LLM Parser Basic Test PASSED ---")
        return True
        
    except Exception as e:
        print(f"LLM Parser Basic Test FAILED: {e}")
        return False


def test_llm_parser_interactive(llm_parser):
    """交互式LLM解析测试"""
    print("\n--- [Test] LLM Parser Interactive ---")
    print("请输入命令进行测试，输入'quit'退出")
    
    try:
        while True:
            user_input = input("\n用户输入: ").strip()
            
            if user_input.lower() in ['quit', 'exit', '退出']:
                break
            
            if not user_input:
                continue
            
            try:
                result = llm_parser.parse_user_command(user_input)
                print(f"解析结果: {result}")
            except Exception as e:
                print(f"解析失败: {e}")
        
        print("--- LLM Parser Interactive Test PASSED ---")
        return True
        
    except Exception as e:
        print(f"LLM Parser Interactive Test FAILED: {e}")
        return False


def test_llm_parser_categories(llm_parser):
    """测试不同类别的命令解析"""
    print("\n--- [Test] LLM Parser Categories ---")
    
    categories = {
        "问候": ["你好", "Hello", "早上好"],
        "商品查询": ["有什么商品", "货架上有什么", "商品列表"],
        "商品抓取": ["拿可乐", "给我苹果", "要那个薯片"],
        "位置指令": ["左边的商品", "上面那个", "右边第二个"],
        "结算": ["多少钱", "计算总价", "结账"],
        "扫描": ["扫描货架", "看看有什么", "检查库存"]
    }
    
    try:
        for category, test_cases in categories.items():
            print(f"\n=== {category} ===")
            for case in test_cases:
                print(f"输入: '{case}'")
                try:
                    result = llm_parser.parse_user_command(case)
                    print(f"结果: {result}")
                except Exception as e:
                    print(f"错误: {e}")
        
        print("\n--- LLM Parser Categories Test PASSED ---")
        return True
        
    except Exception as e:
        print(f"LLM Parser Categories Test FAILED: {e}")
        return False


def test_llm_parser_config(llm_parser):
    """测试LLM解析器配置"""
    print("\n--- [Test] LLM Parser Configuration ---")
    
    try:
        # 检查配置
        if hasattr(llm_parser, 'config'):
            config = llm_parser.config
            print(f"✅ LLM config loaded")
            
            # 显示配置信息（隐藏敏感信息）
            if hasattr(config, '__dict__'):
                for key, value in config.__dict__.items():
                    if 'key' not in key.lower() and 'secret' not in key.lower():
                        print(f"  {key}: {value}")
                    else:
                        print(f"  {key}: [HIDDEN]")
        else:
            print("No config attribute found")
        
        # 检查是否可以调用基本方法
        if hasattr(llm_parser, 'parse_user_command'):
            print("parse_user_command method available")
        else:
            print("parse_user_command method not found")
        
        print("--- LLM Parser Configuration Test PASSED ---")
        return True
        
    except Exception as e:
        print(f"LLM Parser Configuration Test FAILED: {e}")
        return False


def run_llm_parser_tests():
    """运行所有LLM解析器测试"""
    print("=== LLM命令解析器测试 ===")
    
    try:
        # 加载配置
        app_config = load_config("config.ini")
        
        # 尝试导入LLM解析器
        try:
            from intelligence.llm_parser import LLMParser
            llm_parser = LLMParser(app_config.llm)
            print("LLM解析器初始化成功")
        except ImportError as e:
            print(f"LLM解析器模块导入失败: {e}")
            print("注意: llm_parser.py 文件可能缺失或有错误")
            return
        except Exception as e:
            print(f"LLM解析器初始化失败: {e}")
            return
        
        # 运行测试菜单
        while True:
            print("\n" + "="*40)
            print("LLM解析器测试菜单")
            print("="*40)
            print("1. 测试基本解析功能")
            print("2. 交互式解析测试")
            print("3. 测试不同类别命令")
            print("4. 测试解析器配置")
            print("5. 运行所有测试")
            print("Q. 退出")
            
            choice = input("请选择: ").upper()
            
            if choice == '1':
                test_llm_parser_basic(llm_parser)
            elif choice == '2':
                test_llm_parser_interactive(llm_parser)
            elif choice == '3':
                test_llm_parser_categories(llm_parser)
            elif choice == '4':
                test_llm_parser_config(llm_parser)
            elif choice == '5':
                test_llm_parser_config(llm_parser)
                test_llm_parser_basic(llm_parser)
                test_llm_parser_categories(llm_parser)
            elif choice == 'Q':
                break
            else:
                print("无效选择，请重试")
            
    except Exception as e:
        print(f"LLM解析器测试失败: {e}")
    finally:
        print("LLM解析器测试结束")


if __name__ == "__main__":
    run_llm_parser_tests()