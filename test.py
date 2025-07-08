import threading
import time
from sensors.camera_thread import CameraThread
import cv2
import numpy as np
from utils.config import load_config
from utils.calibration import Calibration
from external.RM_API2.Demo.RMDemo_Python.RMDemo_Gripper.src.Robotic_Arm.rm_robot_interface import RoboticArm
from intelligence.vision import VisionAnalyzer
from utils.handeye_calibrator import HandEyeCalibrator
from utils.state import RobotState, DisplayThread

# 临时测试代码
if __name__ == "__main__":
    app_config = load_config("config.ini")
    conn_config = app_config.connections
    arm_config = app_config.arm
    gripper_config = app_config.gripper
    camera_config = app_config.camera
    rail_config = app_config.rail
    
    state = RobotState()
    should_exit = {'exit': False}

    # 摄像头线程
    cam_thread = CameraThread(state, camera_config)
    cam_thread.start()
    print('Camera thread started.')

    # 显示线程
    display_thread = DisplayThread(state, should_exit)
    display_thread.start()
    print('Display thread started. 按q退出显示窗口。')

    # 机械臂测试
    from controllers.arm_controller import ArmController
    arm = ArmController(conn_config, arm_config, gripper_config)

    # 获取机械臂DH参数
    [ret, dh] = arm.arm.rm_get_DH_data()
    print("机械臂DH参数:", dh)

    # 夹爪开合测试
    print('Opening gripper...')
    arm.set_gripper_openness(0.0)  # 全开
    state.set_gripper_openness(0.0)
    time.sleep(2)
    print('Closing gripper...')
    arm.set_gripper_openness(1.0)  # 全关
    state.set_gripper_openness(1.0)
    time.sleep(2)

    # 机械臂运动测试
    print('Moving arm...')
    state.set_arm_moving(True)
    arm.move_to_joints(arm_config.scanning_pose) 
    time.sleep(2)
    arm.move_to_joints(arm_config.dropoff_pose)
    time.sleep(2)
    arm.move_to_joints(arm_config.zero_pose)
    time.sleep(2)
    state.set_arm_moving(False)
    print('Move done.')

    # 所有arm_config相关参数均已通过arm_config对象传递

    # 滑轨控制器测试
    from controllers.rail_controller import RailController
    rail = RailController(rail_config)
    print(f"Rail home position: {rail.get_current_position()}")
    rail.move_to(rail_config.scan_end)
    print(f"Rail moved to: {rail.get_current_position()}")
    rail.move_to(rail_config.home_position)
    print(f"Rail returned to home: {rail.get_current_position()}")

    # 一键手眼标定
    if input('是否进行手眼标定？(y/n): ').lower() == 'y':
        calibrator = HandEyeCalibrator(arm, state, cam_thread)
        calibrator.run_calibration_process()
        print('标定完成，重新加载config.ini...')
        app_config = load_config("config.ini")
        T_end_to_camera = app_config.calibration.T_end_to_camera
        print('新T_end_to_camera:', T_end_to_camera)
        [ret, dh] = arm.arm.rm_get_DH_data()
        calib = Calibration(dh, T_end_to_camera)
        # 伪造一组关节角度、滑轨位置、相机点
        joint_angles = [0, 0, 0, 0, 0, 0]
        rail_position = 0.5
        camera_point = np.array([0.1, 0.2, 0.3])
        world_point = calib.transform_camera_to_world(camera_point, joint_angles, rail_position)
        print(f"Camera point {camera_point} -> World point {world_point}")

    # Calibration测试（动态获取DH参数）
    K, dist = cam_thread.get_camera_intrinsics()
    T_end_to_camera = app_config.calibration.T_end_to_camera
    calib = Calibration(arm.arm.rm_get_DH_data()[1], T_end_to_camera, K, dist)
    # 伪造一组关节角度、滑轨位置、相机点
    joint_angles = [0, 0, 0, 0, 0, 0]  # 6轴机械臂
    rail_position = 0.5  # 滑轨位置
    camera_point = np.array([0.1, 0.2, 0.3])  # 相机系下的点
    world_point = calib.transform_camera_to_world(camera_point, joint_angles, rail_position)
    print(f"Camera point {camera_point} -> World point {world_point}")

    should_exit['exit'] = True
    cam_thread.join(timeout=2)
    display_thread.join(timeout=2)
    print('所有线程已安全退出。')