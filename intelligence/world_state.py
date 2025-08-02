#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能零售机器人世界状态管理器
管理货架布局、商品信息和机器人状态，支持语义化查询和智能推荐
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
    description: str
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
        
        # 商品数据库（完整的16种比赛商品）- 基于语义描述的智能推荐设计
        self.item_database = {
            "可口可乐": {
                "price": 3.5,
                "description": "经典碳酸饮料，红色易拉罐装，330ml，甜味汽水，解渴提神，含咖啡因，气泡丰富，冰爽畅快"
            },
            "百事可乐": {
                "price": 3.5, 
                "description": "知名碳酸饮料，蓝色易拉罐装，330ml，甜味汽水，解渴提神，含咖啡因，口感清爽，年轻活力"
            },
            "红牛": {
                "price": 6.0,
                "description": "功能性能量饮料，蓝银色罐装，250ml，提神醒脑，缓解疲劳，补充体力，运动健身，维生素B群"
            },
            "农夫山泉矿泉水": {
                "price": 2.5,
                "description": "天然矿泉水，透明塑料瓶装，500ml，纯净解渴，补充水分，健康天然，无色无味，清洁卫生"
            },
            "营养快线": {
                "price": 6.0,
                "description": "复合型乳饮料，白色利乐包装，500ml，香甜奶味，营养补充，富含蛋白质和维生素，饱腹感强"
            },
            "娃哈哈 AD钙奶": {
                "price": 5.5,
                "description": "儿童营养饮品，蓝白色塑料瓶，220ml，甜味奶饮，补钙健骨，富含维生素A和D，促进发育"
            },
            "纯牛奶": {
                "price": 2.5,
                "description": "新鲜纯牛奶，白色利乐包装，250ml，浓郁奶香，营养丰富，补充蛋白质和钙质，健康天然"
            },
            "雀巢咖啡": {
                "price": 4.0,
                "description": "速溶咖啡饮品，棕色瓶装，180ml，浓郁咖啡香，提神醒脑，缓解困倦，工作学习伴侣，苦中带甜"
            },
            "牙膏": {
                "price": 7.0,
                "description": "口腔清洁用品，白色软管包装，120g，薄荷香味，清洁牙齿，保护口腔，去除异味，日常洗漱必需"
            },
            "洗发水": {
                "price": 12.0,
                "description": "头发清洁护理产品，蓝色塑料瓶装，400ml，柔顺香氛，清洁头皮，滋养发丝，日常洗护用品"
            },
            "薯片": {
                "price": 3.5,
                "description": "酥脆薯片零食，金色包装袋，70g，香脆可口，解馋充饥，聚会休闲，多种口味，老少皆宜"
            },
            "洽洽瓜子": {
                "price": 5.0,
                "description": "炒制瓜子零食，红色包装袋，108g，香脆咸香，消磨时光，解馋嗑食，休闲娱乐，传统小食"
            },
            "奥利奥饼干": {
                "price": 6.0,
                "description": "夹心饼干零食，蓝色包装盒，97g，巧克力味，香甜酥脆，解馋充饥，下午茶点，经典美味"
            },
            "维达纸巾": {
                "price": 4.0,
                "description": "面部纸巾用品，白色包装盒，200抽，柔软亲肤，清洁擦拭，日常必需，卫生方便，居家办公"
            },
            "橘子": {
                "price": 1.5,
                "description": "新鲜柑橘水果，橙黄色圆形，单个装，酸甜多汁，补充维C，健康营养，天然有机，解渴开胃"
            },
            "苹果": {
                "price": 2.0,
                "description": "新鲜苹果水果，红色圆形，单个装，香甜脆嫩，富含纤维，健康营养，天然有机，饱腹感强"
            }
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
                        description=item_info["description"],
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
                        "description": item.description
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
                        "description": item.description,
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
    
    def find_items_by_need(self, user_need: str) -> Dict[str, Any]:
        """
        基于用户需求描述查找合适商品（语义匹配）
        
        Args:
            user_need: 用户需求描述，如"解渴"、"充饥"、"提神"、"清洁"等
        
        Returns:
            匹配的商品列表，按相关度排序
        """
        with self.lock:
            if not self.shelf_scanned:
                return {"success": False, "error": "货架尚未扫描"}
            
            # 需求关键词映射（简化的语义匹配）
            need_keywords = {
                "解渴": ["解渴", "补充水分", "水", "饮料", "汽水", "矿泉水"],
                "充饥": ["充饥", "饱腹", "零食", "饼干", "瓜子", "薯片", "水果"],
                "提神": ["提神", "醒脑", "咖啡因", "咖啡", "能量", "缓解疲劳"],
                "清洁": ["清洁", "洗漱", "清洁用品", "牙膏", "洗发水", "纸巾"],
                "营养": ["营养", "蛋白质", "维生素", "钙质", "健康", "牛奶"],
                "休闲": ["休闲", "零食", "消磨时光", "聚会", "娱乐"],
                "甜食": ["甜", "巧克力", "香甜", "甜味", "饼干"]
            }
            
            # 扩展用户需求关键词
            search_keywords = []
            user_need_lower = user_need.lower()
            
            # 直接包含的关键词
            search_keywords.append(user_need_lower)
            
            # 映射的关键词
            for need_type, keywords in need_keywords.items():
                if need_type in user_need_lower:
                    search_keywords.extend(keywords)
            
            # 在货架上的商品中搜索匹配
            matched_items = []
            
            for pos_id, item in self.shelf_layout.items():
                if item.status == ItemStatus.ON_SHELF:
                    # 获取商品描述
                    item_description = item.description.lower()
                    
                    # 计算匹配度
                    match_score = 0
                    matched_keywords = []
                    
                    for keyword in search_keywords:
                        if keyword in item_description:
                            match_score += 1
                            matched_keywords.append(keyword)
                    
                    if match_score > 0:
                        matched_items.append({
                            "position_id": pos_id,
                            "item_name": item.item_name,
                            "price": item.price,
                            "description": item.description,
                            "match_score": match_score,
                            "matched_keywords": matched_keywords,
                            "layer": 1 if pos_id <= 4 else 2,
                            "shelf_position": ((pos_id - 1) % 4) + 1
                        })
            
            # 按匹配度排序
            matched_items.sort(key=lambda x: x["match_score"], reverse=True)
            
            return {
                "success": True,
                "user_need": user_need,
                "items": matched_items,
                "count": len(matched_items)
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


# 全局世界状态实例
_world_state = None

def get_world_state() -> WorldState:
    """获取世界状态管理器实例（单例模式）"""
    global _world_state
    if _world_state is None:
        _world_state = WorldState()
    return _world_state