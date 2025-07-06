# main.py - The Final Blueprint: Lean, Stream-based, and Researched

import time
import configparser

from controllers.arm_controller import ArmController
from controllers.rail_controller import RailController
from sensors.camera_thread import CameraThread
from intelligence.vision import VisionAnalyzer
from intelligence.speech import SpeechSystem
from intelligence.llm_parser import LLMParser
from utils.state import SharedState
from utils.calibration import Calibration
from utils.config import load_config

class GrabberSystem:
    """
    总指挥最终版。
    本设计基于一个核心理念：将复杂性封装在专门的模块中，
    main.py只负责调用高级API，清晰地编排比赛流程。
    """
    def __init__(self):
        """
        初始化所有系统组件。
        """
        print("SYSTEM BOOT: Initializing Grabber...")
        self.config = load_config('config.ini')
        self.robot_state = SharedState()
        self.calibration = Calibration()
        self.arm_ctrl = ArmController(self.config.connections, self.config.arm, self.config.gripper)
        self.rail_ctrl = RailController()
        self.vision_analyzer = VisionAnalyzer()
        self.speech_system = SpeechSystem()
        self.llm_parser = LLMParser()
        self.camera_thread = CameraThread()
        self.camera_thread.start()
        time.sleep(2)
        self.arm_ctrl.go_to_home_position()
        self.rail_ctrl.move_to(0)
        print("Grabber initialization complete. Welcome!")

    def run_main_loop(self):
        """
        启动主循环，等待指令。
        """
        while True:
            print("\n" + "="*50)
            print("Select Competition Task:")
            print("[A] Build World Map and Announce")
            print("[B] Recommend and Grab")
            print("[C] Select and Grab by Voice")
            print("[D] Tally and Settlement")
            print("[Q] Quit")
            choice = input("Enter your choice: ").upper()
            if choice == 'A':
                self.task_a_build_world_map_and_announce()
            elif choice == 'B':
                self.task_b_recommend_and_grab()
            elif choice == 'C':
                self.task_c_select_and_grab_by_voice()
            elif choice == 'D':
                self.task_d_tally_settlement()
            elif choice == 'Q':
                break
            else:
                print("Invalid choice, please try again.")
        self.shutdown()

    # ======================================================================
    #                          任务实现                  
    # ======================================================================

    def task_a_build_world_map_and_announce(self):
        """
        任务A: 通过YOLOv8流式视频分析构建世界地图并播报。
        """
        print("--- EXECUTING TASK A (Stream-based World Mapping) ---")
        # 1. [arm_ctrl] 机械臂移动到固定的、使得相机视野开阔的扫描姿态。
        self.arm_ctrl.move_to_scanning_pose()  # 高级API，机械臂到扫描位
        # 2. [vision] 启动YOLOv8的流式检测模式。
        print("Starting stream-based detection...")
        self.vision_analyzer.start_world_building_scan(self.robot_state, self.rail_ctrl)
        # 3. [rail_ctrl] 平滑地、非阻塞地移动导轨，完成整个扫描行程。
        self.rail_ctrl.move_to(self.config.getfloat('rail', 'scan_end_pos'), wait=True)
        # 4. [vision] 停止流式检测，并进行数据后处理。
        print("Scan complete. Processing data to build final world map...")
        world_map = self.vision_analyzer.stop_and_process_scan()
        # 5. [state] 将最终的世界地图存入共享状态，供所有后续任务使用。
        self.robot_state.update_item_world_map(world_map)
        print("World map successfully built and stored.")
        # 6. [rail_ctrl] 导轨返回结算区，为可能的后续任务做准备。
        self.rail_ctrl.move_to(0)
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
        # 1. [rail_ctrl] 导轨归零
        self.rail_ctrl.move_to(0)
        # 2. [arm_ctrl] 机械臂到结算扫描位
        self.arm_ctrl.move_to_checkout_scan_position()
        # 3. [vision] YOLOv8静态图片检测结算区商品
        image = self.robot_state.get_latest_image()
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
        最终版“查找-规划-抓取”辅助函数。
        极度高效，因为它不再“寻找”，而是直接“查询”。
        """
        print(f"Executing lookup-and-grab for: '{item_name}'")
        # 1. [state] 直接从世界地图中查询目标的3D世界坐标。
        target_world_pose = self.robot_state.get_item_pose_from_map(item_name)
        # 2. 如果查询失败，说明商品不在或已被取走，直接报告，无需移动硬件。
        if not target_world_pose:
            self.speech_system.say(f"抱歉，{item_name}似乎已经卖完了。")
            return False
        self.speech_system.say(f"好的，已在地图上定位到{item_name}，正在规划路径。")
        # 3. [arm_ctrl & rail_ctrl] 协同规划并移动到目标的“预备抓取位”。
        self.arm_ctrl.plan_and_move_to_pre_grasp_pose(target_world_pose, self.rail_ctrl)
        # 4. [vision] 在预备位置，进行一次性的精确位姿估计。
        print("In pre-grasp position. Performing fine-tuning perception...")
        latest_image = self.robot_state.get_latest_image()
        fine_tuned_pose = self.vision_analyzer.get_precise_grasp_pose(latest_image, target_world_pose)
        # 5. [arm_ctrl] 执行最终的、短距离的、精确的抓取序列。
        success = self.arm_ctrl.execute_final_grasp_sequence(fine_tuned_pose)
        # 6. [arm_ctrl & rail_ctrl] 抓取成功后，移动到放置区并释放。
        if success:
            self.speech_system.say(f"抓取{item_name}成功")
            self.move_to_dropoff_and_release()
        else:
            self.speech_system.say(f"抓取{item_name}失败，可能是最终定位或夹爪出现问题。")
        # 7. [arm_ctrl & rail_ctrl] 返回初始状态。
        self.arm_ctrl.go_to_home_position()
        self.rail_ctrl.move_to(0)
        return success

    def move_to_dropoff_and_release(self):
        """
        放置流程：导轨归零，机械臂到放置位并松开夹爪。
        """
        self.rail_ctrl.move_to(0)
        self.arm_ctrl.move_to_dropoff_and_release()

    def _generate_layered_announcement(self, world_map):
        """
        根据世界地图生成分层播报文本。
        具体实现可根据世界地图结构自定义。
        """
        # ... (与v2版相同) ...
        raise NotImplementedError("请根据世界地图结构实现分层播报。")

    def shutdown(self):
        """
        安全关闭所有系统。
        """
        print("System Shutting Down...")
        self.camera_thread.stop()
        self.arm_ctrl.disconnect()
        self.rail_ctrl.disconnect()
        print("Shutdown complete.")

# ======================================================================
#                      程序主入口                    
# ======================================================================
if __name__ == '__main__':
    grabber = GrabberSystem()
    try:
        # 为了快速测试，可以直接调用特定任务
        # grabber.task_a_build_world_map_and_announce()
        grabber.run_main_loop()
    except KeyboardInterrupt:
        print("\nManual shutdown requested.")
        grabber.shutdown()