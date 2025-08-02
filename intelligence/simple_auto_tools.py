#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化的自动函数调用工具 - 用于测试新架构
使用标准Python函数，支持Gemini自动组合调用
"""

import asyncio
from intelligence.test_world_state import get_test_world_state

# 获取世界状态实例
world_state = get_test_world_state()


def scan_shelf() -> dict:
    """扫描货架并识别所有商品"""
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


def find_item(item_name: str) -> dict:
    """查找指定商品的位置信息"""
    print(f"[函数调用] find_item(item_name='{item_name}')")
    
    if not world_state.shelf_scanned:
        return {
            "success": False,
            "message": "请先扫描货架",
            "error": "货架尚未扫描"
        }
    
    result = world_state.query_by_name(item_name)
    
    if result["success"]:
        message = f"找到了{result['item_name']}，位于第{result['layer']}层第{result['shelf_position']}个位置，价格{result['price']}元。"
        result["message"] = message
    
    print(f"[函数返回] {result.get('message', result.get('error', ''))}")
    return result


def find_drinks() -> dict:
    """查找所有饮料类商品"""
    print("[函数调用] find_drinks()")
    
    if not world_state.shelf_scanned:
        return {
            "success": False,
            "message": "请先扫描货架",
            "error": "货架尚未扫描"
        }
    
    result = world_state.query_by_category("饮料")
    
    if result["success"] and result["count"] > 0:
        items_list = [f"{item['item_name']}({item['price']}元)" for item in result["items"]]
        message = f"找到{result['count']}个饮料类商品：{', '.join(items_list)}。"
        result["message"] = message
    else:
        result["message"] = "货架上没有饮料类商品。"
    
    print(f"[函数返回] {result['message']}")
    return result


def grab_item(item_name: str, position_id: int) -> dict:
    """抓取指定位置的商品"""
    print(f"[函数调用] grab_item(item_name='{item_name}', position_id={position_id})")
    
    result = world_state.execute_grasp_and_drop(position_id, item_name)
    
    if result["success"]:
        result["message"] = f"成功抓取{result['item_name']}，价格{result['price']}元，已放入结账区。"
    
    print(f"[函数返回] {result.get('message', result.get('error', ''))}")
    return result


def buy_item(item_name: str) -> dict:
    """购买指定商品（组合函数：查找+抓取）"""
    print(f"[函数调用] buy_item(item_name='{item_name}')")
    
    # 先查找商品
    find_result = find_item(item_name)
    if not find_result["success"]:
        return find_result
    
    # 再抓取商品
    grab_result = grab_item(item_name, find_result["position_id"])
    
    if grab_result["success"]:
        message = f"购买成功！{grab_result['message']}"
        return {
            "success": True,
            "message": message,
            "item_name": item_name,
            "price": grab_result["price"]
        }
    else:
        return grab_result


def get_water() -> dict:
    """获取水类饮料（组合函数：查找饮料+选择水+抓取）"""
    print("[函数调用] get_water()")
    
    # 查找饮料
    drinks_result = find_drinks()
    if not drinks_result["success"]:
        return drinks_result
    
    # 从饮料中选择水类商品
    water_items = []
    for item in drinks_result["items"]:
        if "水" in item["item_name"] or "矿泉水" in item["item_name"]:
            water_items.append(item)
    
    if not water_items:
        return {
            "success": False,
            "message": "抱歉，货架上没有水类饮料。",
            "error": "未找到水类饮料"
        }
    
    # 选择最便宜的水
    cheapest_water = min(water_items, key=lambda x: x["price"])
    
    # 抓取选中的水
    grab_result = grab_item(cheapest_water["item_name"], cheapest_water["position_id"])
    
    if grab_result["success"]:
        message = f"为您选择了{cheapest_water['item_name']}，{grab_result['message']}"
        return {
            "success": True,
            "message": message,
            "item_name": cheapest_water["item_name"],
            "price": cheapest_water["price"]
        }
    else:
        return grab_result


def get_checkout_summary() -> dict:
    """获取结账摘要"""
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