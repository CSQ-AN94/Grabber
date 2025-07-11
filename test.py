import threading
import time
import cv2
import numpy as np

from utils.config import load_config
from utils.state import RobotState
from utils.calibration import Calibration
from utils.handeye_calibrator import HandEyeCalibrator
from sensors.camera_thread import CameraThread
from controllers.arm_controller import ArmController
from controllers.rail_controller import RailController
from scipy.spatial.transform import Rotation
from intelligence.speech import SpeechSystem
from intelligence.llm_parser import LLMParser

class DisplayThread(threading.Thread):
    """一个简单的线程，用于在OpenCV窗口中实时显示相机画面。"""
    def __init__(self, state: RobotState, exit_event: threading.Event):
        super().__init__()
        self.state = state
        self.exit_event = exit_event
        self.daemon = True

    def run(self):
        print("[DisplayThread] Started. Press 'q' IN THE OPENCV WINDOW to close visualization.")
        try:
            # 循环条件：主程序没有要求退出
            while not self.exit_event.is_set():
                color, depth = self.state.get_latest_frames()
                # 如果没有新帧，短暂等待，避免CPU空转
                if color is None:
                    time.sleep(0.01)
                    continue

                # 在图像上可以添加一些状态信息
                cv2.imshow('Color Feed', color)
                
                if depth is not None:
                    d_vis = cv2.normalize(depth, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                    d_vis = cv2.applyColorMap(d_vis, cv2.COLORMAP_JET)
                    cv2.imshow('Depth Feed', d_vis)
                
                # waitKey现在只用于检测是否要关闭窗口，它不再设置全局事件
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    print("[DisplayThread] 'q' pressed. Closing visualization windows...")
                    break # 只跳出自己的循环，线程将自然结束
        finally:
            # 确保窗口被销毁
            cv2.destroyAllWindows()
            print("[DisplayThread] Windows closed.")

# --------------------------------------------------------------------------
#  独立的测试函数
# --------------------------------------------------------------------------
def test_arm_movement(arm: ArmController, config):
    print("\n--- [Test] Arm Movement ---")
    print("Moving to scanning pose...")
    arm.move_to_joints(config.scanning_pose) 
    time.sleep(1.5)
    print("Scanning pose in joint space:", arm.get_current_joint_angles())
    print("Scaninng pose in cartesian space", arm.get_base_to_end_pose_matrix)
    print("Moving to dropoff pose...")
    arm.move_to_joints(config.dropoff_pose)
    time.sleep(1.5)
    print("Dropoff pose in joint space:", arm.get_current_joint_angles())
    print("Dropoff pose in cartesian space", arm.get_base_to_end_pose_matrix)
    print("Moving to zero pose...")
    arm.move_to_joints(config.zero_pose)
    time.sleep(1.5)
    print("Zero pose in joint space:", arm.get_current_joint_angles())
    print("Zero pose in cartesian space", arm.get_base_to_end_pose_matrix)
    print("--- Arm Movement Test PASSED ---")

def test_gripper_control(arm: ArmController):
    print("\n--- [Test] Gripper Control ---")
    print("Opening gripper...")
    arm.set_gripper_openness(0.0)
    time.sleep(2)
    print("Closing gripper...")
    arm.set_gripper_openness(1.0)
    time.sleep(2)
    print("--- Gripper Control Test PASSED ---")

def test_rail_movement(rail: RailController, config):
    print("\n--- [Test] Rail Movement ---")
    print(f"Current position: {rail.get_current_position()}. Moving to end...")
    rail.move_to(config.scan_end)
    print(f"Position at end: {rail.get_current_position()}. Returning home...")
    rail.move_to(config.home_position)
    print(f"Position at home: {rail.get_current_position()}.")
    print("--- Rail Movement Test PASSED ---")

def test_coordinate_transform(calibration: Calibration, arm: ArmController, rail: RailController):
    print("\n--- [Test] Coordinate Transform ---")
    # 使用真实的实时数据进行一次变换，而不是伪造数据
    joint_angles = arm.get_current_joint_angles()
    rail_position = rail.get_current_position()
    # 假设一个在相机视野中心、前方0.5米处的点
    _, depth_map = state.get_latest_frames()
    if depth_map is None:
        print("Failed: No depth map available.")
        return
        
    h, w = depth_map.shape
    pixel_coords = (w // 2, h // 2)
    
    world_point = calibration.transform_pixel_to_world(pixel_coords, depth_map, joint_angles, rail_position)
    
    if world_point is not None:
        print(f"Pixel ({pixel_coords}) -> World ({np.round(world_point, 3)})")
        print("--- Coordinate Transform Test PASSED ---")
    else:
        print("--- Coordinate Transform Test FAILED (Invalid depth at pixel) ---")

def run_handeye_calibration(arm: ArmController, cam_thread: CameraThread, state: RobotState):
    print("\n" + "*"*60)
    print("WARNING: Starting Hand-Eye Calibration Process.")
    print("Please ensure:")
    print("1. The calibration board is rigidly fixed in the workspace.")
    print("2. Lighting is uniform and without glare.")
    print("3. The calibration poses in `handeye_calibrator.py` are safe and provide diverse views.")
    print("*"*60)
    if input("Proceed? (y/n): ").lower() != 'y':
        print("Calibration cancelled.")
        return
        
    calibrator = HandEyeCalibrator(arm, cam_thread, state)
    calibrator.run_calibration_process()
    print("\n--- Hand-Eye Calibration Process Finished ---")
    print("Please check `config.ini` for the updated `T_end_to_camera` matrix.")

def collect_calibration_poses_interactively(arm: ArmController, exit_event: threading.Event):
    """
    辅助采集高质量的手眼标定姿态。
    """
    print("\n" + "*"*60)
    print("Interactive Pose Collection Tool")
    print("1. Manually move the arm to a desired pose (using teach mode or another script).")
    print("2. Ensure the calibration board is fully visible in the 'Color Feed' window.")
    print("3. Press 'c' in the OpenCV window to capture and print the pose.")
    print("4. Press 'q' in the OpenCV window to quit this mode.")
    print("*"*60)

    # 确保显示窗口在前台
    cv2.imshow('Color Feed', np.zeros((480, 640, 3), dtype=np.uint8)) 

    captured_poses = []
    while not exit_event.is_set():
        key = cv2.waitKey(100) & 0xFF
        
        if key == ord('q'):
            print("Quitting pose collection mode.")
            break
        elif key == ord('c'):
            print("\n--- Capturing Pose ---")
            # 获取关节角度
            joint_angles = arm.get_current_joint_angles()
            if joint_angles is None:
                print("ERROR: Could not get joint angles.")
                continue
            
            # 计算笛卡尔空间坐标 (需要FK)
            temp_dh = arm.arm.rm_get_DH_data()[1]
            fk_solver = Calibration(temp_dh, np.eye(4))
            pose_matrix = fk_solver.calculate_fk(joint_angles)
            
            # 提取位置(m)和欧拉角(rad)
            position_m = pose_matrix[:3, 3]
            euler_rad = Rotation.from_matrix(pose_matrix[:3, :3]).as_euler('xyz')
            
            # 转换为对人类友好的格式
            joint_angles_deg = [round(np.rad2deg(j), 2) for j in joint_angles]
            position_mm = [round(p * 1000, 2) for p in position_m]
            
            print(f"Joints (deg): {joint_angles_deg},")
            print(f"Pose (mm, rad): pos=({position_mm[0]}, {position_mm[1]}, {position_mm[2]}) rot=({round(euler_rad[0],2)}, {round(euler_rad[1],2)}, {round(euler_rad[2],2)})")
            
            captured_poses.append(joint_angles_deg)

    print("\n--- Captured Poses for Calibration ---")
    print("Please copy the following list into `handeye_calibrator.py`:")
    for pose in captured_poses:
        print(f"    {pose},")

def test_speech_synthesis(speech_system: SpeechSystem):
    print("\n--- [Test] Speech Synthesis (TTS) ---")
    text_to_say = "你好，这是一个语音合成测试。如果能听到我说话，说明一切正常。"
    speech_system.say(text_to_say)
    print("--- TTS Test Finished ---")

def test_speech_recognition(speech_system: SpeechSystem):
    print("\n--- [Test] Speech Recognition (ASR) ---")
    print("Please speak into the microphone for 5 seconds after the prompt...")
    time.sleep(1)
    recognized_text = speech_system.listen(duration=5)
    if recognized_text:
        print(f"SUCCESS: Recognized text is -> '{recognized_text}'")
    else:
        print("FAILURE: No text recognized.")
    print("--- ASR Test Finished ---")

def test_llm_parser(llm_parser: LLMParser):
    print("\n--- [Test] LLM Command Parser ---")
    test_cases = [
        "你好",
        "我想要一瓶可口可乐",
        "帮我拿一下右边那个薯片",
        "有什么好喝的吗？",
    ]
    for case in test_cases:
        result = llm_parser.parse_user_command(case)
        print(f"Input: '{case}' -> Parsed: {result}")
    print("--- LLM Parser Test Finished ---")

# --------------------------------------------------------------------------
#  主测试菜单
# --------------------------------------------------------------------------
def run_test_menu(app_config, state, cam_thread, arm, rail, calibration, speech, llm, exit_event):
    while not exit_event.is_set():
        print("\n" + "="*50)
        print("Grabber System Test Suite")
        print("="*50)
        print("1. Test Arm Movement")
        print("2. Test Gripper Control")
        print("3. Test Rail Movement")
        print("4. Test Coordinate Transform (Live)")
        print("5. Run Full Hand-Eye Calibration")
        print("6. Collect Calibration Poses Interactively")
        print("7. Test Speech Synthesis (TTS)")
        print("8. Test Speech Recognition (ASR)")
        print("9. Test LLM Command Parser")
        print("Y. (Future) Test YOLOv8 Detection")
        print("Q. Quit")
        choice = input("Enter your choice: ").upper()

        match choice:
            case '1':
                test_arm_movement(arm, app_config.arm) 
            case '2':
                test_gripper_control(arm)
            case '3':
                test_rail_movement(rail, app_config.rail)
            case '4':   
                test_coordinate_transform(calibration, arm, rail)
            case '5':
                run_handeye_calibration(arm, cam_thread, state)
            case '6':
                collect_calibration_poses_interactively(arm, exit_event)
            case '7':
                test_speech_synthesis(speech)
            case '8':
                test_speech_recognition(speech)
            case '9':
                test_llm_parser(llm)
            case 'Q':
                exit_event.set()
            case _:
                print("Invalid choice. Please try again.")       
        
        # 给硬件一些喘息时间
        time.sleep(1)

# --------------------------------------------------------------------------
#  主程序入口
# --------------------------------------------------------------------------
if __name__ == "__main__":
    # --- 1. 系统初始化 (Setup) ---
    print("--- System Setup ---")
    app_config = load_config("config.ini")
    state = RobotState()
    exit_event = threading.Event()

    # 启动后台线程
    cam_thread = CameraThread(state, app_config.camera)
    cam_thread.start()
    display_thread = DisplayThread(state, exit_event)
    display_thread.start()
    
    # 等待相机稳定并提供第一帧数据
    print("Waiting for camera to initialize and provide first frame...")
    time.sleep(3) 
    if state.get_latest_frames()[0] is None:
        print("CRITICAL: Failed to get frame from camera. Exiting.")
        exit_event.set()
    else:
        print("Camera is live.")

    # # 初始化控制器和工具
    # arm = ArmController(app_config.connections, app_config.arm, app_config.gripper)
    # rail = RailController(app_config.rail) # 即使是dummy controller，也实例化
    
    # # 初始化标定对象，这是所有坐标转换的基础
    # K, dist = cam_thread.get_camera_intrinsics()
    # T_end_to_camera = app_config.calibration.T_end_to_camera
    # dh_params = arm.arm.rm_get_DH_data()[1]
    # calibration = Calibration(dh_params, T_end_to_camera, K, dist)
    # print("Controllers and Calibration tools initialized.")

    # 初始化智能系统
    speech = SpeechSystem(app_config.speech)
    llm = LLMParser(app_config.llm)
    print("Speech and LLM systems initialized.")
    
    # --- 2. 运行测试菜单 (Main Logic) ---
    # 使用 try...finally 来确保即使测试崩溃，也能安全退出
    try:
        arm = None
        rail = None
        calibration = None
        run_test_menu(app_config, state, cam_thread, arm, rail, calibration, speech, llm, exit_event)
    except Exception as e:
        print(f"\nAn exception occurred: {e}")
    finally:
        # --- 3. 系统关闭 (Teardown) ---
        print("\n--- System Teardown ---")
        exit_event.set() # 确保所有循环都会退出
        
        # 等待所有线程结束
        if cam_thread.is_alive():
            cam_thread.join(timeout=2)
        if display_thread.is_alive():
            display_thread.join(timeout=2)
        
        print("Test suite finished.")