import time
import threading
import atexit
from typing import Optional
from utils.config import UGVConfig
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'external', 'pyagxrobots', 'src'))
import pyagxrobots


class UGVController:
    """
    AgileX Ranger Mini 3 UGV控制器，具有完善的资源管理功能
    运行前需确保当前环境已经使用 ip link set can0 up 初始化CAN接口
    """
    
    def __init__(self, ugv_config: UGVConfig):
        # 基本配置参数
        self.max_dist = ugv_config.max_dist  # 最大移动距离
        self.speed = ugv_config.speed        # 移动速度
        
        # 状态变量
        self._is_moving = False              # 是否正在移动
        self._position = 0.0                 # 当前位置 (0.0-1.0)
        self._movement_lock = threading.Lock()  # 线程锁
        self._connected = False              # 连接状态
        self._emergency_stop = False         # 紧急停止状态
        
        # 初始化UGV硬件连接
        self.ugv: Optional[pyagxrobots.pysdkugv.RangerBase] = None
        self._initialize_ugv()
        
        # 注册退出时的清理函数
        atexit.register(self.disconnect)
    
    def _initialize_ugv(self) -> bool:
        """初始化UGV连接"""
        print("开始UGV初始化...")
        
        try:
            print("初始化pyagxrobots.RangerBase...")
            self.ugv = pyagxrobots.pysdkugv.RangerBase()
            self._connected = True
            print("UGV初始化成功")
            return True
        except Exception as e:
            print(f"UGV初始化失败: {e}")
            print("可能的解决方案:")
            print("  1. 检查USB CAN适配器连接")
            print("  2. 确认AgileX底盘已开机")
            print("  3. 验证CAN线缆连接")
            print("  4. 重新插拔USB CAN适配器")
            self._connected = False
            return False
    
    def emergency_stop(self) -> bool:
        """立即停止所有运动"""
        self._emergency_stop = True
        if not self._connected or self.ugv is None:
            return False
        
        try:
            # 按照官方模式发送全零停止命令
            self.ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
            with self._movement_lock:
                self._is_moving = False
            return True
        except Exception as e:
            print(f"紧急停止失败: {e}")
            return False
    
    def move_to(self, position: float, wait: bool = True) -> bool:
        """移动到指定位置，支持可控的直线运动
        
        参数:
            position: 目标位置 (0.0到1.0范围)
            wait: 是否阻塞等待移动完成
            
        返回:
            bool: 移动是否成功启动
        """
        if not self._connected or self.ugv is None:
            print("UGV未连接")
            return False
        
        if self._emergency_stop:
            print("UGV处于紧急停止状态")
            return False
        
        # 验证位置范围
        position = max(0.0, min(1.0, position))
        
        with self._movement_lock:
            if self._is_moving:
                print("UGV正在移动中，停止当前运动")
                self.emergency_stop()
                time.sleep(0.1)  # 短暂暂停等待停止命令
            
            self._is_moving = True
        
        try:
            # 计算移动参数
            distance = abs(position - self._position)
            travel_time = self.max_dist * distance / max(self.speed, 1e-3)
            
            # 确定移动方向（负值 = 朝向放置区域）
            linear_velocity = -self.speed if position > self._position else self.speed
            
            # 执行移动
            self.ugv.SetMotionCommand(linear_vel=linear_velocity, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
            
            if wait:
                # 在移动过程中持续发送命令以维持运动状态
                start_time = time.time()
                while time.time() - start_time < travel_time:
                    if self._emergency_stop:
                        break
                    
                    # 持续发送运动命令 - CAN接口需要频繁发送命令才能维持运动
                    self.ugv.SetMotionCommand(
                        linear_vel=linear_velocity, 
                        lateral_vel=0.0, 
                        angular_vel=0.0, 
                        steer_angle=0.0
                    )
                    
                    time.sleep(0.02)  # 50Hz频率发送命令，对应ROS2版本的update_rate
                
                # 确保完全停止
                self.ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
                
                with self._movement_lock:
                    self._is_moving = False
                    if not self._emergency_stop:
                        self._position = position
            else:
                # 非阻塞：立即更新位置
                self._position = position
            
            return True
            
        except Exception as e:
            print(f"UGV移动错误: {e}")
            with self._movement_lock:
                self._is_moving = False
            self.emergency_stop()
            return False
    
    def is_moving(self) -> bool:
        """检查UGV是否正在移动"""
        with self._movement_lock:
            return self._is_moving
    
    def get_current_position(self) -> float:
        """获取当前位置（0.0到1.0范围）"""
        return self._position
    
    def is_connected(self) -> bool:
        """检查UGV是否已连接且可操作"""
        return self._connected and not self._emergency_stop
    
    def reset_emergency_stop(self) -> bool:
        """重置紧急停止状态"""
        if not self._connected:
            return False
        
        self._emergency_stop = False
        with self._movement_lock:
            self._is_moving = False
        return True
    
    def disconnect(self) -> None:
        """断开UGV连接并确保底层资源被释放"""
        print("断开UGV连接...")
        
        if self._connected and self.ugv is not None:
            try:
                print("  发送停止命令...")
                self.ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
                time.sleep(0.1)
                
                print("  正在关闭UGV底层接口...")
                self.ugv.shutdown()
                print("  UGV底层接口已关闭")

            except Exception as e:
                print(f"  断开连接时出错: {e}")
        
        # 清理UGV对象和状态
        self.ugv = None
        with self._movement_lock:
            self._connected = False
            self._is_moving = False
        
        print("UGV断开完成")