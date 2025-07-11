import configparser
from dataclasses import dataclass
import numpy as np
from typing import List
import ast

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

@dataclass
class RailConfig:
    port: str
    home_position: float
    scan_start: float
    scan_end: float
    scan_speed: float

@dataclass
class CalibrationConfig:
    T_end_to_camera: np.ndarray  # 手眼标定矩阵

@dataclass
class LLMConfig:
    gemini_api_key: str

@dataclass
class SpeechConfig:
    openai_api_key: str

@dataclass
class VisionConfig:
    model_path: str

# --- 主配置类，聚合所有部分 ---
@dataclass
class AppConfig:
    connections: ConnectionsConfig
    arm: ArmConfig
    gripper: GripperConfig
    camera: CameraConfig
    rail: RailConfig
    calibration: CalibrationConfig
    llm: LLMConfig
    speech: SpeechConfig
    vision: VisionConfig
    
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
    
    def _parse_matrix(s):
        # 解析形如[[...],[...],[...],[...]]的字符串为numpy数组
        return np.array(ast.literal_eval(s), dtype=float)
    
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

    rail_config = RailConfig(
        port=parser.get('rail', 'port', fallback='/dev/ttyUSB0'),
        home_position=parser.getfloat('rail', 'home_position', fallback=0.0),
        scan_start=parser.getfloat('rail', 'scan_start', fallback=0.0),
        scan_end=parser.getfloat('rail', 'scan_end', fallback=1.0),
        scan_speed=parser.getfloat('rail', 'scan_speed', fallback=0.1)
    )

    llm_config = LLMConfig(
        gemini_api_key=parser.get('llm', 'gemini_api_key')
    )

    speech_config = SpeechConfig(
        openai_api_key=parser.get('speech', 'openai_api_key')
    )

    vision_config = VisionConfig(
        model_path=parser.get('vision', 'model_path')
    )

    # 解析手眼标定矩阵
    T_end_to_camera = _parse_matrix(parser.get('calibration', 'T_end_to_camera', fallback=str(np.eye(4).tolist())))
    calibration_config = CalibrationConfig(T_end_to_camera=T_end_to_camera)

    return AppConfig(
        connections=conn_config,
        arm=arm_config,
        gripper=gripper_config,
        camera=camera_config,
        rail=rail_config,
        calibration=calibration_config,
        llm=llm_config,
        speech=speech_config,
        vision=vision_config
    )