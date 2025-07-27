import time
import threading
import atexit
import subprocess
from typing import Optional
from utils.config import UGVConfig
import pyagxrobots


class UGVController:
    """AgileX Ranger Mini 3 UGV控制器，具有完善的资源管理功能"""
    
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
    
    def _ensure_can_interface_ready(self) -> bool:
        """清理上一次连接并重新配置CAN接口"""
        try:
            print("准备CAN接口...")
            
            # 步骤1: 清理上一次的连接（先DOWN）
            print("  步骤1: 清理上一次连接...")
            result = subprocess.run(
                ['ip', 'link', 'set', 'can0', 'down'],
                capture_output=True, text=True, timeout=10
            )
            # 不检查返回码，因为接口可能已经是DOWN状态
            print("  上一次连接已清理")
            
            # 步骤2: 配置CAN接口参数
            print("  步骤2: 配置CAN接口参数...")
            result = subprocess.run(
                ['ip', 'link', 'set', 'can0', 'type', 'can', 'bitrate', '500000'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                print(f"  CAN接口配置失败: {result.stderr}")
                return False
            print("  CAN接口参数配置成功")
            
            # 步骤3: 启动CAN接口
            print("  步骤3: 启动CAN接口...")
            result = subprocess.run(
                ['ip', 'link', 'set', 'can0', 'up'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                print(f"  CAN接口启动失败: {result.stderr}")
                return False
            print("  CAN接口启动成功")
            
            # 步骤4: 验证接口状态为UP
            print("  步骤4: 验证接口状态...")
            result = subprocess.run(
                ['ip', 'link', 'show', 'can0'],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0:
                print(f"  无法获取CAN接口状态: {result.stderr}")
                return False
            
            # 检查输出中是否包含"UP"
            if "UP" in result.stdout:
                print("  CAN接口状态验证: UP")
                return True
            else:
                print(f"  CAN接口状态异常:")
                for line in result.stdout.split('\n'):
                    if line.strip():
                        print(f"    {line.strip()}")
                return False
                
        except subprocess.TimeoutExpired:
            print("  CAN接口配置超时")
            return False
        except Exception as e:
            print(f"  CAN接口配置异常: {e}")
            return False
    
    def _initialize_ugv(self) -> bool:
        """初始化UGV连接，包含CAN接口自动配置和错误处理"""
        print("开始UGV初始化...")
             
        # CAN接口就绪后，初始化pyagxrobots
        try:
            # 首先确保CAN接口就绪
            if not self._ensure_can_interface_ready():
                print("CAN接口配置失败，UGV初始化终止")
                self._connected = False
                return False
            # 关键：在接口UP之后，给予硬件和驱动一点稳定时间
            print("等待CAN接口稳定...")
            time.sleep(0.5)

            print("初始化pyagxrobots.RangerBase...")
            self.ugv = pyagxrobots.pysdkugv.RangerBase()
            self._connected = True
            print("UGV初始化成功")
            return True
        except Exception as e:
            try:
                if not self._ensure_can_interface_ready():
                    print("重试CAN接口配置失败，UGV初始化终止")
                    self._connected = False
                    return False
                print("等待CAN接口稳定...")
                time.sleep(0.5)   

                print("重试UGV初始化")
                self.ugv = pyagxrobots.pysdkugv.RangerBase()
                self._connected = True
                print("第二次UGV初始化成功")
                return True
            except Exception as e:
                print(f"第二次UGV初始化失败: {e}")
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
        """断开UGV连接并尝试优雅地关闭CAN总线"""
        print("断开UGV连接...")
        
        # 发送停止命令（如果连接正常）
        if self._connected and self.ugv is not None:
            try:
                print("  发送停止命令...")
                self.ugv.SetMotionCommand(linear_vel=0.0, lateral_vel=0.0, angular_vel=0.0, steer_angle=0.0)
                time.sleep(0.1)  # 等待命令处理
            except Exception as e:
                print(f"  停止命令发送失败: {e}")

        # 尝试访问并关闭底层的CAN总线
        if hasattr(self.ugv, 'rangerbase') and hasattr(self.ugv.rangerbase, 'device') and hasattr(self.ugv.rangerbase.device, 'bus'):
            try:
                print("  正在关闭底层CAN总线...")
                self.ugv.rangerbase.device.bus.shutdown()
                print("  底层CAN总线已关闭")
            except Exception as e:
                print(f"  关闭底层CAN总线失败: {e}")
        
        # 清理UGV对象和状态
        self.ugv = None
        with self._movement_lock:
            self._connected = False
            self._is_moving = False
        
        print("UGV断开完成")