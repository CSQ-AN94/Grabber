#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Grabber智能零售机器人系统主应用
优化版本：完善错误处理、日志系统、资源管理
"""

import sys
import time
import logging
import signal
import threading
from typing import Optional

# 核心模块导入
from controllers.arm_controller import ArmController
from controllers.ugv_controller import UGVController
from sensors.camera_thread import CameraThread
from intelligence.vision import VisionAnalyzer
from intelligence.speech_local import LocalSpeechSystem
from intelligence.gemini_agent import GeminiAgent
from intelligence.robot_tools import MockRobotTools, ToolRegistry
from utils.state import WorldState
from utils.calibration import Calibration
from utils.config import load_config, setup_logging, ConfigError

class GrabberSystem:
    """
    Grabber智能零售机器人系统主控制器
    优化版本：完善错误处理、资源管理和组件生命周期管理
    """
    
    def __init__(self, config_path: str = 'config.yaml'):
        """
        初始化系统组件
        """
        self.logger = logging.getLogger(__name__)
        self.config = None
        self.shutdown_event = threading.Event()
        
        # 组件引用
        self.world_state: Optional[WorldState] = None
        self.arm_ctrl: Optional[ArmController] = None
        self.ugv_ctrl: Optional[UGVController] = None
        self.camera_thread: Optional[CameraThread] = None
        self.vision_analyzer: Optional[VisionAnalyzer] = None
        self.speech_system: Optional[SpeechSystem] = None
        self.gemini_agent: Optional[GeminiAgent] = None
        self.robot_tools: Optional[MockRobotTools] = None
        self.tool_registry: Optional[ToolRegistry] = None
        self.calibration: Optional[Calibration] = None
        
        # 初始化系统
        self._initialize_system(config_path)
        
        # 设置信号处理
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """处理系统信号"""
        self.logger.info(f"收到信号 {signum}，准备安全关闭...")
        self.shutdown_event.set()
    
    def _initialize_system(self, config_path: str):
        """
        系统初始化流程，包含完整的错误处理
        """
        try:
            self.logger.info("开始初始化Grabber系统...")
            
            # 1. 加载配置
            self.logger.info("加载系统配置...")
            self.config = load_config(config_path)
            self.logger.info("配置加载成功")
            
            # 2. 初始化世界状态
            self.logger.info("初始化世界状态管理器...")
            self.world_state = WorldState()
            self.world_state.initialize_world_map(mock_data=True)
            self.logger.info("世界状态管理器初始化成功")
            
            # 3. 初始化硬件组件
            self.logger.info("初始化硬件...")
            self._initialize_hardware()
            
            # 4. 初始化智能组件
            self.logger.info("初始化AI组件...")
            self._initialize_ai_components()
            
            # 5. 初始化机器人工具
            self.logger.info("初始化机器人工具注册器...")
            self.robot_tools = MockRobotTools(self.world_state, self.config)
            self.tool_registry = ToolRegistry(self.robot_tools)
            
            # 6. 初始化Gemini Agent
            if hasattr(self.config.llm, 'gemini_api_key') and self.config.llm.gemini_api_key != 'YOUR_GEMINI_API_KEY_HERE':
                self.logger.info("初始化Gemini Live Agent...")
                self.gemini_agent = GeminiAgent(self.config.llm, self.config.agent, self.tool_registry)
                self.logger.info("Gemini Agent初始化成功")
            else:
                self.logger.warning("Gemini API密钥未配置，跳过Agent初始化")
            
            # 7. 系统就绪
            self.logger.info("Grabber系统初始化完成！")
            
        except ConfigError as e:
            self.logger.error(f"配置错误: {e}")
            raise SystemExit(1)
        except Exception as e:
            self.logger.error(f"系统初始化失败: {e}")
            self.shutdown()
            raise
    
    def _initialize_hardware(self):
        """初始化硬件"""
        try:
            # 初始化机械臂
            self.logger.info("初始化机械臂控制器...")
            self.arm_ctrl = ArmController(
                self.config.connections, 
                self.config.arm, 
                self.config.gripper
            )
            self.logger.info("机械臂初始化成功")
            
            # 初始化UGV
            self.logger.info("初始化UGV控制器...")
            self.ugv_ctrl = UGVController(self.config.ugv)
            self.logger.info("UGV初始化成功")
            
            # 初始化相机
            self.logger.info("初始化相机线程...")
            self.camera_thread = CameraThread(self.world_state, None)
            self.camera_thread.start()
            self.logger.info("相机线程启动成功")
            
            # 等待相机稳定
            self.logger.info("等待相机稳定...")
            time.sleep(3)
            if self.camera_thread.get_latest_frames()[0] is None:
                raise RuntimeError("相机无法获取图像帧")
            
            # 初始化标定
            self.logger.info("初始化手眼标定...")
            K, dist = self.camera_thread.get_camera_intrinsics()
            self.calibration = Calibration(self.config.calibration.T_end_to_camera, K, dist)
            self.logger.info("手眼标定初始化成功")
            
            # 移动到初始安全位置
            self.logger.info("移动到安全位置...")
            self.arm_ctrl.move_to_joints(self.config.arm.zero_pose)
            self.ugv_ctrl.move_to(0.0)
            self.logger.info("硬件就绪")
            
        except Exception as e:
            self.logger.error(f"硬件初始化失败: {e}")
            raise
    
    def _initialize_ai_components(self):
        """初始化AI组件"""
        try:
            # 初始化视觉分析器
            self.logger.info("初始化视觉分析器...")
            self.vision_analyzer = VisionAnalyzer()
            self.logger.info("视觉分析器初始化成功")
            
            # 初始化语音系统
            self.logger.info("初始化本地语音系统...")
            self.speech_system = LocalSpeechSystem(self.config.speech)
            self.logger.info("本地语音系统初始化成功")
            
        except Exception as e:
            self.logger.error(f"AI组件初始化失败: {e}")
            raise

    def run_main_loop(self):
        """
        主应用循环 - 处理比赛任务菜单
        """
        self.logger.info("启动主应用循环")
        
        try:
            while not self.shutdown_event.is_set():
                try:
                    self._show_main_menu()
                    choice = input("\n请选择任务 (A/B/C/D/V/Q): ").upper().strip()
                    
                    if choice == 'A':
                        self.task_a_inventory_scan()
                    elif choice == 'B':
                        self.task_b_image_recommendation()
                    elif choice == 'C':
                        self.task_c_voice_shopping()
                    elif choice == 'D':
                        self.task_d_checkout_calculation()
                    elif choice == 'V':
                        self.voice_interaction_mode()
                    elif choice == 'Q':
                        self.logger.info("用户选择退出")
                        break
                    else:
                        print("无效选择，请重试")
                        
                except KeyboardInterrupt:
                    self.logger.info("用户中断操作")
                    break
                except Exception as e:
                    self.logger.error(f"任务执行错误: {e}")
                    print(f"任务执行失败: {e}")
                    
        finally:
            self.shutdown()
    
    def _show_main_menu(self):
        """显示主菜单"""
        print("\n" + "="*60)
        print("Grabber 智能零售机器人系统")
        print("="*60)
        print("比赛任务：")
        print("  [A] 任务A: 库存扫描和播报")
        print("  [B] 任务B: 图像理解商品推荐")
        print("  [C] 任务C: 语音购物")
        print("  [D] 任务D: 结账计算")
        print("\n其他功能：")
        print("  [V] 语音交互模式")
        print("  [Q] 退出系统")
        print("="*60)
    
    def voice_interaction_mode(self):
        """语音交互模式"""
        if not self.gemini_agent:
            print("Gemini Agent未初始化，无法使用语音交互")
            return
            
        self.logger.info("进入语音交互模式")
        print("\n语音交互模式")
        print("说话与机器人交互，说'退出'结束对话")
        print("-" * 40)
        
        def command_handler(command):
            """处理Agent命令"""
            self.logger.info(f"收到命令: {command.action}")
            print(f"\n{command.response_text}")
        
        try:
            import asyncio
            asyncio.run(self.gemini_agent.start_interactive_session(command_handler))
        except Exception as e:
            self.logger.error(f"语音交互失败: {e}")
            print(f"语音交互失败: {e}")
    
    def task_a_inventory_scan(self):
        """任务A: 库存扫描和播报"""
        self.logger.info("开始执行任务A: 库存扫描和播报")
        
        try:
            # 使用机器人工具执行扫描
            if self.robot_tools:
                import asyncio
                result = asyncio.run(self.robot_tools.scan_inventory(announce=True))
                
                if result["success"]:
                    announcement = result["data"]["announcement"]
                    print(f"\n播报内容: {announcement}")
                    
                    # 如果语音系统可用，进行语音播报
                    if self.speech_system:
                        try:
                            if hasattr(self.speech_system, 'say') and callable(self.speech_system.say):
                                asyncio.run(self.speech_system.say(announcement))
                            else:
                                print("语音系统不支持TTS功能")
                        except Exception as e:
                            self.logger.warning(f"语音播报失败: {e}")
                    
                    self.logger.info("任务A执行成功")
                else:
                    self.logger.error(f"任务A执行失败: {result.get('message', '未知错误')}")
                    
            else:
                print("机器人工具未初始化")
                
        except Exception as e:
            self.logger.error(f"任务A执行异常: {e}")
            print(f"任务A执行失败: {e}")
    
    def task_b_image_recommendation(self):
        """任务B: 基于图像理解的商品推荐"""
        self.logger.info("开始执行任务B: 图像理解商品推荐")
        
        try:
            image_path = input("请输入图像文件路径: ").strip()
            if not image_path:
                print("未提供图像路径")
                return
                
            # 使用机器人工具执行推荐
            if self.robot_tools:
                import asyncio
                result = asyncio.run(self.robot_tools.recommend_item(image_description=image_path))
                
                if result["success"]:
                    recommended_item = result["data"]["recommended_item"]
                    reason = result["data"]["reason"]
                    
                    print(f"\n推荐商品: {recommended_item}")
                    print(f"推荐理由: {reason}")
                    
                    # 询问是否抓取
                    grab_choice = input("\n是否抓取推荐商品? (y/n): ").lower()
                    if grab_choice == 'y':
                        grab_result = asyncio.run(self.robot_tools.grab_item_by_name(recommended_item))
                        if grab_result["success"]:
                            print(f"成功抓取 {recommended_item}")
                        else:
                            print(f"抓取失败: {grab_result.get('message', '未知错误')}")
                    
                    self.logger.info("任务B执行成功")
                else:
                    self.logger.error(f"任务B执行失败: {result.get('message', '未知错误')}")
                    
            else:
                print("机器人工具未初始化")
                
        except Exception as e:
            self.logger.error(f"任务B执行异常: {e}")
            print(f"任务B执行失败: {e}")
    
    def task_c_voice_shopping(self):
        """任务C: 语音购物"""
        self.logger.info("开始执行任务C: 语音购物")
        
        if not self.gemini_agent:
            print("Gemini Agent未初始化，无法执行语音购物")
            return
            
        print("\n语音购物模式")
        print("请说出您想要的商品...")
        
        # 进入语音购物交互
        self.voice_interaction_mode()
    
    def task_d_checkout_calculation(self):
        """任务D: 结账计算"""
        self.logger.info("开始执行任务D: 结账计算")
        
        try:
            # 使用机器人工具执行结账计算
            if self.robot_tools:
                import asyncio
                result = asyncio.run(self.robot_tools.calculate_checkout())
                
                if result["success"]:
                    checkout_data = result["data"]
                    total_price = checkout_data["total_price"]
                    item_count = checkout_data["item_count"]
                    items = checkout_data["items"]
                    
                    print(f"\n结账摘要:")
                    print(f"商品数量: {item_count} 件")
                    
                    if items:
                        print("商品清单:")
                        for item in items:
                            print(f"  - {item['name']}: {item['price']} 元")
                        print(f"\n总计: {total_price} 元")
                    else:
                        print("结算区没有商品")
                    
                    # 语音播报结算结果
                    if self.speech_system and items:
                        try:
                            summary = result["message"]
                            import asyncio
                            asyncio.run(self.speech_system.say(summary))
                        except Exception as e:
                            self.logger.warning(f"语音播报失败: {e}")
                    
                    self.logger.info("任务D执行成功")
                else:
                    self.logger.error(f"任务D执行失败: {result.get('message', '未知错误')}")
                    
            else:
                print("机器人工具未初始化")
                
        except Exception as e:
            self.logger.error(f"任务D执行异常: {e}")
            print(f"任务D执行失败: {e}")

    # ======================================================================
    #                          任务实现                  
    # ======================================================================

    def task_a_build_world_map_and_announce(self):
        """
        任务A: 通过YOLOv8流式视频分析构建世界地图并播报。
        """
        print("--- EXECUTING TASK A (Stream-based World Mapping) ---")
        # 1. [arm_ctrl] 机械臂移动到固定的、使得相机视野开阔的扫描姿态。
        self.arm_ctrl.move_to_joints(self.config.arm.scanning_pose)
        # 2. [vision] 启动YOLOv8的流式检测模式。
        print("Starting stream-based detection...")
        self.vision_analyzer.start_world_building_scan(self.world_state, self.ugv_ctrl)
        # 3. [ugv_ctrl] 平滑地、非阻塞地移动UGV，完成整个扫描行程。
        self.ugv_ctrl.move_to(1.0, wait=True)
        # 4. [vision] 停止流式检测，并进行数据后处理。
        print("Scan complete. Processing data to build final world map...")
        world_map = self.vision_analyzer.stop_and_process_scan()
        # 5. [state] 将最终的世界地图存入共享状态，供所有后续任务使用。
        self.world_state.update_item_world_map(world_map)
        print("World map successfully built and stored.")
        # 6. [ugv_ctrl] UGV返回起始位置，为可能的后续任务做准备。
        self.ugv_ctrl.move_to(0)
        # 7. [speech] 根据这份精确的地图，生成分层播报。
        announcement = self._generate_layered_announcement(world_map)
        print(f"Announcement: {announcement}")
        self.speech_system.say(announcement)
        # 8. [arm_ctrl] 机械臂返回初始位置。
        self.arm_ctrl.go_to_home_position()

    def task_b_recommend_and_grab(self):
        """任务B: 商品推荐与抓取。流程简化为“LLM分析->查表->抓取”"""
        print("--- EXECUTING TASK B ---")
        image_path = input("Please provide the path to the recommendation image: ")
        # 1. [llm_parser] 调用大模型服务，分析图片并提取出明确的商品名称。
        target_item_name = self.llm_parser.get_item_recommendation_from_image(image_path)
        # 2. [Helper Function] 直接调用通用的抓取流程。
        if target_item_name:
            self.find_and_grab_item(target_item_name)
        else:
            self.speech_system.say("抱歉，我无法从图片中确定要推荐的具体商品。")

    def task_c_select_and_grab_by_voice(self):
        """任务C: 语音选购。流程简化为“语音->LLM解析->查表->抓取”"""
        print("--- EXECUTING TASK C ---")
        self.speech_system.say("您好，请问需要什么？")
        # 1. [speech & llm_parser] 听取并解析语音，获取结构化指令。
        command = self.llm_parser.parse_voice_command(self.speech_system.listen())
        # 2. [Helper Function] 直接调用通用的抓取流程。
        if command and command.get("action") == "fetch":
            self.find_and_grab_item(command.get("item_name"))
        else:
            self.speech_system.say("对不起，我没能理解您的指令。")

    def task_d_tally_settlement(self):
        """任务D: 商品结算。这是一个独立的流程，不依赖世界地图。"""
        # 1. [ugv_ctrl] UGV归零
        self.ugv_ctrl.move_to(0)
        # 2. [arm_ctrl] 机械臂到结算扫描位
        self.arm_ctrl.move_to_joints(self.config.arm.checkout_scan_pose)
        # 3. [vision] YOLOv8静态图片检测结算区商品
        image = self.camera_thread.get_latest_frames()[0]
        items = self.vision_analyzer.detect_items_in_checkout_area(image)
        # 4. [vision] 统计价格
        if not items:
            self.speech_system.say("结算区内没有检测到任何商品。")
            return
        total_price, item_details = self.vision_analyzer.calculate_total_price(items)
        summary = f"结算区有{item_details}。总计{total_price}元。"
        print(f"Checkout Summary: {summary}")
        self.speech_system.say(summary)

    # ======================================================================
    #                       核心辅助函数
    # ======================================================================
    def find_and_grab_item(self, item_name):
        """
        “查找-规划-抓取”辅助函数。
        """
        print(f"Executing lookup-and-grab for: '{item_name}'")
        # 1. [state] 直接从世界地图中查询目标的3D世界坐标。
        target_world_pose = self.world_state.get_item_pose_from_map(item_name)
        # 2. 如果查询失败，说明商品不在或已被取走，直接报告，无需移动硬件。
        if not target_world_pose:
            self.speech_system.say(f"抱歉，{item_name}似乎已经卖完了。")
            return False
        self.speech_system.say(f"好的，已在地图上定位到{item_name}，正在规划路径。")
        # 3. [arm_ctrl & ugv_ctrl] 协同规划并移动到目标的"预备抓取位"。
        self.arm_ctrl.plan_and_move_to_pre_grasp_pose(target_world_pose, self.ugv_ctrl)
        # 4. [vision] 在预备位置，进行一次性的精确位姿估计。
        print("In pre-grasp position. Performing fine-tuning perception...")
        latest_image = self.camera_thread.get_latest_frames()[0]
        fine_tuned_pose = self.vision_analyzer.get_precise_grasp_pose(latest_image, target_world_pose)
        # 5. [arm_ctrl] 执行最终的、短距离的、精确的抓取序列。
        success = self.arm_ctrl.execute_final_grasp_sequence(fine_tuned_pose)
        # 6. [arm_ctrl & ugv_ctrl] 抓取成功后，移动到放置区并释放。
        if success:
            self.speech_system.say(f"抓取{item_name}成功")
            self.move_to_dropoff_and_release()
        else:
            self.speech_system.say(f"抓取{item_name}失败，可能是最终定位或夹爪出现问题。")
        # 7. [arm_ctrl & ugv_ctrl] 返回初始状态。
        self.arm_ctrl.move_to_joints(self.config.arm.scanning_pose)
        self.ugv_ctrl.move_to(0)
        return success

    def move_to_dropoff_and_release(self):
        """
        放置流程：UGV归零，机械臂到放置位并松开夹爪。
        """
        self.ugv_ctrl.move_to(0)
        self.arm_ctrl.move_to_joints(self.config.arm.dropoff_pose)
        self.arm_ctrl.set_gripper_openness(1.0)  # 松开夹爪

    def _generate_layered_announcement(self, world_map):
        """
        根据世界地图生成分层播报文本。
        具体实现可根据世界地图结构自定义。
        """
        # ... (与v2版相同) ...
        raise NotImplementedError("请根据世界地图结构实现分层播报。")

    def shutdown(self):
        """
        安全关闭所有系统组件
        """
        self.logger.info("开始系统关闭流程...")
        self.shutdown_event.set()
        
        try:
            # 关闭相机线程
            if self.camera_thread and self.camera_thread.is_alive():
                self.logger.info("停止相机线程...")
                self.camera_thread.stop()
                self.camera_thread.join(timeout=5)
                if self.camera_thread.is_alive():
                    self.logger.warning("相机线程未能正常停止")
                else:
                    self.logger.info("相机线程已停止")
            
            # 停止Gemini Agent
            if self.gemini_agent:
                self.logger.info("停止Gemini Agent...")
                try:
                    import asyncio
                    asyncio.run(self.gemini_agent.stop_session())
                    self.logger.info("Gemini Agent已停止")
                except Exception as e:
                    self.logger.warning(f"停止Gemini Agent时出错: {e}")
            
            # 机械臂回到安全位置并断开连接
            if self.arm_ctrl:
                self.logger.info("机械臂回到安全位置...")
                try:
                    self.arm_ctrl.move_to_joints(self.config.arm.zero_pose)
                    self.arm_ctrl.set_gripper_openness(0.0)  # 松开夹爪
                    # 如果有断开连接的方法
                    if hasattr(self.arm_ctrl, 'disconnect'):
                        self.arm_ctrl.disconnect()
                    self.logger.info("机械臂安全关闭")
                except Exception as e:
                    self.logger.warning(f"机械臂关闭时出错: {e}")
            
            # UGV回到原点并断开连接
            if self.ugv_ctrl:
                self.logger.info("UGV回到原点...")
                try:
                    self.ugv_ctrl.move_to(0.0)
                    if hasattr(self.ugv_ctrl, 'disconnect'):
                        self.ugv_ctrl.disconnect()
                    self.logger.info("UGV安全关闭")
                except Exception as e:
                    self.logger.warning(f"UGV关闭时出错: {e}")
            
            self.logger.info("系统关闭完成")
            print("系统已安全关闭")
            
        except Exception as e:
            self.logger.error(f"系统关闭时发生错误: {e}")
            print(f"系统关闭时发生错误: {e}")

def main():
    """
    应用程序主入口点
    """
    try:
        # 检查Python版本
        if sys.version_info < (3, 8):
            print("需要Python 3.8或更高版本")
            sys.exit(1)
        
        # 加载配置并设置日志
        print("正在初始化系统...")
        config = load_config('config.yaml')
        setup_logging()
        
        logger = logging.getLogger(__name__)
        logger.info("="*60)
        logger.info("启动Grabber智能零售机器人系统")
        logger.info(f"运行环境: {config.system.environment}")
        logger.info(f"调试模式: {config.system.debug_mode}")
        logger.info("="*60)
        
        # 创建并运行系统
        grabber = GrabberSystem()
        grabber.run_main_loop()
        
    except KeyboardInterrupt:
        print("\n用户中断")
        logger.info("用户通过Ctrl+C中断程序")
    except ConfigError as e:
        print(f"配置错误: {e}")
        logger.error(f"配置错误: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"系统错误: {e}")
        logger.error(f"系统错误: {e}", exc_info=True)
        sys.exit(1)
    finally:
        print("感谢使用Grabber系统！")


if __name__ == "__main__":
    main()