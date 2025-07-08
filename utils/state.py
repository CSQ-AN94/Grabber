import threading
import cv2
import numpy as np

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

class DisplayThread(threading.Thread):
    def __init__(self, state, should_exit_flag):
        super().__init__()
        self.state = state
        self.should_exit_flag = should_exit_flag

    def run(self):
        while not self.should_exit_flag['exit']:
            color, depth = self.state.get_latest_frames()
            if color is not None:
                cv2.imshow('Color', color)
            if depth is not None:
                d = depth.astype(np.float32)
                d = cv2.normalize(d, None, 0, 255, cv2.NORM_MINMAX)
                d = d.astype(np.uint8)
                d = cv2.applyColorMap(d, cv2.COLORMAP_JET)
                cv2.imshow('Depth', d)
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.should_exit_flag['exit'] = True
                break
        cv2.destroyAllWindows()

