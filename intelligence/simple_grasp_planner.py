"""
简单抓取规划器
基于2.5D几何约束的实用抓取点估计

核心理念：
- 避免复杂点云处理和平面拟合
- 使用bbox中心的单点深度值
- 从config.yaml读取预定义的抓取策略
- 直接计算世界坐标系下的抓取姿态
- 为货架场景优化，假设物体基本垂直站立
"""

import numpy as np
from typing import Optional, Dict, Any, Tuple
from utils.config import ItemsConfig
from utils.calibration import Calibration
from intelligence.vision import VisionAnalyzer


class SimpleGraspPlanner:
    """
    简单抓取规划器 - 2.5D几何约束方法
    
    在机械臂到达预抓取位姿后使用，选择画面中心的物体进行抓取
    使用依赖注入模式，传入构造好的实例，参考ArmController的实现
    
    架构说明：
    - 标定系统基于末端法兰坐标系（不知道夹爪存在）
    - 本规划器估算TCP应达到的位姿，然后补偿夹爪长度
    - 输出给move_to_cartesian_pose()的是末端法兰位姿
    """
    
    def __init__(self, 
                 items_config: ItemsConfig,
                 calibration: Calibration,
                 vision_analyzer: VisionAnalyzer,
                 gripper_length: float = 0.15):
        """
        初始化抓取规划器
        
        Args:
            items_config: 物品配置实例
            calibration: 标定实例，用于坐标转换（基于末端法兰）
            vision_analyzer: 视觉分析器实例
            gripper_length: 夹爪长度，单位：米（TCP相对末端法兰的Z轴偏移）
        """
        self.items_config = items_config
        self.calibration = calibration 
        self.vision_analyzer = vision_analyzer
        self.gripper_length = gripper_length  # 夹爪长度补偿
        
        print(f"[简单抓取规划器] 初始化完成，支持 {len(self.items_config.get_all_items())} 种物品")
        print(f"[简单抓取规划器] 支持的物品: {', '.join(self.items_config.get_all_items())}")
        print(f"[简单抓取规划器] 夹爪长度补偿: {self.gripper_length:.3f}m")
    
    def estimate_grasp(self, 
                      color_image: np.ndarray,
                      depth_image: np.ndarray,
                      arm_current_pose: np.ndarray,
                      ugv_position: float = 0.0,
                      expected_item_name: Optional[str] = None) -> Dict[str, Any]:
        """
        估算抓取点 - 核心方法
        
        Args:
            color_image: BGR彩色图像
            depth_image: 深度图像（单位：米）
            arm_current_pose: 机械臂当前位姿矩阵，用于坐标转换
            ugv_position: UGV当前位置（米）
            expected_item_name: 期望抓取的物体名称（仅用于日志）
            
        Returns:
            Dict: 包含抓取位姿信息的字典
            {
                "success": bool,
                "message": str,
                "grasp_pose": [x, y, z, roll, pitch, yaw],  # 末端法兰位姿（已补偿夹爪长度）
                "gripper_openness": float,  # 推荐夹爪张开度
                "target_object": str,    # 实际检测到的物体类别
                "confidence": float,     # 检测置信度
                "price": float,          # 物品价格
                "debug_info": Dict       # 调试信息
            }
        """
        print(f"[简单抓取规划器] 开始估算抓取点，期望物体: {expected_item_name}")
        
        try:
            # 1. 使用视觉分析器进行目标检测
            detections = self.vision_analyzer.analyze_image(color_image, depth_image)
            
            if not detections:
                return {
                    "success": False,
                    "message": "未检测到任何物体",
                    "error": "No objects detected"
                }
            
            print(f"[简单抓取规划器] 检测到 {len(detections)} 个物体")
            
            # 2. 选择画面中心最近的检测结果
            best_detection = self._select_center_object(color_image, detections)
            
            if best_detection is None:
                return {
                    "success": False,
                    "message": "无法选择目标物体",
                    "error": "Cannot select target object"
                }
                
            target_class = best_detection['name']
            confidence = best_detection['confidence']
            box = best_detection['box']
            
            print(f"[简单抓取规划器] 选择目标: {target_class} (置信度: {confidence:.3f})")
            
            # 3. 获取bbox中心点的像素坐标和深度值
            pixel_coords, center_depth = self._get_bbox_center_depth(depth_image, box)
            
            if center_depth <= 0:
                return {
                    "success": False,
                    "message": "无法获取有效深度信息",
                    "error": "Invalid depth data"
                }
            
            print(f"[简单抓取规划器] 目标位置: 像素{pixel_coords}, 深度: {center_depth:.3f}m")
            
            # 4. 使用标定模块进行像素坐标转世界坐标
            world_point = self.calibration.transform_pixel_to_world(
                pixel_coords, 
                center_depth, 
                arm_current_pose,
                ugv_position
            )
            
            if world_point is None:
                return {
                    "success": False,
                    "message": "坐标转换失败",
                    "error": "Coordinate transformation failed"
                }
            
            print(f"[简单抓取规划器] 世界坐标: [{world_point[0]:.3f}, {world_point[1]:.3f}, {world_point[2]:.3f}]")
            
            # 5. 从配置加载抓取策略并应用微调
            item_config = self._get_item_config(target_class)
            
            if item_config is None:
                return {
                    "success": False,
                    "message": f"不支持的物体类别: {target_class}",
                    "error": f"Unsupported object class: {target_class}"
                }
            
            # 计算最终抓取位姿
            grasp_pose = self._compute_final_grasp_pose(world_point, item_config)
            
            print(f"[简单抓取规划器] 最终末端法兰位姿: [{grasp_pose[0]:.3f}, {grasp_pose[1]:.3f}, {grasp_pose[2]:.3f}, "
                  f"{grasp_pose[3]:.3f}, {grasp_pose[4]:.3f}, {grasp_pose[5]:.3f}]")
            print(f"[简单抓取规划器] 夹爪张开度: {item_config.gripper_openness:.3f}, 价格: ￥{item_config.price}")
            
            # 6. 返回结果
            return {
                "success": True,
                "message": f"成功估算抓取点，目标: {target_class}",
                "grasp_pose": grasp_pose,
                "gripper_openness": item_config.gripper_openness,  # 改为gripper_openness
                "target_object": target_class,
                "confidence": confidence,
                "price": item_config.price,
                "debug_info": {
                    "expected_item": expected_item_name,
                    "detected_item": target_class,
                    "bbox": box,
                    "pixel_coords": pixel_coords,
                    "depth_m": center_depth,
                    "world_point": world_point.tolist(),
                    "item_config": {
                        "z_offset": item_config.z_offset,
                        "roll": item_config.roll,
                        "pitch": item_config.pitch,
                        "yaw": item_config.yaw,
                        "gripper_openness": item_config.gripper_openness,  # 改为gripper_openness
                        "price": item_config.price
                    },
                    "all_detections": len(detections),
                    "ugv_position": ugv_position
                }
            }
            
        except Exception as e:
            print(f"[简单抓取规划器] 错误: {e}")
            import traceback
            traceback.print_exc()
            return {
                "success": False,
                "message": f"估算抓取点时发生错误: {str(e)}",
                "error": str(e)
            }
    
    def _select_center_object(self, color_image: np.ndarray, detections: list) -> Optional[Dict]:
        """选择画面中心最近的检测结果"""
        image_center_x = color_image.shape[1] // 2
        image_center_y = color_image.shape[0] // 2
        
        best_detection = None
        min_distance_to_center = float('inf')
        
        for detection in detections:
            box = detection['box']  # [x1, y1, x2, y2]
            bbox_center_x = (box[0] + box[2]) // 2
            bbox_center_y = (box[1] + box[3]) // 2
            
            # 计算到图像中心的距离
            distance = ((bbox_center_x - image_center_x) ** 2 + 
                       (bbox_center_y - image_center_y) ** 2) ** 0.5
            
            if distance < min_distance_to_center:
                min_distance_to_center = distance
                best_detection = detection
        
        return best_detection
    
    def _get_bbox_center_depth(self, depth_image: np.ndarray, box: list) -> Tuple[Tuple[int, int], float]:
        """获取bbox中心点的像素坐标和深度值"""
        bbox_center_x = (box[0] + box[2]) // 2
        bbox_center_y = (box[1] + box[3]) // 2
        center_depth = depth_image[bbox_center_y, bbox_center_x]
        
        # 如果中心点深度无效，在3x3区域内寻找有效深度
        if center_depth <= 0:
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    ny, nx = bbox_center_y + dy, bbox_center_x + dx
                    if (0 <= nx < depth_image.shape[1] and 
                        0 <= ny < depth_image.shape[0]):
                        depth_val = depth_image[ny, nx]
                        if depth_val > 0:
                            center_depth = depth_val
                            break
                if center_depth > 0:
                    break
        
        return (bbox_center_x, bbox_center_y), center_depth
    
    def _compute_final_grasp_pose(self, world_point: np.ndarray, item_config) -> list:
        """
        计算最终抓取位姿（末端法兰位姿）
        
        架构：
        1. 首先计算TCP应达到的理想抓取位姿
        2. 然后沿着工具坐标系Z轴负方向偏移gripper_length
        3. 返回末端法兰应达到的位姿，使得TCP到达理想抓取点
        """
        # 步骤1：计算TCP理想抓取位姿
        tcp_x = world_point[0]
        tcp_y = world_point[1] 
        tcp_z = world_point[2] + item_config.z_offset  # 应用Z轴偏移
        tcp_roll = item_config.roll
        tcp_pitch = item_config.pitch
        tcp_yaw = item_config.yaw
        
        # 步骤2：构造TCP到末端法兰的变换矩阵
        # TCP相对末端法兰向前(+Z)偏移gripper_length，所以末端法兰向后(-Z)偏移
        from scipy.spatial.transform import Rotation
        
        # TCP的旋转矩阵
        tcp_rotation = Rotation.from_euler('ZYX', [tcp_yaw, tcp_pitch, tcp_roll]).as_matrix()
        
        # 在TCP坐标系下，末端法兰位于TCP的-Z方向gripper_length距离处
        tcp_to_end_offset = np.array([0, 0, -self.gripper_length])
        
        # 将偏移向量转换到世界坐标系
        world_offset = tcp_rotation @ tcp_to_end_offset
        
        # 步骤3：计算末端法兰位姿
        end_x = tcp_x + world_offset[0]
        end_y = tcp_y + world_offset[1] 
        end_z = tcp_z + world_offset[2]
        end_roll = tcp_roll  # 姿态保持不变
        end_pitch = tcp_pitch
        end_yaw = tcp_yaw
        
        print(f"[TCP补偿] TCP位姿: [{tcp_x:.3f}, {tcp_y:.3f}, {tcp_z:.3f}]")
        print(f"[TCP补偿] 末端位姿: [{end_x:.3f}, {end_y:.3f}, {end_z:.3f}] (补偿: {self.gripper_length:.3f}m)")
        
        return [end_x, end_y, end_z, end_roll, end_pitch, end_yaw]
    
    def _get_item_config(self, object_class: str):
        """获取指定物体的配置"""
        return self.items_config.get_item_config(object_class)
    
    def get_supported_objects(self) -> list:
        """获取支持的物体类别列表"""
        return self.items_config.get_all_items()
    
    def get_item_price(self, item_name: str) -> Optional[float]:
        """获取物品价格"""
        return self.items_config.get_item_price(item_name)
    
    def get_all_item_prices(self) -> Dict[str, float]:
        """获取所有物品价格"""
        prices = {}
        for item_name in self.items_config.get_all_items():
            price = self.get_item_price(item_name)
            if price is not None:
                prices[item_name] = price
        return prices