from external.RM_API2.Python.Robotic_Arm.rm_robot_interface import *
import threading
import time
from utils.config import *
from external.RM_API2.Demo.RMDemo_Python.RMDemo_AlgoInterface.src.Robotic_Arm.rm_robot_interface import RoboticArm

class ArmController:
    def __init__(self, conn_config:ConnectionsConfig, arm_config:ArmConfig, gripper_config:GripperConfig):
        self.lock = threading.Lock()
        self.config = arm_config
        self.arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
        self.handle = self.arm.rm_create_robot_arm(conn_config.arm_ip, conn_config.arm_port)
        self._init_gripper(gripper_config)  # 初始化夹爪
        print(f"机械臂连接句柄: {self.handle.id}")

    def move_to_joints(self, joint_angles, speed=30, radius=0, wait=True):
        # joint_angles: list of 6 floats (单位: 度)
        # speed: int, 机械臂运动速度
        # radius: int, 轨迹圆滑度
        # wait: 是否阻塞直到完成
        with self.lock:
            block = 1 if wait else 0
            # connect=0: 不连接下一个轨迹
            return self.arm.rm_movej(joint_angles, speed, radius, 0, block)

    def move_to_cartesian_pose(self, pose, speed=30, radius=0, wait=True):
        # pose: [x, y, z, rx, ry, rz] (单位: mm, deg)
        with self.lock:
            block = 1 if wait else 0
            return self.arm.rm_movel(pose, speed, radius, 0, block)

    def get_current_joint_angles(self):
        # 返回当前6个关节角度 (单位: 度)
        with self.lock:
            code, joints = self.arm.rm_get_joint_degree()
            if code == 0:
                return joints
            else:
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

    def get_dh_params(self):
        # 获取DH参数，返回[[a, alpha, d, theta_offset], ...]
        arm = RoboticArm()
        ret, dh_struct = arm.rm_get_DH_data()
        if ret != 0:
            raise RuntimeError(f"获取DH参数失败，错误码: {ret}")
        # dh_struct: rm_dh_t，字段为d, a, alpha, offset，均为c_float*8
        # 单位：d, a为米，alpha, offset为角度（需转为弧度）
        dof = 6  # 视具体机械臂型号而定
        d = [dh_struct.d[i] for i in range(dof)]
        a = [dh_struct.a[i] for i in range(dof)]
        alpha = [np.deg2rad(dh_struct.alpha[i]) for i in range(dof)]
        offset = [np.deg2rad(dh_struct.offset[i]) for i in range(dof)]
        # 返回标准DH参数格式
        return [[a[i], alpha[i], d[i], offset[i]] for i in range(dof)]