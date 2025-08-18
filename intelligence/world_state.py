#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能零售机器人世界状态管理器
管理货架布局、商品信息和机器人状态，支持语义化查询和智能推荐
"""

import threading
from typing import Dict, List, Any
from dataclasses import dataclass
from enum import Enum


class ItemStatus(Enum):
    ON_SHELF = "on_shelf"
    ON_CHECKOUT_ZONE = "on_checkout_zone"


@dataclass
class ShelfItem:
    """货架物品信息"""
    item_name: str
    price: float
    status: ItemStatus = ItemStatus.ON_SHELF


class WorldState:
    """
    智能零售机器人世界状态管理器
    
    设计目标：
    1. 管理货架布局和商品状态信息
    2. 模拟2层货架，每层4个商品位置（共8个位置）
    3. 支持语义化商品查询和智能推荐
    4. 为LLM驱动的购物助手提供数据支持
    """
    
    def __init__(self):
        self.lock = threading.Lock()
        
        # 货架布局：position_id -> ShelfItem
        self.shelf_layout: Dict[int, ShelfItem] = {}
        self.shelf_scanned = False
        
        # 结账区商品
        self.checkout_items: List[str] = []
        
        # 机器人状态
        self.robot_busy = False
        
        # 商品数据库
        self.item_database = {
            "可口可乐": {"price": 3.5},
            "百事可乐": {"price": 3.5},
            "红牛": {"price": 6.0},
            "农夫山泉矿泉水": {"price": 2.5},
            "营养快线": {"price": 6.0},
            "娃哈哈 AD钙奶": {"price": 5.5},
            "纯牛奶": {"price": 2.5},
            "雀巢咖啡": {"price": 4.0},
            "牙膏": {"price": 7.0},
            "洗发水": {"price": 12.0},
            "薯片": {"price": 3.5},
            "洽洽瓜子": {"price": 5.0},
            "奥利奥饼干": {"price": 6.0},
            "维达纸巾": {"price": 4.0},
            "橘子": {"price": 1.5},
            "苹果": {"price": 2.0}
        }
    
    # === 货架扫描模拟 ===
    def simulate_shelf_scan(self) -> List[str]:
        """
        模拟货架扫描，返回8个位置的商品列表
        这个函数被scan_shelf_and_identify工具调用
        """
        with self.lock:
            # 模拟扫描结果：随机选择8个商品放在货架上
            available_items = [
                "可口可乐", "薯片", "农夫山泉矿泉水", "红牛",        # 第1层（位置1-4）
                "雀巢咖啡", "苹果", "奥利奥饼干", "橘子"           # 第2层（位置5-8）
            ]
            
            # 清空现有布局
            self.shelf_layout.clear()
            
            # 填充货架布局
            for pos_id, item_name in enumerate(available_items, 1):
                if item_name in self.item_database:
                    item_info = self.item_database[item_name]
                    self.shelf_layout[pos_id] = ShelfItem(
                        item_name=item_name,
                        price=item_info["price"],
                        status=ItemStatus.ON_SHELF
                    )
            
            self.shelf_scanned = True
            return available_items
    
    # === 查询接口 ===
    def query_full_layout(self) -> Dict[str, Any]:
        """查询完整的货架布局，按位置顺序显示所有位置（包括空位）"""
        with self.lock:
            if not self.shelf_scanned:
                return {"success": False, "error": "货架尚未扫描"}
            
            layout = {}
            layer1_items = ["空位"] * 4
            layer2_items = ["空位"] * 4
            
            # 收集货架上的商品信息
            for pos_id, item in self.shelf_layout.items():
                if item.status == ItemStatus.ON_SHELF:
                    item_data = {
                        "position_id": pos_id,
                        "item_name": item.item_name,
                        "price": item.price
                    }
                    layout[pos_id] = item_data
                    
                    if pos_id <= 4:
                        layer1_items[pos_id - 1] = item.item_name
                    else:
                        layer2_items[pos_id - 5] = item.item_name
            
            return {
                "success": True,
                "layout": layout,
                "layer1": layer1_items,
                "layer2": layer2_items,
                "total_items": len(layout)
            }
    
    def query_checkout_summary(self) -> Dict[str, Any]:
        """查询结账区摘要"""
        with self.lock:
            items = []
            total_price = 0.0
            
            for item_name in self.checkout_items:
                if item_name in self.item_database:
                    price = self.item_database[item_name]["price"]
                    items.append({"name": item_name, "price": price})
                    total_price += price
            
            return {
                "success": True,
                "items": items,
                "total_price": total_price,
                "item_count": len(items)
            }

    # === 机器人操作接口 ===

# 全局世界状态实例
_world_state = None

def get_world_state() -> WorldState:
    """获取世界状态管理器实例（单例模式）"""
    global _world_state
    if _world_state is None:
        _world_state = WorldState()
    return _world_state