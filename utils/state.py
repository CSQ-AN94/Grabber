# utils/state.py - 全局状态管理

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
    """存储单个物品信息的结构体"""
    item_name: str
    price: float
    description: Dict[str, Any]  # 描述信息，如形状、颜色、类别
    world_position: List[float]  # 世界坐标系下的6D位姿 [x, y, z, rx, ry, rz]
    status: ItemStatus = ItemStatus.ON_SHELF

class WorldState:
    """
    线程安全的世界状态管理器。
    - 维护机械臂、导轨、货架物品等所有动态信息。
    - 提供统一的接口供其他模块（如Agent、控制器）查询和更新状态。
    
    主要功能:
    1. 机器人状态管理: 跟踪关节角度、导轨位置、机械臂运动状态��
    2. 世界模型管理: 维护一个包含所有货架物品信息的“地图”。
    3. 业务逻辑: 处理物品抓取、放置、结账等核心流程。
    
    此类不直接与硬件交互，而是通过控制器和传感器线程（如CameraThread）接收更新。
    """
    
    def __init__(self):
        self.lock = threading.Lock()
        
        # --- 机器人状态 ---
        self.current_joint_angles = None
        self.is_arm_moving = False
        self.gripper_openness = None
        self.rail_position = 0.0
        
        # --- 世界模型 ---
        self.world_map: Dict[int, ItemInfo] = {}  # 位置ID -> 物品信息
        self.map_initialized = False
        self.checkout_items: List[str] = []  # 已放入结账区的物品列表
        
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
    
    # --- 机器人状态接口 ---

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
    
    def get_rail_position(self) -> float:
        """获取导轨当前位置"""
        with self.lock:
            return self.rail_position
    
    def set_rail_position(self, position: float):
        """更新导轨位置"""
        with self.lock:
            self.rail_position = position
    
    # --- 世界模型接口 ---
    def initialize_world_map(self, mock_data: bool = True):
        """初始化世界地图，目前使用mock数据"""
        with self.lock:
            if mock_data:
                # 模拟一个2层、每层4个位置的货架布局
                mock_layout = [
                    "可口可乐", "薯片", "农夫山泉矿泉水", "红牛",  # 第1层
                    "雀巢咖啡", "苹果", "奥利奥饼干", "橘子"      # 第2层
                ]
                
                for i, item_name in enumerate(mock_layout, 1):
                    if item_name in self.item_database:
                        item_info = self.item_database[item_name]
                        # 模拟物品在世界坐标系中的3D位置
                        mock_position = [
                            100 + (i % 4) * 150,  # x: 沿货架横向排列
                            200 if i <= 4 else 400,  # y: 第1层和第2层
                            300,  # z: 高度
                            0, 0, 0  # 姿态（暂不使用）
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
        """获取完整的世界地图，供Agent决策使用"""
        with self.lock:
            result = {}
            for pos_id, item_info in self.world_map.items():
                result[pos_id] = {
                    "item_name": item_info.item_name,
                    "price": item_info.price,
                    "description": item_info.description,
                    "world_position": item_info.world_position,
                    "status": item_info.status.value,
                    "layer": 1 if pos_id <= 4 else 2,  # 所在层
                    "shelf_position": ((pos_id - 1) % 4) + 1  # 在该层的位置 (1-4)
                }
            return result
    
    def query_item_by_name(self, item_name: str) -> Optional[Dict[str, Any]]:
        """根据物品名称查询货架上的物品信息"""
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
        """根据类别查询所有物品"""
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
        """查询某个位置旁边的物品（上/下/左/右）"""
        with self.lock:
            # 计算目标位置ID
            target_pos = None
            
            if direction == "下方":
                target_pos = reference_position + 4 if reference_position <= 4 else None
            elif direction == "上方":
                target_pos = reference_position - 4 if reference_position > 4 else None
            elif direction == "左侧":
                if (reference_position - 1) % 4 > 0:
                    target_pos = reference_position - 1
            elif direction == "右侧":
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
        """标记一个物品已被机械臂抓取"""
        with self.lock:
            if position_id in self.world_map:
                self.world_map[position_id].status = ItemStatus.ON_GRIPPER
                return True
            return False
    
    def move_item_to_checkout(self, position_id: int) -> bool:
        """将被抓取的物品移动到结账区"""
        with self.lock:
            if position_id in self.world_map:
                item_info = self.world_map[position_id]
                item_info.status = ItemStatus.ON_CHECKOUT_ZONE
                self.checkout_items.append(item_info.item_name)
                return True
            return False
    
    def get_checkout_summary(self) -> Dict[str, Any]:
        """获取结账区物品的摘要信息"""
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
        """生成用于语音播报的库存清单"""
        with self.lock:
            if not self.map_initialized:
                return "货架信息尚未初始化。"
            
            layer1_items = []
            layer2_items = []
            
            for pos_id in range(1, 9):
                if pos_id in self.world_map:
                    item_name = self.world_map[pos_id].item_name
                    if pos_id <= 4:
                        layer1_items.append(item_name)
                    else:
                        layer2_items.append(item_name)
            
            announcement = f"货架第一层有: {', '.join(layer1_items)}; 第二层有: {', '.join(layer2_items)}"
            return announcement
