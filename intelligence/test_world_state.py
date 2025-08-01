#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简化版WorldState - 专门用于测试Gemini能力边界
保持最少的状态信息，专注于测试工具调用模式
"""

import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum


class ItemStatus(Enum):
    ON_SHELF = "on_shelf"
    ON_GRIPPER = "on_gripper" 
    ON_CHECKOUT_ZONE = "on_checkout_zone"


@dataclass
class ShelfItem:
    """货架物品信息"""
    item_name: str
    price: float
    category: str
    status: ItemStatus = ItemStatus.ON_SHELF


class TestWorldState:
    """
    简化版世界状态管理器 - 专门用于测试Gemini Function Calling能力边界
    
    设计目标：
    1. 最少化状态信息，专注于工具调用测试
    2. 模拟2层货架，每层4个商品位置（共8个位置）
    3. 支持多种查询方式来测试Gemini的推理能力
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
        
        # 商品数据库（完整的16种比赛商品）
        self.item_database = {
            "可口可乐": {"price": 3.5, "category": "饮料"},
            "百事可乐": {"price": 3.5, "category": "饮料"},
            "红牛": {"price": 6.0, "category": "饮料"},
            "农夫山泉矿泉水": {"price": 2.5, "category": "饮料"},
            "营养快线": {"price": 6.0, "category": "饮料"},
            "娃哈哈 AD钙奶": {"price": 5.5, "category": "饮料"},
            "纯牛奶": {"price": 2.5, "category": "饮料"},
            "雀巢咖啡": {"price": 4.0, "category": "饮料"},
            "牙膏": {"price": 7.0, "category": "日用品"},
            "洗发水": {"price": 12.0, "category": "日用品"},
            "薯片": {"price": 3.5, "category": "零食"},
            "洽洽瓜子": {"price": 5.0, "category": "零食"},
            "奥利奥饼干": {"price": 6.0, "category": "零食"},
            "维达纸巾": {"price": 4.0, "category": "日用品"},
            "橘子": {"price": 1.5, "category": "水果"},
            "苹果": {"price": 2.0, "category": "水果"}
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
                        category=item_info["category"],
                        status=ItemStatus.ON_SHELF
                    )
            
            self.shelf_scanned = True
            return available_items
    
    # === 查询接口 ===
    def query_full_layout(self) -> Dict[str, Any]:
        """查询完整的货架布局"""
        with self.lock:
            if not self.shelf_scanned:
                return {"success": False, "error": "货架尚未扫描"}
            
            layout = {}
            layer1_items = []
            layer2_items = []
            
            for pos_id, item in self.shelf_layout.items():
                if item.status == ItemStatus.ON_SHELF:
                    item_data = {
                        "position_id": pos_id,
                        "item_name": item.item_name,
                        "price": item.price,
                        "category": item.category
                    }
                    layout[pos_id] = item_data
                    
                    if pos_id <= 4:
                        layer1_items.append(item.item_name)
                    else:
                        layer2_items.append(item.item_name)
            
            return {
                "success": True,
                "layout": layout,
                "layer1": layer1_items,
                "layer2": layer2_items,
                "total_items": len(layout)
            }
    
    def query_by_name(self, item_name: str) -> Dict[str, Any]:
        """根据商品名称查询"""
        with self.lock:
            if not self.shelf_scanned:
                return {"success": False, "error": "货架尚未扫描"}
            
            for pos_id, item in self.shelf_layout.items():
                if item.item_name == item_name and item.status == ItemStatus.ON_SHELF:
                    return {
                        "success": True,
                        "position_id": pos_id,
                        "item_name": item.item_name,
                        "price": item.price,
                        "category": item.category,
                        "layer": 1 if pos_id <= 4 else 2,
                        "shelf_position": ((pos_id - 1) % 4) + 1
                    }
            
            return {"success": False, "error": f"未找到商品: {item_name}"}
    
    def query_by_category(self, category: str) -> Dict[str, Any]:
        """根据类别查询商品"""
        with self.lock:
            if not self.shelf_scanned:
                return {"success": False, "error": "货架尚未扫描"}
            
            items = []
            for pos_id, item in self.shelf_layout.items():
                if item.category == category and item.status == ItemStatus.ON_SHELF:
                    items.append({
                        "position_id": pos_id,
                        "item_name": item.item_name,
                        "price": item.price,
                        "layer": 1 if pos_id <= 4 else 2,
                        "shelf_position": ((pos_id - 1) % 4) + 1
                    })
            
            return {
                "success": True,
                "category": category,
                "items": items,
                "count": len(items)
            }
    
    def query_relative_position(self, reference_item: str, direction: str) -> Dict[str, Any]:
        """查询相对位置的商品"""
        with self.lock:
            if not self.shelf_scanned:
                return {"success": False, "error": "货架尚未扫描"}
            
            # 先找到参考商品的位置
            reference_pos = None
            for pos_id, item in self.shelf_layout.items():
                if item.item_name == reference_item and item.status == ItemStatus.ON_SHELF:
                    reference_pos = pos_id
                    break
            
            if not reference_pos:
                return {"success": False, "error": f"未找到参考商品: {reference_item}"}
            
            # 计算目标位置
            target_pos = None
            if direction in ["上方", "上面"]:
                target_pos = reference_pos - 4 if reference_pos > 4 else None
            elif direction in ["下方", "下面"]:
                target_pos = reference_pos + 4 if reference_pos <= 4 else None
            elif direction in ["左侧", "左边"]:
                if (reference_pos - 1) % 4 > 0:
                    target_pos = reference_pos - 1
            elif direction in ["右侧", "右边"]:
                if (reference_pos - 1) % 4 < 3:
                    target_pos = reference_pos + 1
            
            if target_pos and target_pos in self.shelf_layout:
                target_item = self.shelf_layout[target_pos]
                if target_item.status == ItemStatus.ON_SHELF:
                    return {
                        "success": True,
                        "reference_item": reference_item,
                        "direction": direction,
                        "target_position_id": target_pos,
                        "target_item_name": target_item.item_name,
                        "target_price": target_item.price,
                        "target_category": target_item.category
                    }
            
            return {"success": False, "error": f"{reference_item}的{direction}没有商品"}
    
    def query_robot_status(self) -> Dict[str, Any]:
        """查询机器人状态"""
        with self.lock:
            return {
                "success": True,
                "robot_busy": self.robot_busy,
                "shelf_scanned": self.shelf_scanned,
                "checkout_items_count": len(self.checkout_items)
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
    
    # === 机器人操作 ===
    def execute_grasp_and_drop(self, position_id: int, item_name: str) -> Dict[str, Any]:
        """执行抓取和放置操作"""
        with self.lock:
            if self.robot_busy:
                return {"success": False, "error": "机器人正忙，请稍候"}
            
            if not self.shelf_scanned:
                return {"success": False, "error": "货架尚未扫描"}
            
            if position_id not in self.shelf_layout:
                return {"success": False, "error": f"无效的位置ID: {position_id}"}
            
            item = self.shelf_layout[position_id]
            if item.status != ItemStatus.ON_SHELF:
                return {"success": False, "error": f"位置{position_id}没有可抓取的商品"}
            
            if item.item_name != item_name:
                return {"success": False, "error": f"位置{position_id}的商品是{item.item_name}，不是{item_name}"}
            
            # 执行抓取和放置
            self.robot_busy = True
            item.status = ItemStatus.ON_CHECKOUT_ZONE
            self.checkout_items.append(item_name)
            self.robot_busy = False
            
            return {
                "success": True,
                "message": f"成功抓取{item_name}并放置到结账区",
                "item_name": item_name,
                "price": item.price,
                "position_id": position_id
            }


# 全局测试状态实例
_test_world_state = None

def get_test_world_state() -> TestWorldState:
    """获取测试世界状态实例（单例模式）"""
    global _test_world_state
    if _test_world_state is None:
        _test_world_state = TestWorldState()
    return _test_world_state