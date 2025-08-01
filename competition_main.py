#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
8区域网格化抓取系统
两个模式: 1.测试抓取 2.数据收集
"""

import time
import sys
import os
import json
import joblib

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from controllers.arm_controller import ArmController
from intelligence.vision import VisionAnalyzer
from sensors.camera_thread import CameraThread

# ========== 内置配置 - 避免外部依赖 ==========

# 连接配置
CONNECTIONS_CONFIG = {
    "arm_ip": "192.168.1.18",
    "arm_port": 8080
}

# 机械臂配置
ARM_CONFIG = {
    "scanning_pose": [0.112,0,0.4505,3.142,1.571,0],
    "scanning_joints": [0,-90,90,0,90,0],
    "upper_pre_grasp_pose": [-0.290622,0.003243,0.60741,3.144,1.292,-0.008],
    "lower_pre_grasp_pose": [-0.354503,0.003511,0.390667,3.142,1.093,-0.01], # 最后一个pose为真正的预抓取姿势
    "pre_dropoff_joints_list": [[90,-90,90,0,90,0],
                                [90,60,120,0,-90,0]]
}

# 夹爪配置
GRIPPER_CONFIG = {
    "zero_speed": 25600,
    "init_speed": 51200, 
    "run_speed": 51200
}

# 视觉配置
VISION_CONFIG = {
    "model_path": "intelligence/models/7_19.pt"
}

# ========== 8区域网格化配置 ==========

SHELF_REGIONS = {
    "1-1": {
        "item_name": ""
    },
    "1-2": {
        "item_name": ""
    },
    "1-3": {
        "item_name": ""
    },
    "1-4": {
        "item_name": ""
    },
    "2-1": {
        "item_name": ""
    },
    "2-2": {
        "item_name": ""
    },
    "2-3": {
        "item_name": ""
    },
    "2-4": {
        "item_name": ""
    }
}

# 商品信息数据库
ITEM_DATABASE = {
    "牙膏": {"openness": 0.2, "price": 7},
    "雀巢咖啡": {"openness": 0.3, "price": 4},
    "洗发水": {"openness": 0.4,"price": 12},
    "可口可乐": {"openness": 0.3, "price": 3.5},
    "百事可乐": {"openness": 0.3, "price": 3.5},
    "橘子": {"openness": 0.5, "price": 1.5},
    "苹果": {"openness": 0.5, "price": 2},
    "纯牛奶": {"openness": 0.4, "price": 2.5},
    "农夫山泉矿泉水": {"openness": 0.3, "price": 2.5},
    "维达纸巾": {"openness": 0.5, "price": 4},
    "薯片": {"openness": 0.6, "price": 3.5},
    "恰恰瓜子": {"openness": 0.6, "price": 5},
    "奥利奥饼干": {"openness": 0.4, "price": 6},
    "娃哈哈 AD钙奶": {"openness": 0.4, "price": 5.5},
    "营养快线": {"openness": 0.4, "price": 6},
    "红牛": {"openness": 0.3, "price": 6}
}

# ========== 核心功能类 ==========

class SimpleArmConfig:
    def __init__(self, config_dict):
        for key, value in config_dict.items():
            setattr(self, key, value)

class RegionBasedGraspSystem:
    """
    基于区域的抓取系统
    在预抓取位姿使用相机2d信息，通过预训练的线性回归估计精细抓取需要的补偿x,y,z
    """
    
    def __init__(self, arm_controller, vision_analyzer, camera_thread):
        self.arm = arm_controller
        self.vision = vision_analyzer
        self.camera = camera_thread
        self.region_models = {}  # 存储每个区域的线性回归模型
        self.load_trained_models()
        self.dropoff_counter = 0
    
    def load_trained_models(self):
        """加载训练好的线性回归模型"""
        for region_id in SHELF_REGIONS.keys():
            model_path = f"models/{region_id}_offset_model.pkl"
            try:
                if os.path.exists(model_path):
                    self.region_models[region_id] = joblib.load(model_path)
                    print(f"✅ 加载区域模型: {region_id}")
                else:
                    print(f"⚠️  区域模型不存在: {region_id}")
            except Exception as e:
                print(f"❌ 加载模型失败 {region_id}: {e}")
    
    def _find_x_center_bbox(self, detections):
        """找到X轴最中间的bbox - 关键策略"""
        if not detections:
            return None
        
        # 按bbox中心的X坐标排序，找到最接近图像X轴中心的
        image_center_x = 320
        best_detection = min(detections,
                           key=lambda d: abs((d['box'][0] + d['box'][2]) / 2 - image_center_x))
        
        return best_detection
    
    def predict_grasp_offset(self, region_id, u, v):
        """预测抓取offset"""
        if region_id not in self.region_models:
            print(f"区域 {region_id} 的模型未训练，使用默认offset")
            return [-0.2,0,-0.06]  # 默认的offset
        
        model = self.region_models[region_id]
        try:
            offset = model.predict([[u, v]])[0]
            return offset.tolist()
        except Exception as e:
            print(f"预测offset失败: {e}")
            return [-0.1, 0.0, 0.0]
    
    def test_grasp_in_region(self, region_id):
        """测试指定区域的抓取"""
        print(f"\n测试区域 {region_id} 抓取")
        
        if region_id not in SHELF_REGIONS:
            return {"success": False, "message": f"未知区域: {region_id}"}
        on_up = region_id[0] == '1'
        try:
            # 1. 移动到预抓取位置
            pre_grasp_pose = ARM_CONFIG["upper_pre_grasp_pose"] if on_up else ARM_CONFIG["lower_pre_grasp_pose"]
            self.arm.movej_to_cartesian_pose(pre_grasp_pose)
            self.arm.set_gripper_openness(1.0)

            # 2. YOLO检测
            color_image, depth_image = self.camera.get_latest_frames()
            detections = self.vision.analyze_image(color_image, depth_image)
            center_bbox = self._find_x_center_bbox(detections)
            
            if not center_bbox:
                return {"success": False, "message": "未检测到目标"}
            
            # 3. 计算bbox中心和预测offset
            bbox = center_bbox['box']
            u = (bbox[0] + bbox[2]) // 2
            v = (bbox[1] + bbox[3]) // 2
            predicted_offset = self.predict_grasp_offset(region_id, u, v)
            
            print(f"📊 bbox中心: ({u}, {v})")
            print(f"🧮 预测offset: {predicted_offset}")
            
            # 4. 移动到最终抓取位置
            print(f"pre_grasp_pose: {pre_grasp_pose}")
            final_pose = [
                pre_grasp_pose[0] + predicted_offset[0],
                pre_grasp_pose[1] + predicted_offset[1],
                pre_grasp_pose[2] + predicted_offset[2],
                *pre_grasp_pose[3:]
            ]
            pre_final = [final_pose[0] + 0.08, *final_pose[1:]]
            print(f"final_pose: {final_pose}") 
            print(f"pre_final: {pre_final}")
            self.arm.movej_to_cartesian_pose(pre_final)
            self.arm.move_to_cartesian_pose(final_pose)
            time.sleep(0.5)
            
            # 5. 根据检测到的物品设置夹爪开合度
            print(center_bbox)
            detected_item = center_bbox['name']
            if detected_item in ITEM_DATABASE:
                openness = ITEM_DATABASE[detected_item]["openness"]
            else:
                openness = 0.4  # 默认开合度
                print(f"⚠️  未知物品 {detected_item}，使用默认开合度 {openness}")
            
            print(f"🤖 设置夹爪开合度: {openness} (物品: {detected_item})")
            self.arm.set_gripper_openness(openness)
            time.sleep(1)
            self.arm.move_to_cartesian_pose(pre_final)
            
            # 6. 放置
            self.arm.movej_to_cartesian_pose(ARM_CONFIG["scanning_pose"])
            for joints in ARM_CONFIG["pre_dropoff_joints_list"]:
                self.arm.move_to_joints(joints)
            self.arm.set_gripper_openness(1.0)
            
            print(f"✅ 区域 {region_id} 抓取完成")
            return {
                "success": True, 
                "region_id": region_id,
                "detected_item": detected_item,
                "bbox_center": (u, v), 
                "offset": predicted_offset,
                "openness": openness
            }
            
        except Exception as e:
            print(f"❌ 抓取失败: {e}")
            return {"success": False, "message": str(e)}
    
    def collect_region_data(self, on_up, num_samples=20):
        """收集指定区域的训练数据。使用前先手动拖教到预抓取位置"""
        print(f"\n🎓 收集数据，样本数: {num_samples}")
        
        training_data = []
        
        # 确保数据目录存在和移动到预抓取位置
        os.makedirs("training_data", exist_ok=True)
        pre_grasp_poses = ARM_CONFIG["upper_pre_grasp_poses"] if on_up else ARM_CONFIG["lower_pre_grasp_poses"]
        pg_pose = pre_grasp_poses[-2]
        self.arm.movej_to_cartesian_pose(pg_pose)
        time.sleep(2)
        
        for i in range(num_samples):
            print(f"\n📝 样本 {i+1}/{num_samples}")
            input("调整物品位置，按Enter继续...")
            
            # YOLO检测
            color_image, depth_image = self.camera.get_latest_frames()
            detections = self.vision.analyze_image(color_image, depth_image)
            center_bbox = self._find_x_center_bbox(detections)
            
            if not center_bbox:
                print("未检测到目标，跳过")
                continue
                
            # 获取bbox中心
            bbox = center_bbox['box']
            u = (bbox[0] + bbox[2]) // 2
            v = (bbox[1] + bbox[3]) // 2
            print(f"bbox中心: ({u}, {v})")
            
            # 示教
            input("拖动机械臂到抓取位置，按Enter记录...")
            
            # 记录位置并计算offset
            final_matrix = self.arm.get_base_to_end_pose_matrix()
            if final_matrix is None:
                continue
                
            offset = [
                final_matrix[0, 3] - pg_pose[0],
                final_matrix[1, 3] - pg_pose[1], 
                final_matrix[2, 3] - pg_pose[2]
            ]
            
            training_data.append({
                "u": int(u), "v": int(v),
                "offset_x": offset[0], "offset_y": offset[1], "offset_z": offset[2]
            })
            
            print(f"✅ offset: {offset}")
            self.arm.move_to_cartesian_pose(pg_pose)
        
        # 保存数据
        location = "upper" if on_up else "lower"
        filename = f"training_data/{location}_shelf_data.json"
        with open(filename, 'w') as f:
            json.dump(training_data, f, indent=2)
        
        print(f"✅ 已保存 {len(training_data)} 个样本到 {filename}")
        return True


# ========== 主程序 ==========

def main():
    """主程序 - 两个模式"""
    print("🤖 8区域网格化抓取系统")
    print("1. 测试抓取流程")
    print("2. 收集训练数据")
    
    mode = input("选择模式 (1/2): ").strip()
    
    if mode not in ["1", "2"]:
        print("无效选择")
        return
    
    # 初始化系统
    arm_config = SimpleArmConfig(ARM_CONFIG)
    gripper_config = SimpleArmConfig(GRIPPER_CONFIG) 
    conn_config = SimpleArmConfig(CONNECTIONS_CONFIG)
    
    cam_thread = CameraThread()
    arm = ArmController(conn_config, arm_config, gripper_config)
    analyzer = VisionAnalyzer(model_path=VISION_CONFIG["model_path"])
    
    system = RegionBasedGraspSystem(arm, analyzer, cam_thread)
    
    cam_thread.start()
    time.sleep(2)
    arm.movej_to_cartesian_pose(ARM_CONFIG["scanning_pose"])
    
    try:
        # 选择区域
        print("\n选择区域:")
        regions = list(SHELF_REGIONS.keys())
        for i, region_id in enumerate(regions, 1):
            print(f"{i}. {region_id}")
        
        choice = int(input("区域: ")) - 1
        region_id = regions[choice]
        
        if mode == "1":
            # 测试模式
            result = system.test_grasp_in_region(region_id)
            if result["success"]:
                print(f"✅ 测试成功: {result}")
            else:
                print(f"❌ 测试失败: {result}")
        
        elif mode == "2":
            # 数据收集模式  
            num_samples = int(input("样本数量(默认20): ") or "20")
            on_up = region_id[0] == '1'
            system.collect_region_data(on_up, num_samples)
        
    finally:
        cam_thread.stop()
        arm.movej_to_cartesian_pose(ARM_CONFIG["scanning_pose"])
        arm.move_to_joints(ARM_CONFIG["scanning_joints"])

if __name__ == "__main__":
    main()