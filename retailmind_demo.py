#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grabber 智能零售机器人 - 集成视觉功能的并发优化版演示脚本
"""

import time
import sys
import os
import threading
import cv2
import numpy as np

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from utils.config import load_config
from controllers.arm_controller import ArmController
from intelligence.speech_local import LocalSpeechSystem
from intelligence.vision import VisionAnalyzer
from sensors.camera_thread import CameraThread
from utils.state import WorldState
import asyncio
# --- 全局配置 ---
try:
    app_config = load_config("config.ini")
except Exception as e:
    print(f"错误: 无法加载 config.ini。请确保文件存在且格式正确。 {e}")
    sys.exit(1)

# --- 商品抓取属性字典 ---
# 整合了所有与物品抓取相关的参数
ITEM_PROPERTIES = {
    "农夫山泉矿泉水": {
        "openness": 0.4,
        "pre_grasp_joints": [-16.578,112.739,-120.366,101.181,-93.032,-188.264], # 度
        "grasp_joints": [-41.644,115.8,-116.202,134.477,-87.154,-179.964], # 度
        "pre_grasp_pose": [-186.776,202.79,345.843,-2.673,1.541,-1.191], # 毫米，弧度
        "grasp_pose": [-178.204,295.786,346.932,0.102,1.516,1.723], # 毫米，弧度
        "dropoff_joints": [1.589,96.846,-8.109,101.008,-36.784,-93.576] # 度
    },
    "红牛": {
        "openness": 0.3,
        "pre_grasp_joints": [-1.64,120.052,-86.078,90.004,-86.24,-148.971],
        "grasp_joints": [-24.348,119.154,-83.624,113.839,-70.488,-148.973],
        "pre_grasp_pose":[-339.958,153.472,294.296,-0.766,1.495,0.812],
        "grasp_pose": [-329.805,285.531,293.966,-0.371,1.517,1.303],
        "dropoff_joints": [-2.824,94.878,26.895,76.503,-68.367,-50.739]
    },
    "可口可乐": {
        "openness": 0.4,
        "pre_grasp_joints": [-5.72,51.46,-23.465,93.944,-79.998,-152.419],
        "grasp_joints": [-26.065,58.77,-31.492,117.151,-70.367,-156.12], 
        "pre_grasp_pose":[-303.452,172.589,602.917,-0.08,1.449,1.534],
        "grasp_pose": [-294.183,288.828,604.159,0.188,1.42,1.954],
        "dropoff_joints": [10.611,121.605,-24.101,75.583,-36.712,-71.333],
    },
    "雀巢咖啡": {
        "openness": 0.3,
        "pre_grasp_joints": [89.771,24.44,-81.221,0.006,-30.847,-180.012],
        "grasp_joints": [-83.691,-4.213,67.262,166.723,-28.749,-170.523],
        "pre_grasp_pose":[-17.685,254.558,595.49,-1.72,1.538,-0.133],
        "grasp_pose": [-18.433,311.331,588.179,-2.017,1.526,-0.447],
        "dropoff_joints": [23.402,94.82,25.584,87.645,-82.586,-52.513],
    },
}


class VisionDisplayThread(threading.Thread):
    """
    一个专门用于在后台运行视觉分析并显示结果的线程。
    """
    def __init__(self, analyzer: VisionAnalyzer, state: WorldState, exit_event: threading.Event):
        super().__init__()
        self.analyzer = analyzer
        self.state = state
        self.exit_event = exit_event
        self.daemon = True

    def run(self):
        print("[VisionDisplayThread] Started.")
        window_name = "Live Vision Feed"
        cv2.namedWindow(window_name)
        
        while not self.exit_event.is_set():
            color_frame, depth_frame = self.state.get_latest_frames()
            color_frame = cv2.cvtColor(color_frame, cv2.COLOR_BGR2RGB)
            
            if color_frame is not None:
                # 1. 分析当前帧
                detections = self.analyzer.analyze_image(color_frame, depth_frame)
                # 2. 在帧上绘制检测结果
                frame_with_boxes = self.analyzer.draw_detections(color_frame, detections)
                # 3. 显示处理后的帧
                cv2.imshow(window_name, frame_with_boxes)

            # 按 'q' 键或接收到退出信号时退出
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.exit_event.set()
                break
        
        cv2.destroyAllWindows()
        print("[VisionDisplayThread] Stopped.")


def grasp(arm: ArmController, item_name: str):
    """
    根据物品名称执行抓取动作。

    该函数从 ITEM_PROPERTIES 字典中查找物品的抓取参数，
    并控制机械臂完成一系列动作：移动到预抓取位置、抓取、移动到放置位置。
    """
    print(f"\n>>> ACTION: Grasping '{item_name}'")
    
    item_props = ITEM_PROPERTIES.get(item_name)
    if not item_props:
        print(f"警告: 物品 '{item_name}' 的抓取属性未定义，无法抓取。")
        return

    pre_grasp_joints = item_props["pre_grasp_joints"]
    pre_grasp_pose = item_props["pre_grasp_pose"]
    grasp_joints = item_props["grasp_joints"]
    grasp_pose = item_props["grasp_pose"]
    openness = item_props["openness"]
    dropoff_joints = item_props["dropoff_joints"]

    # 使用 numpy 进行高精度单位转换（毫米 -> 米）
    pre_grasp_pose_np = np.array(pre_grasp_pose, dtype=np.float64)
    pre_grasp_pose_np[:3] /= 1000.0

    grasp_pose_np = np.array(grasp_pose, dtype=np.float64)
    grasp_pose_np[:3] /= 1000.0

    # 1. 移动到预抓取位置，同时打开夹爪
    arm.move_to_joints(pre_grasp_joints)
    arm.set_gripper_openness(1.0)

    # 2. 移动到精确抓取位置
    arm.move_to_cartesian_pose(grasp_pose_np)
    
    # 3. 闭合夹爪
    arm.set_gripper_openness(openness)
    
    # 4. 抬起物品
    arm.move_to_cartesian_pose(pre_grasp_pose_np)
    
    # 5. 移动到初始姿态
    arm.move_to_joints(app_config.arm.home_pose)

    # 6. 移动到预放置点
    arm.move_to_joints([44,87,-78,96,-88.5,-170])
    # 6. 移动到放置点
    arm.move_to_joints(dropoff_joints)
    
    # 7. 释放物品
    arm.set_gripper_openness(1.0)
    
    # 8. 返回初始姿态
    arm.move_to_joints(app_config.arm.home_pose)
    
    print(f"<<< ACTION: Grasp '{item_name}' finished.")


async def scan(arm: ArmController):
    arm.move_to_joints(app_config.arm.scanning_pose)


async def main_demo():
    """
    演示的主函数
    """
    print("--- Grabber Demo Script Initializing ---")
    
    exit_event = threading.Event()
    cam_thread = None
    vision_thread = None

    try:
        # 1. 初始化所有模块
        state = WorldState()
        cam_thread = CameraThread(state, None)
        
        arm = ArmController(app_config.connections, app_config.arm, app_config.gripper)
        tts = LocalSpeechSystem(app_config.speech)
        analyzer = VisionAnalyzer(model_path=app_config.vision.model_path)
        
        vision_thread = VisionDisplayThread(analyzer, state, exit_event)

        print("模块初始化成功 (Arm, TTS, Vision, Camera, State)")

        # 2. 启动后台线程
        cam_thread.start()
        vision_thread.start()
        print("后台线程 (Camera, Vision) 已启动。")
        
        # 等待相机稳定
        time.sleep(3)

        arm.move_to_joints(app_config.arm.home_pose)
        
        async def say(text):
            print(f"\n🤖 AI: {text}")
            try:
                result = await tts.say(text)
                if not result.get("success", False):
                    print(f"TTS错误: {result.get('message', '未知错误')}")
            except Exception as e:
                print(f"TTS播放失败: {e}")


        # ==================== DEMO开始 ====================
        
        await say("你好，这里是RetailMind智脑零售机器人，可以和我说您需要做什么，比如扫描商品，商品推荐，结算以及退换货等需求，都可以和我说；请问您需要什么服务？")

        # --- Task A: 扫描与播报 ---
        print("\n--- Task A: Inventory Scan ---")
        print("我想要扫描商品")
        time.sleep(5)
        
        await say("好的，正在扫描商品")
        scan(arm)
        
        await say("按货架从上到下，从左到右的顺序，第1层：可口可乐、营养快线、雀巢咖啡，薯片；第2层：红牛、农夫山泉矿泉水、橘子、百事可乐。")
        await say("货架上共有8样商品，请您任意选购，我会为您抓取。")

        # --- Task B: 图像理解与推荐 ---
        print("\n--- Task B: Image-based Recommendation ---")
        print("Human: 请进行根据我传入的图片进行商品推荐")
        time.sleep(7)

        await say("好的,请在终端输入图片路径")
        input("图片路径：")
        await say("好的，已识别到图片，正在分析。")
        time.sleep(2)
        await say("这张图像展示了一个看起来口渴的卡通男孩。他的舌头伸出，表情似乎在说:我好渴。在他的思考泡泡中，有一个装满水的玻璃杯，暗示他想要喝水。整体上，图像传达了男孩口渴想要喝水。")
        await say("为您推荐选购商品为：农夫山泉矿泉水。RetailMind智脑零售机器人开始抓取。")
        
        grasp(arm, "农夫山泉矿泉水")
        
        await say("抓取完成，目前购物车内商品为农夫山泉矿泉水，总价为2元。您还需要其他的商品么？我可以向您推荐。")

        # --- Task C & D: 连续购物与结算 ---
        print("\n--- Task C & D: Voice Shopping & Checkout ---")
        print("Human: 我还想要可口可乐")
        time.sleep(4)
        
        say("好的，RetailMind智脑零售机器人正在为您抓取可口可乐")
        grasp(arm, "可口可乐")
        await say("抓取完成，您还需要什么吗？")

        print("\nHuman: 我还想要它正下方那个")
        time.sleep(4)
        
        await say("可口可乐正下方的商品是红牛。RetailMind智脑零售机器人正在为您抓取红牛。")
        grasp(arm, "红牛")
        await say("抓取完成，您还需要什么商品么？")

        print("\nHuman: 有点困了，有什么推荐的？")
        time.sleep(4)

        await say("用户反应有点困了根据优先级原则，这个给您推荐雀巢咖啡或红牛，由于用户已经买了红牛，所以推荐雀巢咖啡。请问您需要嘛？")
        
        print("Human: 雀巢咖啡")
        time.sleep(3)

        await say("好的，正在为您抓取雀巢咖啡")
        grasp(arm, "雀巢咖啡")
        await say("抓取完成，还需要什么吗？")

        print("\nHuman: 不需要了，请问一共多少钱？")
        time.sleep(4)

        await say("正在前往结算区识别计算总金额，请稍后")
        arm.move_to_joints([57.921,106.916,-98.976,89.12,-124.49,-169.596])
        time.sleep(2)

        await say("您选购的商品有：农夫山泉矿泉水，可口可乐，红牛，雀巢咖啡。总金额为16元。")
        time.sleep(5)
        await say("付款成功，欢迎您下次光临！")

        arm.move_to_joints(app_config.arm.home_pose)
        print("\n--- Demo Finished ---")
        
        # --- Task E: 创新点：退换货 ---
        print("\nHuman:我要退换货")
        time.sleep(5)
        await say("你好这里是RetailMind智脑零售机器人，退换货服务专区，有什么可以帮到您？")
        print("\nHuman:我想要退货。")
        time.sleep(4)
        await say("好的请将商品放置在结算区")
        time.sleep(8)
        arm.move_to_joints([57.921,106.916,-98.976,89.12,-124.49,-169.596])
        await say("正在识别，请稍后。")
        await say("您放置的商品有红牛，农夫山泉，一共是8.5元，请问是否确定退货")
        print("Human：确定退货")
        time.sleep(5)
        await say("好的，正在帮您完成退货，退款成功。")
        await say("请问您还需要什么?")
        print("Human：不需要，谢谢。")
        time.sleep(3)
        await say("好的欢迎您下次光临")



    except Exception as e:
        print(f"\n演示过程中发生错误: {e}")
    finally:
        print("\n--- Shutting down ---")
        exit_event.set()
        if vision_thread:
            vision_thread.join(timeout=2)
        if cam_thread:
            cam_thread.stop()
            cam_thread.join(timeout=2)
        print("所有线程已停止。")


if __name__ == "__main__":
    try:
        asyncio.run(main_demo())
    except KeyboardInterrupt:
        print("\n用户中断，演示结束。")