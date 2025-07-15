# intelligence/robot_tools.py - Mock机器人工具（测试阶段）

import asyncio
import time
from typing import Dict, Any, Optional
from utils.state import WorldState
from utils.config import AppConfig

class MockRobotTools:
    """
    Mock机器人工具类 - 测试阶段使用预定义响应
    
    每个工具函数都返回标准格式：
    {
        "success": bool,
        "message": str,
        "data": Any,
        "execution_time": float
    }
    """
    
    def __init__(self, world_state: WorldState, config: AppConfig):
        self.world_state = world_state
        self.config = config
        
        # 初始化mock世界地图
        self.world_state.initialize_world_map(mock_data=True)
    
    async def scan_inventory(self, announce: bool = True) -> Dict[str, Any]:
        """任务A: 扫描货架商品"""
        start_time = time.time()
        
        # 模拟扫描过程
        await asyncio.sleep(2.0)  # 模拟扫描时间
        
        announcement = self.world_state.get_inventory_announcement()
        
        return {
            "success": True,
            "message": "货架扫描完成",
            "data": {
                "announcement": announcement,
                "world_map": self.world_state.get_world_map()
            },
            "execution_time": time.time() - start_time
        }
    
    async def recommend_item(self, image_description: str = "") -> Dict[str, Any]:
        """任务B: 商品推荐（预留接口）"""
        start_time = time.time()
        
        # 模拟图片理解过程
        await asyncio.sleep(1.5)
        
        # Mock推荐逻辑
        mock_recommendations = {
            "渴": "农夫山泉矿泉水",
            "饿": "薯片", 
            "困": "红牛",
            "甜": "奥利奥饼干"
        }
        
        recommended_item = "农夫山泉矿泉水"  # 默认推荐
        for keyword, item in mock_recommendations.items():
            if keyword in image_description:
                recommended_item = item
                break
        
        return {
            "success": True,
            "message": f"基于图片分析，为您推荐：{recommended_item}",
            "data": {
                "recommended_item": recommended_item,
                "reason": "根据图片内容分析得出的推荐"
            },
            "execution_time": time.time() - start_time
        }
    
    async def grab_item_by_name(self, item_name: str) -> Dict[str, Any]:
        """任务C1: 按名称抓取商品"""
        start_time = time.time()
        
        # 查询商品位置
        item_info = self.world_state.query_item_by_name(item_name)
        
        if not item_info:
            return {
                "success": False,
                "message": f"抱歉，{item_name}已售完或不存在",
                "data": None,
                "execution_time": time.time() - start_time
            }
        
        # 模拟抓取过程
        await asyncio.sleep(3.0)  # 模拟移动+抓取时间
        
        # 更新世界状态
        self.world_state.mark_item_grabbed(item_info["position_id"])
        self.world_state.move_item_to_checkout(item_info["position_id"])
        
        return {
            "success": True,
            "message": f"成功抓取{item_name}，已放置到结算区",
            "data": {
                "item_name": item_name,
                "position_id": item_info["position_id"],
                "price": item_info["price"]
            },
            "execution_time": time.time() - start_time
        }
    
    async def grab_item_by_position(self, reference_item: str, direction: str) -> Dict[str, Any]:
        """任务C2: 按相对位置抓取商品"""
        start_time = time.time()
        
        # 先找到参考商品的位置
        ref_info = self.world_state.query_item_by_name(reference_item)
        if not ref_info:
            return {
                "success": False,
                "message": f"找不到参考商品：{reference_item}",
                "data": None,
                "execution_time": time.time() - start_time
            }
        
        # 查询相对位置的商品
        target_info = self.world_state.query_relative_position(
            ref_info["position_id"], direction
        )
        
        if not target_info:
            return {
                "success": False,
                "message": f"{reference_item}的{direction}没有商品",
                "data": None,
                "execution_time": time.time() - start_time
            }
        
        # 模拟抓取过程
        await asyncio.sleep(3.0)
        
        # 更新世界状态
        self.world_state.mark_item_grabbed(target_info["position_id"])
        self.world_state.move_item_to_checkout(target_info["position_id"])
        
        return {
            "success": True,
            "message": f"成功抓取{target_info['item_name']}（{reference_item}的{direction}），已放置到结算区",
            "data": {
                "item_name": target_info["item_name"],
                "position_id": target_info["position_id"],
                "reference_item": reference_item,
                "direction": direction
            },
            "execution_time": time.time() - start_time
        }
    
    async def grab_item_by_semantic(self, category: str) -> Dict[str, Any]:
        """任务C3: 按语义信息抓取商品"""
        start_time = time.time()
        
        # 查询分类商品
        items = self.world_state.query_items_by_category(category)
        
        if not items:
            return {
                "success": False,
                "message": f"抱歉，没有找到{category}类商品",
                "data": None,
                "execution_time": time.time() - start_time
            }
        
        if len(items) == 1:
            # 只有一个商品，直接抓取
            item = items[0]
            await asyncio.sleep(3.0)
            
            self.world_state.mark_item_grabbed(item["position_id"])
            self.world_state.move_item_to_checkout(item["position_id"])
            
            return {
                "success": True,
                "message": f"为您选择了{item['item_name']}",
                "data": {
                    "item_name": item["item_name"],
                    "position_id": item["position_id"],
                    "category": category
                },
                "execution_time": time.time() - start_time
            }
        else:
            # 多个商品，需要用户选择
            item_names = [item["item_name"] for item in items]
            return {
                "success": True,
                "message": f"找到{category}有：{', '.join(item_names)}。请告诉我您要哪个？",
                "data": {
                    "available_items": items,
                    "category": category,
                    "requires_selection": True
                },
                "execution_time": time.time() - start_time
            }
    
    async def calculate_checkout(self) -> Dict[str, Any]:
        """任务D: 计算结算区总价"""
        start_time = time.time()
        
        # 模拟识别过程
        await asyncio.sleep(1.0)
        
        summary = self.world_state.get_checkout_summary()
        
        if summary["item_count"] == 0:
            return {
                "success": True,
                "message": "结算区没有商品",
                "data": summary,
                "execution_time": time.time() - start_time
            }
        
        # 生成详细清单
        item_list = ", ".join([f"{item['name']}({item['price']}元)" 
                              for item in summary["items"]])
        
        return {
            "success": True,
            "message": f"您选购的商品有：{item_list}。总价为{summary['total_price']}元",
            "data": summary,
            "execution_time": time.time() - start_time
        }
    
    async def move_to_position(self, position: str) -> Dict[str, Any]:
        """移动到指定位置"""
        start_time = time.time()
        
        position_map = {
            "scanning_area": "扫描区",
            "checkout_area": "结算区", 
            "dropoff_area": "放置区"
        }
        
        if position not in position_map:
            return {
                "success": False,
                "message": f"未知位置：{position}",
                "data": None,
                "execution_time": time.time() - start_time
            }
        
        # 模拟移动过程
        await asyncio.sleep(2.0)
        
        return {
            "success": True,
            "message": f"已移动到{position_map[position]}",
            "data": {"position": position},
            "execution_time": time.time() - start_time
        }
    
    # --- Agent查询工具 ---
    async def query_world_map(self) -> Dict[str, Any]:
        """查询完整世界地图"""
        return {
            "success": True,
            "message": "世界地图查询成功",
            "data": {"world_map": self.world_state.get_world_map()},
            "execution_time": 0.01
        }
    
    async def query_item_location(self, item_name: str) -> Dict[str, Any]:
        """查询特定商品位置"""
        item_info = self.world_state.query_item_by_name(item_name)
        
        if item_info:
            return {
                "success": True,
                "message": f"找到{item_name}的位置信息",
                "data": {"item_info": item_info},
                "execution_time": 0.01
            }
        else:
            return {
                "success": False,
                "message": f"{item_name}不在货架上",
                "data": None,
                "execution_time": 0.01
            }
    
    async def query_relative_position(self, reference_item: str, direction: str) -> Dict[str, Any]:
        """查询相对位置关系"""
        ref_info = self.world_state.query_item_by_name(reference_item)
        if not ref_info:
            return {
                "success": False,
                "message": f"找不到参考商品：{reference_item}",
                "data": None,
                "execution_time": 0.01
            }
        
        target_info = self.world_state.query_relative_position(
            ref_info["position_id"], direction
        )
        
        if target_info:
            return {
                "success": True,
                "message": f"{reference_item}的{direction}是{target_info['item_name']}",
                "data": {"target_info": target_info},
                "execution_time": 0.01
            }
        else:
            return {
                "success": False,
                "message": f"{reference_item}的{direction}没有商品",
                "data": None,
                "execution_time": 0.01
            }


# 工具函数注册器
class ToolRegistry:
    """工具函数注册器 - 为Agent提供可调用的工具"""
    
    def __init__(self, robot_tools: MockRobotTools):
        self.robot_tools = robot_tools
    
    def get_tool_definitions(self) -> list:
        """获取工具定义（用于Gemini Live API）"""
        return [
            {
                "function_declarations": [
                    {
                        "name": "scan_inventory",
                        "description": "扫描货架商品并播报位置",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "announce": {
                                    "type": "boolean",
                                    "description": "是否播报商品清单",
                                    "default": True
                                }
                            }
                        }
                    },
                    {
                        "name": "grab_item_by_name", 
                        "description": "根据商品名称抓取商品",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "item_name": {
                                    "type": "string",
                                    "description": "要抓取的商品名称"
                                }
                            },
                            "required": ["item_name"]
                        }
                    },
                    {
                        "name": "grab_item_by_position",
                        "description": "根据相对位置抓取商品",
                        "parameters": {
                            "type": "object", 
                            "properties": {
                                "reference_item": {
                                    "type": "string",
                                    "description": "参考商品名称"
                                },
                                "direction": {
                                    "type": "string",
                                    "description": "相对方向",
                                    "enum": ["上方", "下方", "左边", "右边"]
                                }
                            },
                            "required": ["reference_item", "direction"]
                        }
                    },
                    {
                        "name": "grab_item_by_semantic",
                        "description": "根据语义分类抓取商品",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "category": {
                                    "type": "string", 
                                    "description": "商品分类",
                                    "enum": ["水果", "饮料", "零食", "日用品"]
                                }
                            },
                            "required": ["category"]
                        }
                    },
                    {
                        "name": "calculate_checkout",
                        "description": "计算结算区商品总价",
                        "parameters": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "query_world_map",
                        "description": "查询完整的货架商品地图",
                        "parameters": {
                            "type": "object",
                            "properties": {}
                        }
                    },
                    {
                        "name": "query_item_location",
                        "description": "查询特定商品的位置信息",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "item_name": {
                                    "type": "string",
                                    "description": "要查询的商品名称"
                                }
                            },
                            "required": ["item_name"]
                        }
                    }
                ]
            }
        ]
    
    async def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """执行工具函数"""
        if hasattr(self.robot_tools, tool_name):
            tool_func = getattr(self.robot_tools, tool_name)
            return await tool_func(**parameters)
        else:
            return {
                "success": False,
                "message": f"未知工具：{tool_name}",
                "data": None,
                "execution_time": 0
            }