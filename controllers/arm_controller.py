from external.RM_API2.Python.Robotic_Arm.rm_robot_interface import *
from scipy.spatial.transform import Rotation
import threading
import time
import numpy as np
from utils.config import *

class ArmController:
    def __init__(self, conn_config:ConnectionsConfig, arm_config:ArmConfig, gripper_config:GripperConfig):
        self.lock = threading.Lock()
        self.config = arm_config
        self.arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
        self.handle = self.arm.rm_create_robot_arm(conn_config.arm_ip, conn_config.arm_port)
        self._init_gripper(gripper_config)  # 初始化夹爪
        print(f"机械臂连接句柄: {self.handle.id}")

    def move_to_joints(self, joint_angles, speed=30, radius=0, wait=True):
        # joint_angles: list of 6 floats (单位: 弧度)
        # speed: int, 机械臂运动速度百分比
        # radius: int, 轨迹圆滑度
        
        with self.lock:
            # 将弧度转换为度，因为API需要度作为输入
            joint_angles_deg = [np.rad2deg(angle) for angle in joint_angles]
            block = 1 if wait else 0
            # connect=0: 不连接下一个轨迹
            return self.arm.rm_movej(joint_angles_deg, speed, radius, 0, block)
        
    def move_to_cartesian_pose(self, pose, speed=30, wait=True):
        # pose: 一个6元素的列表 [x, y, z, roll, pitch, yaw]。位置单位为米(m)，姿态单位为弧度(rad)。
        # speed: 运动速度百分比
        # wait: 是否阻塞直到完成
        with self.lock:
            # rm_movej_p API需要米和弧度，直接使用传入的pose
            block = 1 if wait else 0
            return self.arm.rm_movej_p(pose, speed, 0, 0, block)

    def get_current_joint_angles(self):
        """
        返回当前6个关节角度 (单位: 弧度)
        """
        with self.lock:
            code, joints_deg = self.arm.rm_get_joint_degree() # 返回值是度
            if code == 0:
                joints_rad = [np.deg2rad(j) for j in joints_deg] # 转换为弧度
                return joints_rad
            else:
                return None
            
    def get_base_to_end_pose_matrix(self):
        """
        获取机械臂末端在基坐标系下的位姿矩阵
        """
        with self.lock:
            ret_code, state_dict = self.arm.rm_get_current_arm_state()
            if ret_code != 0:
                print(f"获取机械臂状态失败，错误码: {ret_code}")
                return None
            pose_raw = state_dict.get('pose')
            if pose_raw is None:
                print("无法获取末端位姿")
                return None
            # 单位转换
            x_m = pose_raw[0] / 1000000.0  # 0.001mm -> m
            y_m = pose_raw[1] / 1000000.0  # 0.001mm -> m
            z_m = pose_raw[2] / 1000000.0  # 0.001mm -> m
            rx_rad = pose_raw[3] / 1000.0    # 0.001rad -> rad
            ry_rad = pose_raw[4] / 1000.0    # 0.001rad -> rad
            rz_rad = pose_raw[5] / 1000.0    # 0.001rad -> rad
            # 构造4x4位姿矩阵
            T = np.eye(4)
            try:
                rotation_matrix = Rotation.from_euler('xyz', [rx_rad, ry_rad, rz_rad], degrees=False).as_matrix()
                T[:3, :3] = rotation_matrix
                T[:3, 3] = [x_m, y_m, z_m]
                return T
            except Exception as e:
                print(f"转换位姿矩阵失败: {e}")
                return None

    def _init_gripper(self, gripper_config: GripperConfig):
        # 设置24V
        self.arm.rm_set_tool_voltage(3)
        time.sleep(0.5)
        # 设置工具端RS485为modbus RTU主站，波特率9600
        print("设置RS485的返回码：", self.arm.rm_set_tool_rs485_mode(0, 9600))
        time.sleep(0.2)
        # 写入速度参数
        self._write_gripper_reg(36, gripper_config.zero_speed)  # 找零速度
        time.sleep(0.2)
        self._write_gripper_reg(38, gripper_config.init_speed)   # 初始速度
        time.sleep(0.2)
        self._write_gripper_reg(40, gripper_config.run_speed)   # 运行速度
        time.sleep(0.2)

    def _write_gripper_reg(self, address, value):
        """
        将十进制的数据转换为modbus RTU寄存器格式并写入
        """
        high = (value >> 16) & 0xFFFF
        low = value & 0xFFFF
        data = [high, low]
        param = rm_modbus_rtu_write_params_t(
            device=1, # 外部设备地址
            address=address, # 寄存器开始地址
            type=1, # 0=控制器端, 1=工具端 
            num=2,
            data=data
        )
        return self.arm.rm_write_modbus_rtu_registers(param)

    def set_gripper_openness(self, openness):
        # 0.0(全开)~1.0(全关)
        with self.lock:
            pos = int(openness * 256000)
            return self._write_gripper_reg(43, pos)