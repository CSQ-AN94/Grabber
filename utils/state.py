import threading

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