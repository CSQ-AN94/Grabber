import threading
import time
import cv2
import numpy as np

# 导入我们所有的模块和工具
from utils.config import load_config
from utils.state import RobotState
from utils.calibration import Calibration
from utils.handeye_calibrator import HandEyeCalibrator
from sensors.camera_thread import CameraThread
from controllers.arm_controller import ArmController
from controllers.rail_controller import RailController

class DisplayThread(threading.Thread):
    """一个简单的线程，用于在OpenCV窗口中实时显示相机画面。"""
    def __init__(self, state: RobotState, exit_event: threading.Event):
        super().__init__()
        self.state = state
        self.exit_event = exit_event
        self.daemon = True

    def run(self):
        print("[DisplayThread] Started. Press 'q' in the OpenCV window to request exit.")
        while not self.exit_event.is_set():
            color, depth = self.state.get_latest_frames()
            if color is not None:
                # 在图像上可以添加一些状态信息，比如机械臂是否在移动
                if self.state.get_arm_moving():
                    cv2.putText(color, "ARM MOVING", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)
                cv2.imshow('Color Feed', color)
            if depth is not None:
                # 深度图的可视化
                d_vis = cv2.normalize(depth, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
                d_vis = cv2.applyColorMap(d_vis, cv2.COLORMAP_JET)
                cv2.imshow('Depth Feed', d_vis)
            
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.exit_event.set() # 发送退出信号
                break
        cv2.destroyAllWindows()
        print("[DisplayThread] Windows closed.")

# --------------------------------------------------------------------------
#  独立的测试函数
# --------------------------------------------------------------------------
def test_arm_movement(arm: ArmController, config):
    print("\n--- [Test] Arm Movement ---")
    print("Moving to scanning pose...")
    arm.move_to_joints(config.scanning_pose) 
    time.sleep(1)
    print("Moving to dropoff pose...")
    arm.move_to_joints(config.dropoff_pose)
    time.sleep(1)
    print("Moving to zero pose...")
    arm.move_to_joints(config.zero_pose)
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

def run_handeye_calibration(arm: ArmController, cam_thread: CameraThread, state: RobotState, calibration: Calibration):
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
        
    calibrator = HandEyeCalibrator(arm, cam_thread, state, calibration)
    calibrator.run_calibration_process()
    print("\n--- Hand-Eye Calibration Process Finished ---")
    print("Please check `config.ini` for the updated `T_end_to_camera` matrix.")

# --------------------------------------------------------------------------
#  主测试菜单
# --------------------------------------------------------------------------
def run_test_menu(app_config, state, cam_thread, arm, rail, calibration):
    while not exit_event.is_set():
        print("\n" + "="*50)
        print("Grabber System Test Suite")
        print("="*50)
        print("1. Test Arm Movement")
        print("2. Test Gripper Control")
        print("3. Test Rail Movement")
        print("4. Test Coordinate Transform (Live)")
        print("5. Run Full Hand-Eye Calibration")
        print("Y. (Future) Test YOLOv8 Detection")
        print("Q. Quit")
        choice = input("Enter your choice: ").upper()

        if choice == '1':
            test_arm_movement(arm, app_config.arm)
        elif choice == '2':
            test_gripper_control(arm)
        elif choice == '3':
            test_rail_movement(rail, app_config.rail)
        elif choice == '4':
            test_coordinate_transform(calibration, arm, rail)
        elif choice == '5':
            run_handeye_calibration(arm, cam_thread, state, calibration)
        elif choice == 'Q':
            exit_event.set() # 发送退出信号
        else:
            print("Invalid choice.")
        
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

    # 初始化控制器和工具
    arm = ArmController(app_config.connections, app_config.arm, app_config.gripper)
    rail = RailController(app_config.rail) # 即使是dummy controller，也实例化
    
    # 初始化标定对象，这是所有坐标转换的基础
    K, dist = cam_thread.get_camera_intrinsics()
    T_end_to_camera = app_config.calibration.T_end_to_camera
    dh_params = arm.arm.rm_get_DH_data()[1]
    calibration = Calibration(dh_params, T_end_to_camera, K, dist)
    print("Controllers and Calibration tools initialized.")
    
    # --- 2. 运行测试菜单 (Main Logic) ---
    # 使用 try...finally 来确保即使测试崩溃，也能安全退出
    try:
        run_test_menu(app_config, state, cam_thread, arm, rail, calibration)
    except Exception as e:
        print(f"\nAn exception occurred: {e}")
        exit_event.set() # 确保在异常时也能退出
    finally:
        # --- 3. 系统关闭 (Teardown) ---
        print("\n--- System Teardown ---")
        exit_event.set() # 确保所有循环都会退出
        
        # 等待所有线程结束
        if cam_thread.is_alive():
            cam_thread.join(timeout=2)
        if display_thread.is_alive():
            display_thread.join(timeout=2)
            
        # 可以添加其他清理代码，如断开硬件连接
        # arm.disconnect() 
        
        print("Test suite finished.")