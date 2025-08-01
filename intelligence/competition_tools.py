#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
比赛工具函数库 - 用于测试Gemini Function Calling能力边界
提供4个核心工具函数，测试Gemini的工具调用顺序和依赖理解能力
"""

import asyncio
import logging
from typing import Dict, Any
from intelligence.test_world_state import get_test_world_state

logger = logging.getLogger(__name__)


class CompetitionTools:
    """
    比赛工具函数库 - 最小工具集测试
    
    设计目标：
    1. 测试Gemini是否能理解工具调用的依赖关系
    2. 测试Gemini对复杂语义的理解和推理能力
    3. 验证文本输出是否适合TTS播报
    """
    
    def __init__(self):
        self.world_state = get_test_world_state()
        self.logger = logging.getLogger(__name__)
    
    # === 工具函数1：货架扫描 ===
    async def scan_shelf_and_identify(self) -> Dict[str, Any]:
        """
        扫描货架并识别所有商品
        
        功能：驱动机械臂到扫描位置，使用视觉系统识别货架上的8个商品
        
        Returns:
            包含扫描结果的字典，适合TTS播报
        """
        try:
            self.logger.info("开始扫描货架...")
            
            # 模拟扫描过程（驱动机械臂 + 视觉识别）
            await asyncio.sleep(2)  # 模拟硬件操作时间
            
            # 调用世界状态的扫描模拟
            scanned_items = self.world_state.simulate_shelf_scan()
            
            # 生成适合TTS播报的结果
            layer1_items = scanned_items[:4]
            layer2_items = scanned_items[4:]
            
            announcement = (
                f"货架扫描完成。检测到{len(scanned_items)}个商品。"
                f"第一层有：{', '.join(layer1_items)}。"
                f"第二层有：{', '.join(layer2_items)}。"
            )
            
            self.logger.info(f"扫描完成，检测到{len(scanned_items)}个商品")
            
            return {
                "success": True,
                "message": announcement,
                "data": {
                    "total_items": len(scanned_items),
                    "layer1": layer1_items,
                    "layer2": layer2_items,
                    "all_items": scanned_items
                }
            }
            
        except Exception as e:
            error_msg = f"货架扫描失败: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "message": "货架扫描过程中发生错误，请稍后重试。",
                "error": error_msg
            }
    
    # === 工具函数2：世界状态查询 ===
    async def query_world_state(self, query_type: str, **params) -> Dict[str, Any]:
        """
        查询世界状态信息
        
        重要：这是获取最新货架信息的唯一途径，在执行抓取操作前必须先查询！
        
        Args:
            query_type: 查询类型
                - "full_layout": 查询完整货架布局
                - "by_name": 根据商品名称查询，需要参数 item_name
                - "by_category": 根据类别查询，需要参数 category
                - "relative_position": 查询相对位置，需要参数 reference_item, direction
                - "robot_status": 查询机器人状态
                - "checkout_summary": 查询结账区摘要
            **params: 查询参数
        
        Returns:
            查询结果字典
        """
        try:
            self.logger.info(f"查询世界状态: {query_type}, 参数: {params}")
            
            # 模拟查询延迟
            await asyncio.sleep(0.5)
            
            # 根据查询类型调用相应方法
            if query_type == "full_layout":
                result = self.world_state.query_full_layout()
                
            elif query_type == "by_name":
                item_name = params.get("item_name")
                if not item_name:
                    return {"success": False, "error": "缺少参数: item_name", "message": "查询失败，请指定商品名称。"}
                result = self.world_state.query_by_name(item_name)
                
            elif query_type == "by_category":
                category = params.get("category")
                if not category:
                    return {"success": False, "error": "缺少参数: category", "message": "查询失败，请指定商品类别。"}
                result = self.world_state.query_by_category(category)
                
            elif query_type == "relative_position":
                reference_item = params.get("reference_item")
                direction = params.get("direction")
                if not reference_item or not direction:
                    return {"success": False, "error": "缺少参数: reference_item 或 direction", "message": "查询失败，请指定参考商品和方向。"}
                result = self.world_state.query_relative_position(reference_item, direction)
                
            elif query_type == "robot_status":
                result = self.world_state.query_robot_status()
                
            elif query_type == "checkout_summary":
                result = self.world_state.query_checkout_summary()
                
            else:
                return {"success": False, "error": f"不支持的查询类型: {query_type}", "message": "查询失败，不支持该查询类型。"}
            
            # 为查询结果添加适合TTS的消息
            if result.get("success"):
                if query_type == "by_name" and "item_name" in result:
                    result["message"] = f"找到了{result['item_name']}，位于第{result['layer']}层第{result['shelf_position']}个位置，价格{result['price']}元。"
                elif query_type == "by_category" and "items" in result:
                    if result["count"] > 0:
                        items_list = [f"{item['item_name']}({item['price']}元)" for item in result["items"]]
                        result["message"] = f"找到{result['count']}个{result['category']}类商品：{', '.join(items_list)}。"
                    else:
                        result["message"] = f"货架上没有{result.get('category', '')}类商品。"
                elif query_type == "relative_position" and "target_item_name" in result:
                    result["message"] = f"{result['reference_item']}的{result['direction']}是{result['target_item_name']}，价格{result['target_price']}元。"
                elif query_type == "full_layout" and "layer1" in result:
                    result["message"] = f"货架共有{result['total_items']}个商品。第一层：{', '.join(result['layer1'])}。第二层：{', '.join(result['layer2'])}。"
                elif query_type == "checkout_summary":
                    if result["item_count"] > 0:
                        items_str = ', '.join([f"{item['name']}({item['price']}元)" for item in result["items"]])
                        result["message"] = f"结账区有{result['item_count']}个商品：{items_str}，总价{result['total_price']}元。"
                    else:
                        result["message"] = "结账区暂无商品。"
                elif query_type == "robot_status":
                    status = "忙碌" if result["robot_busy"] else "空闲"
                    scan_status = "已扫描" if result["shelf_scanned"] else "未扫描"
                    result["message"] = f"机器人状态：{status}，货架{scan_status}，结账区有{result['checkout_items_count']}个商品。"
            
            return result
            
        except Exception as e:
            error_msg = f"查询世界状态失败: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "message": "查询过程中发生错误，请稍后重试。",
                "error": error_msg
            }
    
    # === 工具函数3：抓取和放置 ===
    async def grasp_and_drop(self, position_id: int, item_name: str) -> Dict[str, Any]:
        """
        抓取指定位置的商品并放置到结账区
        
        重要警告：
        1. 调用此函数前必须先用 query_world_state 确认商品信息！
        2. position_id 和 item_name 必须通过查询获得，不能猜测！
        3. 确保商品确实在货架上且可抓取！
        
        Args:
            position_id: 商品在货架上的位置ID (1-8)
            item_name: 商品名称（必须与位置上的实际商品匹配）
        
        Returns:
            抓取操作结果
        """
        try:
            self.logger.info(f"开始抓取商品: 位置{position_id}, 商品{item_name}")
            
            # 模拟抓取过程（机械臂运动 + 抓取 + 放置）
            await asyncio.sleep(3)  # 模拟硬件操作时间
            
            # 执行抓取和放置
            result = self.world_state.execute_grasp_and_drop(position_id, item_name)
            
            # 生成适合TTS播报的消息
            if result["success"]:
                result["message"] = f"成功抓取{result['item_name']}，价格{result['price']}元，已放入结账区。"
            else:
                # 保持原有错误信息，但确保适合语音播报
                pass
            
            return result
            
        except Exception as e:
            error_msg = f"抓取商品失败: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "message": "抓取过程中发生错误，请稍后重试。",
                "error": error_msg
            }
    
    # === 工具函数4：结账摘要 ===
    async def get_checkout_summary(self) -> Dict[str, Any]:
        """
        获取结账区商品摘要
        
        功能：统计结账区所有商品，计算总价，生成结账单
        
        Returns:
            结账摘要信息
        """
        try:
            self.logger.info("获取结账摘要...")
            
            # 模拟处理时间
            await asyncio.sleep(1)
            
            # 获取结账摘要
            result = self.world_state.query_checkout_summary()
            
            # 生成适合TTS播报的消息
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
            
            return result
            
        except Exception as e:
            error_msg = f"获取结账摘要失败: {str(e)}"
            self.logger.error(error_msg)
            return {
                "success": False,
                "message": "获取结账信息时发生错误，请稍后重试。",
                "error": error_msg
            }
    
    # === 工具定义（用于注册到GeminiAgent）===
    def get_tool_definitions(self) -> list:
        """
        获取所有工具函数的定义，用于注册到GeminiAgent
        特别注意工具描述中的依赖关系说明
        """
        return [
            {
                "name": "scan_shelf_and_identify",
                "description": "扫描货架并识别所有商品。这是了解货架布局的第一步，会更新系统的商品信息。",
                "function": self.scan_shelf_and_identify,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            },
            {
                "name": "query_world_state", 
                "description": """查询世界状态信息。这是获取实时货架信息的关键工具。支持多种查询类型：
                - full_layout: 查询完整货架布局
                - by_name: 根据商品名称查询位置信息
                - by_category: 根据类别查询（饮料、零食、水果、日用品）  
                - relative_position: 查询相对位置的商品
                - robot_status: 查询机器人状态
                - checkout_summary: 查询结账区商品
                重要：在执行抓取前必须先查询确认商品位置！""",
                "function": self.query_world_state,
                "parameters": {
                    "type": "object", 
                    "properties": {
                        "query_type": {
                            "type": "string",
                            "description": "查询类型",
                            "enum": ["full_layout", "by_name", "by_category", "relative_position", "robot_status", "checkout_summary"]
                        },
                        "item_name": {
                            "type": "string",
                            "description": "商品名称（query_type为by_name时使用）"
                        },
                        "category": {
                            "type": "string", 
                            "description": "商品类别（query_type为by_category时使用）：饮料、零食、水果、日用品"
                        },
                        "reference_item": {
                            "type": "string",
                            "description": "参考商品名称（query_type为relative_position时使用）"
                        },
                        "direction": {
                            "type": "string",
                            "description": "方向（query_type为relative_position时使用）：上方、下方、左侧、右侧"
                        }
                    },
                    "required": ["query_type"]
                }
            },
            {
                "name": "grasp_and_drop",
                "description": """抓取指定商品并放置到结账区。⚠️重要：调用前必须先用query_world_state确认商品信息！
                position_id和item_name必须通过查询获得，不能猜测！""",
                "function": self.grasp_and_drop,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "position_id": {
                            "type": "integer",
                            "description": "商品在货架上的位置ID (1-8，必须通过查询获得）"
                        },
                        "item_name": {
                            "type": "string", 
                            "description": "商品名称（必须与位置上的实际商品匹配）"
                        }
                    },
                    "required": ["position_id", "item_name"]
                }
            },
            {
                "name": "get_checkout_summary",
                "description": "获取结账区商品摘要，包括商品列表、总价和数量统计。",
                "function": self.get_checkout_summary,
                "parameters": {
                    "type": "object",
                    "properties": {},
                    "required": []
                }
            }
        ]


# 全局工具实例
_competition_tools = None

def get_competition_tools() -> CompetitionTools:
    """获取比赛工具实例（单例模式）"""
    global _competition_tools
    if _competition_tools is None:
        _competition_tools = CompetitionTools()
    return _competition_tools