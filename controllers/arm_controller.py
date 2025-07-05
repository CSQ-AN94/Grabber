from external.RM_API2.Python.Robotic_Arm.rm_robot_interface import *
import threading
import time

class ArmController:
    def __init__(self, ip_address, port=8080):
        self.lock = threading.Lock()
        # 按官方示例初始化
        self.arm = RoboticArm(rm_thread_mode_e.RM_TRIPLE_MODE_E)
        self.handle = self.arm.rm_create_robot_arm(ip_address, port)
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

    def _init_gripper(self):
        # 只初始化一次夹爪
        if hasattr(self, '_gripper_inited') and self._gripper_inited:
            return
        # 设置24V
        self.arm.rm_set_tool_voltage(3)
        time.sleep(0.5)
        # 设置工具端RS485为modbus RTU主站，波特率9600
        print("设置RS485的返回码：", self.arm.rm_set_tool_rs485_mode(0, 9600))
        time.sleep(0.2)
        # 写入速度参数
        print("写入找零速度的返回码：", self._write_gripper_reg(36, 25600))   # 找零速度
        time.sleep(0.2)
        self._write_gripper_reg(38, 51200)   # 初始速度
        time.sleep(0.2)
        self._write_gripper_reg(40, 51200)   # 运行速度
        time.sleep(0.2)
        self._gripper_inited = True

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
            self._init_gripper()
            pos = int(openness * 256000)
            return self._write_gripper_reg(43, pos)