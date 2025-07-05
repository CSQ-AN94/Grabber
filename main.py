# main.py - 项目蓝图与主调度器
# =============================================
# 生产者-消费者架构：
# - sensors/camera_thread.py: 生产者线程，采集相机数据，写入 state.py
# - utils/state.py: 线程安全的世界状态仓库，所有模块通过它交换数据
# - main.py: 唯一消费者/指挥官，从 state 获取世界状态，调度 controllers/intelligence
# - controllers/: 所有硬件操作的唯一入口（机械臂、夹爪、导轨等）
# - intelligence/: 所有AI/推理/感知的唯一入口（视觉、语音、LLM等）
# =============================================

from controllers.arm_controller import ArmController
from controllers.rail_controller import RailController  # 预留接口
from intelligence.vision import VisionSystem
from intelligence.speech import SpeechSystem
from intelligence.llm_parser import LLMParser
from sensors.camera_thread import CameraThread
from utils.state import SystemState
from utils.calibration import Calibration
import configparser
import time

class GrabberSystem:
    """
    总指挥类：唯一的消费者，负责调度所有子系统。
    只与 state.py 交互，不直接操作硬件。
    """
    def __init__(self):
        print("System Initializing...")
        # 1. 读取配置
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        # 2. 初始化世界状态仓库
        self.state = SystemState()
        # 3. 初始化各智能模块
        self.vision = VisionSystem(self.config)
        self.speech = SpeechSystem(self.config)
        self.llm = LLMParser(self.config)
        # 4. 初始化硬件控制器
        self.arm_ctrl = ArmController(self.config)
        self.rail_ctrl = RailController(self.config)  # 预留
        # 5. 启动生产者线程（相机）
        self.camera_thread = CameraThread(self.state, self.config)
        self.camera_thread.start()
        print("All systems initialized. Ready for competition.")
        time.sleep(2) # 等待相机线程稳定

    def shutdown(self):
        print("System Shutting Down...")
        self.camera_thread.stop()
        self.arm_ctrl.disconnect()
        print("Shutdown complete.")

    # =================== 任务A: 商品识别与语音播报 ===================
    def task_A_identify_all_items(self):
        print("\n--- Task A: Identify All Items ---")
        # 1. 机械臂移动到观察位（通过控制器）
        self.arm_ctrl.move_to_observe_position()
        # 2. 从状态仓库获取最新图像
        latest_image = self.state.get_latest_image()
        # 3. 视觉模块检测所有物体
        detected_items = self.vision.detect_all_items(latest_image)
        # 4. 排序（如有需要）
        sorted_items = self.vision.sort_items_for_broadcast(detected_items)
        # 5. 语音播报
        item_names = [item['name'] for item in sorted_items]
        broadcast_text = f"检测到以下商品: {', '.join(item_names)}"
        print(f"Broadcast: {broadcast_text}")
        self.speech.say(broadcast_text)

    # =================== 任务B: 推荐与抓取 ===================
    def task_B_recommend_and_grab(self, image_path):
        print(f"\n--- Task B: Recommend and Grab from {image_path} ---")
        # 1. LLM分析图片，推荐商品
        recommended_item = self.llm.recommend_item_from_image(image_path)
        if not recommended_item:
            self.speech.say("抱歉，我无法根据这张图片推荐商品。")
            return
        self.speech.say(f"根据图片内容，我为您推荐{recommended_item}。现在开始抓取。")
        # 2. 执行抓取流程
        self._core_grab_item_by_name(recommended_item)

    # =================== 任务C: 语音选购 ===================
    def task_C_grab_by_voice_command(self):
        print("\n--- Task C: Grab by Voice Command ---")
        self.speech.say("请说出您想要的商品。")
        command_text = self.speech.listen()
        if not command_text:
            self.speech.say("抱歉，我没有听到您的指令。")
            return
        item_to_grab = self.llm.parse_item_from_text(command_text)
        if not item_to_grab:
            self.speech.say("抱歉，我没能理解您想要的商品是什么。")
            return
        self.speech.say(f"好的，正在为您抓取{item_to_grab}。")
        self._core_grab_item_by_name(item_to_grab)

    # =================== 任务D: 结算与金额播报 ===================
    def task_D_checkout_and_sum(self):
        print("\n--- Task D: Checkout and Sum ---")
        self.arm_ctrl.move_to_checkout_scan_position()
        latest_image = self.state.get_latest_image()
        checkout_items = self.vision.detect_items_in_checkout_area(latest_image)
        if not checkout_items:
            self.speech.say("结算区内没有检测到任何商品。")
            return
        total_price, item_details = self.vision.calculate_total_price(checkout_items)
        summary_text = f"结算区有{item_details}。总计{total_price}元。"
        print(f"Checkout Summary: {summary_text}")
        self.speech.say(summary_text)

    # =================== 核心抓取流程 ===================
    def _core_grab_item_by_name(self, item_name):
        print(f"--- Core Grab Sequence for: {item_name} ---")
        # 1. 获取世界状态
        latest_image = self.state.get_latest_image()
        latest_point_cloud = self.state.get_latest_point_cloud()
        # 2. 视觉定位
        pixel_coords = self.vision.find_item_pixel_location(latest_image, item_name)
        if not pixel_coords:
            self.speech.say(f"抱歉，我在货架上找不到{item_name}。")
            return False
        # 3. 点云转3D
        camera_coords_3d = self.vision.get_3d_coords_from_point_cloud(latest_point_cloud, pixel_coords)
        # 4. 坐标变换
        arm_target_pose = Calibration.transform_camera_to_arm_base(camera_coords_3d)
        # 5. 执行抓取
        success = self.arm_ctrl.execute_grasp_sequence(arm_target_pose)
        if success:
            self.speech.say(f"{item_name}已抓取。")
            self.arm_ctrl.move_to_dropoff_and_release()
            self.speech.say("已放置到结算区。")
        else:
            self.speech.say(f"抱歉，抓取{item_name}失败。")
        return success

    # =================== 主循环 ===================
    def run_grabber(self):
        """命令行界面，触发不同任务。"""
        while True:
            print("\n" + "="*50)
            print("Select Competition Task:")
            print("[A] Identify All Items")
            print("[B] Recommend and Grab (from 'test_image.jpg')")
            print("[C] Grab by Voice Command")
            print("[D] Checkout and Sum")
            print("[Q] Quit")
            choice = input("Enter your choice: ").upper()
            if choice == 'A':
                self.task_A_identify_all_items()
            elif choice == 'B':
                self.task_B_recommend_and_grab('test_image.jpg')
            elif choice == 'C':
                self.task_C_grab_by_voice_command()
            elif choice == 'D':
                self.task_D_checkout_and_sum()
            elif choice == 'Q':
                break
            else:
                print("Invalid choice, please try again.")
            self.arm_ctrl.go_to_home_position() # 每个任务后回到安全位

if __name__ == "__main__":
    system = GrabberSystem()
    try:
        system.run_grabber()
    except KeyboardInterrupt:
        print("\nManual interruption detected.")
    finally:
        system.shutdown()