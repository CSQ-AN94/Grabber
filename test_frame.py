# test_frame.py
from controllers.arm_controller import ArmController
from utils.calibration import Calibration
from utils.config import load_config
import time


app_config = load_config("config.ini")
arm = ArmController(app_config.connections, app_config.arm, app_config.gripper)
dh_params = arm.arm.rm_get_DH_data()[1]
T_end_to_camera = app_config.calibration.T_end_to_camera
calibration = Calibration(dh_params, T_end_to_camera, 0, 0)

# 1. 让机械臂回到绝对零位
print("Moving to absolute zero position...")
arm.move_to_joints([0, 0, 0, 0, 0, 0])
time.sleep(3)

# 2. 获取零位时的末端姿态 (通过正运动学)
#    这将是我们所有测量的参考原点
zero_pose_matrix = calibration.calculate_fk([0, 0, 0, 0, 0, 0])
print(f"Pose at joint zero (from FK):\n{zero_pose_matrix}")

# 3. 实验1: 沿一个轴平移
print("Testing movement along one axis...")
# 假设我们认为 X 轴是朝前的
# 构造一个目标姿态：在零位姿态的基础上，沿X轴平移10cm (0.1米)
# 旋转保持不变
target_pose_list = [0.1, 0.0, 0.0, 0.0, 0.0, 0.0] # [x, y, z, rx, ry, rz] in meters and radians

# 使用 rm_movej_p 移动
arm.arm.rm_movej_p(target_pose_list, v=30, r=0, connect=0, block=1)

# 观察结果: 机械臂是不是笔直地向前移动了？
# 如果是，那么API的X轴就是我们认为的“向前”。
# 如果它向右移动了，那API的X轴就是我们的“向右”。
# 你可以通过这个方法依次测试X, Y, Z轴。

# 4. 实验2: 绕一个轴旋转
print("Testing rotation around one axis...")
arm.move_to_joints([0, 0, 0, 0, 0, 0]) # 回到零位
time.sleep(3)
# 构造一个目标姿态：绕Z轴旋转90度 (pi/2)
target_pose_list_rot = [0.0, 0.0, 0.0, 0.0, 0.0, 1.5708]
arm.arm.rm_movej_p(target_pose_list_rot, v=30, r=0, connect=0, block=1)
# 观察末端工具（夹爪）是如何旋转的，这就定义了Z轴的旋转方向。