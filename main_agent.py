#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grabber智能零售机器人 - Agent驱动的新主程序
支持真实硬件模式和Mock调试模式
"""

import time
import logging
import traceback

from intelligence.gemini_agent import GeminiAgent
from intelligence import robot_tools

def initialize_hardware_systems():
    """初始化所有硬件系统"""
    print("=== 初始化硬件系统 ===")

    from intelligence.vision import VisionAnalyzer
    from sensors.camera_thread import CameraThread
    from utils.config import load_config
    from controllers.arm_controller import ArmController
    
    app_config = load_config()
    
    # 1. 初始化视觉分析器
    print("1. 初始化YOLO视觉分析器...")
    try:
        model_path = app_config.vision.model_path
        vision_analyzer = VisionAnalyzer(model_path=model_path)
        print(f"YOLO模型加载成功: {model_path}")
    except Exception as e:
        print(f"YOLO模型加载失败: {e}")
        raise
    
    # 2. 初始化相机系统
    print("2. 初始化RealSense相机系统...")
    try:
        camera_thread = CameraThread(
            serial=app_config.camera.head_serial,
            width=app_config.camera.width,
            height=app_config.camera.height,
            fps=app_config.camera.fps,
        )
        camera_thread.start()
        print("相机线程启动成功")
        
        # 等待相机初始化完成
        print("等待相机初始化...")
        time.sleep(3)
        
        # 验证相机数据
        color_frame, _ = camera_thread.get_latest_frames()
        if color_frame is None:
            raise RuntimeError("相机数据获取失败")
        print(f"相机数据验证成功 (分辨率: {color_frame.shape})")
        
    except Exception as e:
        print(f"相机系统初始化失败: {e}")
        raise
    
    # 4. 初始化机械臂控制器
    print("4. 初始化Realman机械臂...")
    try:
        arm_controller = ArmController(app_config.connections, app_config.arm, app_config.gripper)
        
        # 验证机械臂状态
        _ = arm_controller.get_base_to_end_pose_matrix()
        print(f"机械臂状态验证成功")
        
    except Exception as e:
        print(f"机械臂初始化失败: {e}")
        raise
    
    print("=== 硬件系统初始化完成 ===")
    return vision_analyzer, camera_thread, arm_controller

def main():
    """主程序入口"""
    print("=== Grabber智能零售机器人 - Agent系统 ===")
    
    # 1. 选择工具模式
    print("\n请选择运行模式:")
    print("1. 无工具调用")
    print("2. 支持工具调用")
    mode_choice = input("选择模式 (1-2, 默认1): ").strip()
    enable_tools = mode_choice == "2"
    
    # 2. 如果启用工具模式，选择硬件模式
    use_real_hardware = False
    if enable_tools:
        print("\n请选择工具执行模式:")
        print("1. Mock调试模式 (调试Agent)")
        print("2. 真实硬件模式 (连接实际机器人，执行真实操作)")
        hardware_choice = input("选择模式 (1-2, 默认1): ").strip()
        use_real_hardware = hardware_choice == "2"
    
    # 3. 选择交互方式
    print("\n请选择交互方式:")
    print("1. 文本交互")
    print("2. 语音交互")
    voice_choice = input("选择交互方式 (1-2, 默认1): ").strip()
    enable_voice = voice_choice == "2"
    
    # 初始化硬件系统（仅在真实硬件模式下）
    vision_analyzer = None
    camera_thread = None
    arm_controller = None
    
    if use_real_hardware:
        try:
            vision_analyzer, camera_thread, arm_controller = initialize_hardware_systems()
        except Exception as e:
            print(f"\n硬件系统初始化失败: {e}")
            print("程序退出")
            return
    
    try:
        # 4. 配置robot_tools和初始化购物车
        robot_tools.clear_shopping_cart()
        print(f"[主程序] 购物车已初始化为空")
        
        if use_real_hardware:
            # 真实硬件模式：设置硬件组件并初始化
            robot_tools.set_hardware_components(
                vision_analyzer, camera_thread, arm_controller
            )
            robot_tools.init_real_hardware_mode()

            # 临时测试
            # robot_tools.scan_shelf()
            # robot_tools.execute_grab("红牛")
            # return 0
        
        else:
            # Mock模式：初始化预设商品
            robot_tools.init_mock_mode()
        
        # 5. 初始化Agent
        mode_text = '支持工具调用' if enable_tools else '无工具调用'
        hardware_text = '真实硬件' if use_real_hardware else 'Mock调试'
        voice_text = '语音交互' if enable_voice else '文本交互'
        
        print(f"\n=== 启动配置 ===")
        print(f"Agent模式: {mode_text}")
        if enable_tools:
            print(f"工具模式: {hardware_text}")
        print(f"交互方式: {voice_text}")
        print("================")
        
        agent = GeminiAgent(enable_tools=enable_tools, enable_voice=enable_voice, use_real_hardware=use_real_hardware)
        
        if agent.client is None or agent.chat is None:
            print("Agent初始化失败")
            return
        
        print(f"Agent初始化成功")
        
        # 6. 启动交互循环
        if enable_voice:
            print("\n=== 语音交互模式 ===")
            print("- 说 '小浦' 激活系统，机器人会播报'我在'并开始录音")
            print("- VAD智能检测语音结束，自动识别并发送给AI")
            print("- AI回复后语音播报，然后根据响应内容决定下一步")
            print("- 完整流程：唤醒词 → TTS响应 → VAD录音 → 识别 → AI处理 → TTS播报 → 状态决策")
            print("- 按Ctrl+C退出程序")
            
            # 启动语音系统
            agent.voice_manager.start_system()
            print("[Agent] 语音系统已启动，说 '小浦' 激活对话")
            
            try:
                print(f"\n[系统] 语音系统运行中...")
                print(f"[系统] 当前时间: {time.strftime('%H:%M:%S')}")
                print(f"[系统] 说 '小浦' 开始对话")
                
                while True:
                    time.sleep(1)  # 保持程序运行
            except KeyboardInterrupt:
                print("\n[系统] 程序被用户中断")
            finally:
                agent.voice_manager.stop_system()
        else:
            # 文本交互模式
            print("\n=== 文本交互模式 ===")
            print("- 直接输入文本与AI对话")
            if enable_tools:
                print("- 可以要求机器人扫描货架、抓取商品等")
            print("- 输入 'quit' 退出程序")
            
            while True:
                user_input = input("\n请输入: ").strip()
                if user_input.lower() in ['quit', 'exit', 'q']:
                    break
                
                if not user_input:
                    continue
                
                print("AI思考中...")
                
                # 处理文本输入
                result = agent.process_text(user_input)
                
                if result["success"]:
                    print(f"\nAI回复: {result['text']}")
                else:
                    print(f"\n处理失败: {result['error']}")
    
    except KeyboardInterrupt:
        print("\n用户中断，退出")
    except Exception as e:
        print(f"\n程序发生错误: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()