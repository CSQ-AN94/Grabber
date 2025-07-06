import configparser
from dataclasses import dataclass
import numpy as np
from typing import List

@dataclass
class ConnectionsConfig:
    arm_ip: str
    arm_port: int

@dataclass
class ArmConfig:
    scanning_pose: List[float]
    zero_pose: List[float]
    dropoff_pose: List[float]
    checkout_scan_pose: List[float]


@dataclass
class GripperConfig:
    zero_speed: int
    init_speed: int
    run_speed: int

@dataclass
class CameraConfig:
    enable_color: bool
    enable_depth: bool
    frame_timeout_ms: int
    sleep_interval: float
    # 可扩展分辨率、帧率等参数
    
# --- 主配置类，聚合所有部分 ---
@dataclass
class AppConfig:
    connections: ConnectionsConfig
    arm: ArmConfig
    gripper: GripperConfig
    camera: CameraConfig
    
# --- 主加载函数 ---
def load_config(path: str = 'config.ini') -> AppConfig:
    """
    读取.ini文件，解析所有部分，并返回一个结构化的AppConfig对象。
    """
    parser = configparser.ConfigParser()
    parser.read(path)

    def _parse_list(s: str) -> List[float]:
        """一个辅助函数，用于将逗号分隔的字符串解析为浮点数列表"""
        return [float(x.strip()) for x in s.split(',')]
    
    # 使用上面定义的dataclass填充配置
    conn_config = ConnectionsConfig(
        arm_ip=parser.get('connections', 'arm_ip'),
        arm_port=parser.getint('connections', 'arm_port')
    )

    arm_config = ArmConfig(
        scanning_pose=_parse_list(parser.get('arm', 'scanning_pose')),
        zero_pose=_parse_list(parser.get('arm', 'zero_pose')),
        dropoff_pose=_parse_list(parser.get('arm', 'dropoff_pose')),
        checkout_scan_pose=_parse_list(parser.get('arm', 'checkout_scan_pose'))
    )

    gripper_config = GripperConfig(
        zero_speed=parser.getint('gripper', 'zero_speed'),
        init_speed=parser.getint('gripper', 'init_speed'),
        run_speed=parser.getint('gripper', 'run_speed'),
    )

    camera_config = CameraConfig(
        enable_color=parser.getboolean('camera', 'enable_color', fallback=True),
        enable_depth=parser.getboolean('camera', 'enable_depth', fallback=True),
        frame_timeout_ms=parser.getint('camera', 'frame_timeout_ms', fallback=100),
        sleep_interval=parser.getfloat('camera', 'sleep_interval', fallback=0.01)
    )

    return AppConfig(
        connections=conn_config,
        arm=arm_config,
        gripper=gripper_config,
        camera=camera_config
    )