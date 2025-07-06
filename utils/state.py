import threading
import time
from sensors.camera_thread import CameraThread
import cv2
import numpy as np
from utils.config import load_config
from utils.calibration import Calibration

class RobotState:
    def __init__(self):
        self.lock = threading.Lock()  # 线程锁，保证数据安全

        # --- Camera State ---
        self.latest_color_frame = None
        self.latest_depth_frame = None
        self.new_frame_available = False # 一个标志位

        # --- Arm State ---
        self.current_joint_angles = None  # [float]*6
        self.is_arm_moving = False
        self.gripper_openness = None  # 0.0~1.0

    def update_frames(self, color, depth):
        with self.lock:
            self.latest_color_frame = color
            self.latest_depth_frame = depth
            self.new_frame_available = True

    def get_latest_frames(self):
        with self.lock:
            self.new_frame_available = False
            return self.latest_color_frame, self.latest_depth_frame

    # ========== Arm State ========== 
    def update_joint_angles(self, joint_angles):
        with self.lock:
            self.current_joint_angles = list(joint_angles)

    def get_joint_angles(self):
        with self.lock:
            return self.current_joint_angles

    def set_arm_moving(self, moving: bool):
        with self.lock:
            self.is_arm_moving = moving

    def get_arm_moving(self):
        with self.lock:
            return self.is_arm_moving

    def set_gripper_openness(self, openness):
        with self.lock:
            self.gripper_openness = openness

    def get_gripper_openness(self):
        with self.lock:
            return self.gripper_openness

# 临时测试代码
if __name__ == "__main__":
    app_config = load_config("config.ini")
    conn_config = app_config.connections
    arm_config = app_config.arm
    gripper_config = app_config.gripper
    camera_config = app_config.camera
    rail_config = app_config.rail
    
    state = RobotState()
    # 摄像头线程测试
    cam_thread = CameraThread(state, camera_config)
    cam_thread.start()
    print('Camera thread started. Press q to exit.')

    # 摄像头实时显示
    try:
        while True:
            color, depth = state.get_latest_frames()
            if color is not None:
                cv2.imshow('Color', color)
            if depth is not None:
                d = depth.astype(np.float32)
                d = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX)
                d = d.astype(np.uint8)
                d = cv2.applyColorMap(d, cv2.COLORMAP_JET) # 红色代表最远，蓝色代表最近，黑色是无效值
                cv2.imshow('Depth', d)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        cam_thread.join(timeout=1)
        cv2.destroyAllWindows()

    # 机械臂测试
    from controllers.arm_controller import ArmController
    arm = ArmController(conn_config, arm_config, gripper_config)

    # 获取机械臂DH参数
    [ret, dh] = arm.rm_get_DH_data()
    print(dh.to_dict())

    # 获取并保存初始关节角度
    joints = arm.get_current_joint_angles()
    
    print('Current joints:', joints)
    state.update_joint_angles(joints)

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
    time.sleep(3)
    arm.move_to_joints(arm_config.dropoff_pose)
    time.sleep(3)
    arm.move_to_joints(arm_config.zero_pose)
    time.sleep(3)
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

    # 摄像头实时显示
    try:
        while True:
            color, depth = state.get_latest_frames()
            if color is not None:
                cv2.imshow('Color', color)
            if depth is not None:
                d = depth.astype(np.float32)
                d = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX)
                d = d.astype(np.uint8)
                d = cv2.applyColorMap(d, cv2.COLORMAP_JET) # 红色代表最远，蓝色代表最近，黑色是无效值
                cv2.imshow('Depth', d)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
    finally:
        cam_thread.join(timeout=1)
        cv2.destroyAllWindows()

    # Calibration测试
    dh_params = app_config.arm.dh_params
    T_end_to_camera = app_config.calibration.T_end_to_camera
    calib = Calibration(dh_params, T_end_to_camera)
    # 伪造一组关节角度、滑轨位置、相机点
    joint_angles = [0, 0, 0, 0, 0, 0]  # 6轴机械臂
    rail_position = 0.5  # 滑轨位置
    camera_point = np.array([0.1, 0.2, 0.3])  # 相机系下的点
    world_point = calib.transform_camera_to_world(camera_point, joint_angles, rail_position)
    print(f"Camera point {camera_point} -> World point {world_point}")