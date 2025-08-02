#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能零售机器人工具函数库
实现LLM驱动的智能购物助手功能，支持Gemini自动函数调用
"""

import json
from intelligence.world_state import get_world_state
from intelligence.gemini_agent import GeminiAgent

# 获取世界状态实例
world_state = get_world_state()


def scan_shelf() -> dict:
    """扫描货架并识别所有商品位置，这是了解货架布局的第一步，必须在其他操作前执行"""
    print("[函数调用] scan_shelf()")
    
    # 模拟扫描过程
    scanned_items = world_state.simulate_shelf_scan()
    
    layer1_items = scanned_items[:4]
    layer2_items = scanned_items[4:]
    
    result = {
        "success": True,
        "message": f"货架扫描完成。检测到{len(scanned_items)}个商品。第一层有：{', '.join(layer1_items)}。第二层有：{', '.join(layer2_items)}。",
        "items": scanned_items
    }
    
    print(f"[函数返回] {result['message']}")
    return result


# find_item 函数已删除 - 使用更强大的 buy_product() 替代


# find_items_for_need 函数已删除 - 使用更强大的 buy_product() 替代


# grab_item 函数已删除 - 由 buy_product() 内部调用 _internal_grab_item()


# buy_item 函数已删除 - 使用更强大的 buy_product() 替代


def buy_product(user_query: str) -> dict:
    """
    大模型驱动的通用智能购买函数
    
    理解任何形式的购买需求：
    - 商品名称："苹果"、"可口可乐"
    - 需求描述："我渴了"、"解渴的东西"、"便宜的饮料" 
    - 位置描述："第一层第二个"、"可口可乐旁边的"
    - 复合条件："便宜的解渴饮料"、"提神又不贵的"
    
    内部使用大模型分析用户意图，结合货架信息智能推荐最佳商品
    """
    print(f"[函数调用] buy_product(user_query='{user_query}')")
    try:
        # 1. 收集完整上下文
        context = _gather_complete_context(user_query)
        if not context["success"]:
            return context
        
        # 2. 调用大模型进行智能推荐 (使用同步方式)
        recommendation = _get_llm_recommendation_sync(context)
        if not recommendation["success"]:
            return recommendation
        
        # 3. 执行推荐的购买操作
        result = _execute_recommendation(recommendation)
        
        if result["success"]:
            message = f"根据您的需求'{user_query}'，为您推荐了{result['item_name']}（{result['reasoning']}），{result['message']}"
            result["message"] = message
            result["user_query"] = user_query
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "message": f"购买过程中发生错误：{str(e)}",
            "error": str(e)
        }


def _gather_complete_context(user_query: str) -> dict:
    """收集完整上下文信息"""
    if not world_state.shelf_scanned:
        return {
            "success": False,
            "message": "请先扫描货架",
            "error": "货架尚未扫描"
        }
    
    # 获取货架布局
    shelf_info = world_state.query_full_layout()
    if not shelf_info["success"]:
        return shelf_info
    
    return {
        "success": True,
        "user_query": user_query,
        "shelf_layout": shelf_info["layout"],
        "layer1_items": shelf_info["layer1"],
        "layer2_items": shelf_info["layer2"],
        "total_items": shelf_info["total_items"]
    }


def _get_llm_recommendation_sync(context: dict) -> dict:
    """使用大模型获取智能推荐"""
    try:
        # 创建推荐分析的结构化prompt
        prompt = f"""你是智能购物助手，需要根据用户需求分析并推荐最合适的商品。

用户需求："{context['user_query']}"

当前货架信息：
第一层商品：{', '.join([f"{item}(位置{i+1})" for i, item in enumerate(context['layer1_items'])])}
第二层商品：{', '.join([f"{item}(位置{i+5})" for i, item in enumerate(context['layer2_items'])])}

详细商品信息：
{_format_items_for_llm(context['shelf_layout'])}

请分析用户需求并推荐最佳商品。考虑因素：
1. 用户的具体需求（解渴、充饥、提神、价格敏感等）
2. 商品的功能特性和价格
3. 用户可能的偏好

请严格按以下JSON格式回复（不要包含其他文字）：
{{
    "recommended_item": "推荐的商品名称",
    "position_id": 商品位置ID数字,
    "reasoning": "推荐理由（简洁说明为什么选择这个商品）"
}}"""

        # 创建临时的LLM代理进行分析
        analyzer = GeminiAgent(enable_tools=False)  # 不使用工具，仅用于文本分析
        
        # 同步调用LLM分析 (简化版本)
        import asyncio
        result = asyncio.run(analyzer.process_text(prompt))
        
        if not result["success"]:
            return {
                "success": False,
                "message": "推荐分析失败",
                "error": result.get("error", "LLM分析错误")
            }
        
        # 解析LLM返回的JSON
        try:
            # 提取JSON部分
            response_text = result["text"].strip()
            if "```json" in response_text:
                json_start = response_text.find("```json") + 7
                json_end = response_text.find("```", json_start)
                json_text = response_text[json_start:json_end].strip()
            elif "{" in response_text and "}" in response_text:
                json_start = response_text.find("{")
                json_end = response_text.rfind("}") + 1
                json_text = response_text[json_start:json_end]
            else:
                json_text = response_text
            
            recommendation = json.loads(json_text)
            
            return {
                "success": True,
                "recommended_item": recommendation["recommended_item"],
                "position_id": recommendation["position_id"],
                "reasoning": recommendation["reasoning"]
            }
            
        except json.JSONDecodeError as e:
            return {
                "success": False,
                "message": f"推荐结果解析失败：{result['text']}",
                "error": f"JSON解析错误: {str(e)}"
            }
    
    except Exception as e:
        return {
            "success": False,
            "message": "推荐分析过程中发生错误",
            "error": str(e)
        }


def _format_items_for_llm(shelf_layout: dict) -> str:
    """格式化商品信息供LLM分析"""
    formatted_items = []
    for pos_id, item_data in shelf_layout.items():
        item_text = f"位置{pos_id}: {item_data['item_name']} - {item_data['price']}元\n   描述: {item_data['description']}"
        formatted_items.append(item_text)
    return "\n\n".join(formatted_items)


def _execute_recommendation(recommendation: dict) -> dict:
    """执行LLM推荐的购买操作"""
    try:
        item_name = recommendation["recommended_item"]  
        position_id = recommendation["position_id"]
        reasoning = recommendation["reasoning"]
        
        # 执行抓取操作（内部函数，不暴露给Gemini）
        grab_result = _internal_grab_item(item_name, position_id)
        
        if grab_result["success"]:
            return {
                "success": True,
                "message": grab_result["message"],
                "item_name": item_name,
                "position_id": position_id,
                "price": grab_result["price"],
                "reasoning": reasoning
            }
        else:
            return grab_result
            
    except Exception as e:
        return {
            "success": False,
            "message": "执行推荐操作失败",
            "error": str(e)
        }


def _internal_grab_item(item_name: str, position_id: int) -> dict:
    """内部抓取函数，不暴露给Gemini"""
    result = world_state.execute_grasp_and_drop(position_id, item_name)
    
    if result["success"]:
        result["message"] = f"成功抓取{result['item_name']}，价格{result['price']}元，已放入结账区。"
    
    return result


def get_checkout_summary() -> dict:
    """获取购物车中所有商品的详细清单和总价，用于结账时查看购买的商品和费用"""
    print("[函数调用] get_checkout_summary()")
    
    result = world_state.query_checkout_summary()
    
    if result["success"]:
        if result["item_count"] > 0:
            items_detail = []
            for item in result["items"]:
                items_detail.append(f"{item['name']} {item['price']}元")
            
            result["message"] = (
                f"结账清单：{', '.join(items_detail)}。"
                f"共{result['item_count']}件商品，总计{result['total_price']}元。"
            )
        else:
            result["message"] = "结账区暂无商品。"
    
    print(f"[函数返回] {result['message']}")
    return result