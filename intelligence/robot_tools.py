#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能零售机器人工具函数库
实现LLM驱动的智能购物助手功能，支持Gemini自动函数调用
"""

from intelligence.world_state import get_world_state

# 获取世界状态实例
world_state = get_world_state()


def scan_shelf() -> dict:
    """
    驱动机器人系统扫描货架以初始化货架上所有商品信息，这是了解货架布局的第一步，必须在任何推荐行为前执行。
    建立的世界状态将用于后续的商品查询和推荐，并且随着真实抓取操作的进行而更新。
    
    重要：这是一次性工具，货架扫描完成后不应再次调用。如需查看商品信息，请直接基于现有货架布局进行推荐。

    返回：
    - 首次扫描：返回扫描结果，包括第一层和第二层的商品列表
    - 重复扫描：返回错误，提示应基于现有商品信息进行推荐
    """
    print("[函数调用] scan_shelf()")
    
    # 检查是否已经扫描过
    if world_state.shelf_scanned:
        error_result = {
            "success": False,
            "message": "货架已扫描，无需重复扫描。请直接基于当前货架商品信息为用户推荐合适的商品。",
            "error": "重复扫描被阻止",
            "instruction": "请直接根据已知的货架布局为用户提供商品推荐，而不是重新扫描货架"
        }
        print(f"[函数返回] {error_result['message']}")
        return error_result
    
    # 首次扫描：执行正常的扫描逻辑
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

def get_robot_tools():
    """获取机器人工具函数列表，用于Gemini Agent"""
    return [
        scan_shelf,
        execute_grab, 
        get_checkout_summary
    ]

def execute_grab(item_name: str, position_id: int) -> dict:
    """
    驱动真实机器人系统执行抓取指定商品的操作。
    直接从货架抓取商品并放置到结账区。
    
    参数：
    - item_name: 要抓取的商品名称
    - position_id: 商品在货架上的位置ID
    
    返回：
    - 成功时返回抓取结果，包括商品名称、价格和位置ID
    - 失败时返回错误信息
    """
    print(f"[函数调用] execute_grab(item_name='{item_name}', position_id={position_id})")
    
    # 导入枚举类型
    from world_state import ItemStatus
    
    try:
        # 验证货架状态
        if not world_state.shelf_scanned:
            error_result = {
                "success": False,
                "message": "请先扫描货架",
                "error": "货架尚未扫描"
            }
            print(f"[函数返回] {error_result['message']}")
            return error_result
        
        # 检查机器人忙碌状态
        if world_state.robot_busy:
            error_result = {
                "success": False,
                "message": "机器人正忙，请稍候",
                "error": "机器人正忙"
            }
            print(f"[函数返回] {error_result['message']}")
            return error_result
        
        # 直接操作world_state属性进行抓取
        with world_state.lock:
            # 验证位置和商品
            if position_id not in world_state.shelf_layout:
                error_result = {
                    "success": False,
                    "message": f"无效的位置ID: {position_id}",
                    "error": f"无效的位置ID: {position_id}"
                }
                print(f"[函数返回] {error_result['message']}")
                return error_result
            
            item = world_state.shelf_layout[position_id]
            if item.status != ItemStatus.ON_SHELF:
                error_result = {
                    "success": False,
                    "message": f"位置{position_id}没有可抓取的商品",
                    "error": f"位置{position_id}没有可抓取的商品"
                }
                print(f"[函数返回] {error_result['message']}")
                return error_result
            
            if item.item_name != item_name:
                error_result = {
                    "success": False,
                    "message": f"位置{position_id}的商品是{item.item_name}，不是{item_name}",
                    "error": f"商品不匹配"
                }
                print(f"[函数返回] {error_result['message']}")
                return error_result
            
            # 执行抓取：ON_SHELF -> ON_CHECKOUT_ZONE
            world_state.robot_busy = True
            item.status = ItemStatus.ON_CHECKOUT_ZONE
            world_state.checkout_items.append(item_name)
            world_state.robot_busy = False
            
            success_result = {
                "success": True,
                "message": f"成功抓取{item_name}并放置到结账区",
                "item_name": item_name,
                "price": item.price,
                "position_id": position_id
            }
            print(f"[函数返回] 成功抓取{item_name}，价格{item.price}元")
            return success_result
        
    except Exception as e:
        error_result = {
            "success": False,
            "message": f"抓取操作中发生错误：{str(e)}",
            "error": str(e)
        }
        print(f"[函数返回] {error_result['message']}")
        return error_result



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


def get_robot_tools():
    """获取机器人工具函数列表，用于Gemini Agent"""
    return [
        scan_shelf,
        execute_grab, 
        get_checkout_summary
    ]