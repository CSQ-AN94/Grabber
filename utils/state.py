# utils/state.py - 世界状态管理器

import threading
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

class ItemStatus(Enum):
    ON_SHELF = "on_shelf"
    ON_GRIPPER = "on_gripper" 
    ON_CHECKOUT_ZONE = "on_checkout_zone"
    UNKNOWN = "unknown"

@dataclass
class ItemInfo:
    """商品信息数据结构"""
    item_name: str
    price: float
    description: Dict[str, Any]  # shape, color, category等
    world_position: List[float]  # [x, y, z, rx, ry, rz] 6DOF世界坐标
    status: ItemStatus = ItemStatus.ON_SHELF

class WorldState:
    """
    强化的世界状态管理器 - 物理世界的数字孪生
    
    管理：
    1. 机器人状态（继承原有功能）
    2. 世界地图（商品位置和状态）
    3. 动态状态更新
    """
    
    def __init__(self):
        self.lock = threading.Lock()
        
        # --- 原有机器人状态 ---
        self.latest_color_frame = None
        self.latest_depth_frame = None
        self.new_frame_available = False
        self.current_joint_angles = None
        self.is_arm_moving = False
        self.gripper_openness = None
        
        # --- 新增世界地图 ---
        self.world_map: Dict[int, ItemInfo] = {}  # 位置ID -> 商品信息
        self.map_initialized = False
        self.checkout_items: List[str] = []  # 结算区商品列表
        
        # --- 预定义商品信息库 ---
        self.item_database = {
            "牙膏": {"price": 7, "description": {"shape": "管状", "color": "白色", "category": "日用品"}},
            "雀巢咖啡": {"price": 4, "description": {"shape": "瓶装", "color": "棕色", "category": "饮料"}},
            "洗发水": {"price": 12, "description": {"shape": "瓶装", "color": "蓝色", "category": "日用品"}},
            "可口可乐": {"price": 3.5, "description": {"shape": "瓶装", "color": "红色", "category": "饮料"}},
            "百事可乐": {"price": 3.5, "description": {"shape": "瓶装", "color": "蓝色", "category": "饮料"}},
            "橘子": {"price": 1.5, "description": {"shape": "球形", "color": "橙色", "category": "水果"}},
            "苹果": {"price": 2, "description": {"shape": "球形", "color": "红色", "category": "水果"}},
            "纯牛奶": {"price": 2.5, "description": {"shape": "盒装", "color": "白色", "category": "饮料"}},
            "农夫山泉矿泉水": {"price": 2.5, "description": {"shape": "瓶装", "color": "透明", "category": "饮料"}},
            "维达纸巾": {"price": 4, "description": {"shape": "包装", "color": "白色", "category": "日用品"}},
            "薯片": {"price": 3.5, "description": {"shape": "包装", "color": "黄色", "category": "零食"}},
            "洽洽瓜子": {"price": 5, "description": {"shape": "包装", "color": "红色", "category": "零食"}},
            "奥利奥饼干": {"price": 6, "description": {"shape": "包装", "color": "蓝色", "category": "零食"}},
            "娃哈哈 AD钙奶": {"price": 5.5, "description": {"shape": "瓶装", "color": "蓝色", "category": "饮料"}},
            "营养快线": {"price": 6, "description": {"shape": "瓶装", "color": "白色", "category": "饮料"}},
            "红牛": {"price": 6, "description": {"shape": "罐装", "color": "蓝色", "category": "饮料"}}
        }
    
    # --- 原有功能保持不变 ---
    def update_frames(self, color, depth):
        with self.lock:
            self.latest_color_frame = color
            self.latest_depth_frame = depth
            self.new_frame_available = True

    def get_latest_frames(self):
        with self.lock:
            self.new_frame_available = False
            return self.latest_color_frame, self.latest_depth_frame

    def update_joint_angles(self, joint_angles):
        with self.lock:
            self.current_joint_angles = list(joint_angles)

    def get_joint_angles(self):
        with self.lock:
            return self.current_joint_angles

    def set_arm_moving(self, moving: bool):
        with self.lock:
            self.is_arm_moving = moving

    def get_arm_moving(self):
        with self.lock:
            return self.is_arm_moving

    def set_gripper_openness(self, openness):
        with self.lock:
            self.gripper_openness = openness

    def get_gripper_openness(self):
        with self.lock:
            return self.gripper_openness
    
    # --- 新增世界地图管理功能 ---
    def initialize_world_map(self, mock_data: bool = True):
        """初始化世界地图（测试阶段使用mock数据）"""
        with self.lock:
            if mock_data:
                # 测试用的模拟货架布局（2层×4个=8个位置）
                mock_layout = [
                    "可口可乐", "薯片", "农夫山泉矿泉水", "红牛",  # 第1层
                    "雀巢咖啡", "苹果", "奥利奥饼干", "橘子"      # 第2层
                ]
                
                for i, item_name in enumerate(mock_layout, 1):
                    if item_name in self.item_database:
                        item_info = self.item_database[item_name]
                        # 模拟3D位置（实际使用时从视觉系统获取）
                        mock_position = [
                            100 + (i % 4) * 150,  # x: 货架水平位置
                            200 if i <= 4 else 400,  # y: 第1层或第2层
                            300,  # z: 固定高度
                            0, 0, 0  # 旋转角度
                        ]
                        
                        self.world_map[i] = ItemInfo(
                            item_name=item_name,
                            price=item_info["price"],
                            description=item_info["description"],
                            world_position=mock_position,
                            status=ItemStatus.ON_SHELF
                        )
            
            self.map_initialized = True
    
    def get_world_map(self) -> Dict[int, Dict[str, Any]]:
        """获取完整世界地图（Agent查询用）"""
        with self.lock:
            result = {}
            for pos_id, item_info in self.world_map.items():
                result[pos_id] = {
                    "item_name": item_info.item_name,
                    "price": item_info.price,
                    "description": item_info.description,
                    "world_position": item_info.world_position,
                    "status": item_info.status.value,
                    "layer": 1 if pos_id <= 4 else 2,  # 货架层数
                    "shelf_position": ((pos_id - 1) % 4) + 1  # 层内位置
                }
            return result
    
    def query_item_by_name(self, item_name: str) -> Optional[Dict[str, Any]]:
        """根据商品名查询位置信息"""
        with self.lock:
            for pos_id, item_info in self.world_map.items():
                if item_info.item_name == item_name and item_info.status == ItemStatus.ON_SHELF:
                    return {
                        "position_id": pos_id,
                        "item_name": item_info.item_name,
                        "price": item_info.price,
                        "world_position": item_info.world_position,
                        "layer": 1 if pos_id <= 4 else 2,
                        "shelf_position": ((pos_id - 1) % 4) + 1
                    }
            return None
    
    def query_items_by_category(self, category: str) -> List[Dict[str, Any]]:
        """根据分类查询商品"""
        with self.lock:
            results = []
            for pos_id, item_info in self.world_map.items():
                if (item_info.description.get("category") == category and 
                    item_info.status == ItemStatus.ON_SHELF):
                    results.append({
                        "position_id": pos_id,
                        "item_name": item_info.item_name,
                        "price": item_info.price,
                        "layer": 1 if pos_id <= 4 else 2,
                        "shelf_position": ((pos_id - 1) % 4) + 1
                    })
            return results
    
    def query_relative_position(self, reference_position: int, direction: str) -> Optional[Dict[str, Any]]:
        """查询相对位置的商品"""
        with self.lock:
            # 计算相对位置逻辑
            target_pos = None
            
            if direction == "上方":
                target_pos = reference_position + 4 if reference_position <= 4 else None
            elif direction == "下方":
                target_pos = reference_position - 4 if reference_position > 4 else None
            elif direction == "左边":
                if (reference_position - 1) % 4 > 0:
                    target_pos = reference_position - 1
            elif direction == "右边":
                if (reference_position - 1) % 4 < 3:
                    target_pos = reference_position + 1
            
            if target_pos and target_pos in self.world_map:
                item_info = self.world_map[target_pos]
                if item_info.status == ItemStatus.ON_SHELF:
                    return {
                        "position_id": target_pos,
                        "item_name": item_info.item_name,
                        "price": item_info.price,
                        "world_position": item_info.world_position
                    }
            return None
    
    def mark_item_grabbed(self, position_id: int) -> bool:
        """标记商品被抓取"""
        with self.lock:
            if position_id in self.world_map:
                self.world_map[position_id].status = ItemStatus.ON_GRIPPER
                return True
            return False
    
    def move_item_to_checkout(self, position_id: int) -> bool:
        """将商品移动到结算区"""
        with self.lock:
            if position_id in self.world_map:
                item_info = self.world_map[position_id]
                item_info.status = ItemStatus.ON_CHECKOUT_ZONE
                self.checkout_items.append(item_info.item_name)
                return True
            return False
    
    def get_checkout_summary(self) -> Dict[str, Any]:
        """获取结算区摘要"""
        with self.lock:
            items = []
            total_price = 0
            
            for item_name in self.checkout_items:
                if item_name in self.item_database:
                    price = self.item_database[item_name]["price"]
                    items.append({"name": item_name, "price": price})
                    total_price += price
            
            return {
                "items": items,
                "total_price": total_price,
                "item_count": len(items)
            }
    
    def get_inventory_announcement(self) -> str:
        """生成货架播报文本"""
        with self.lock:
            if not self.map_initialized:
                return "货架信息未初始化"
            
            layer1_items = []
            layer2_items = []
            
            for pos_id in range(1, 9):
                if pos_id in self.world_map:
                    item_name = self.world_map[pos_id].item_name
                    if pos_id <= 4:
                        layer1_items.append(item_name)
                    else:
                        layer2_items.append(item_name)
            
            announcement = f"第1层: {', '.join(layer1_items)}; 第2层: {', '.join(layer2_items)}"
            return announcement