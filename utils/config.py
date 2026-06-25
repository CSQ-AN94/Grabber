"""
YAML配置系统 - 简洁、清晰、类型安全
设计原则：
1. 配置即文档 - YAML中直接注明单位和含义
2. 最小中间层 - 直接映射到dataclass
3. 类型安全 - 保持强类型检查
4. 单位明确 - 避免隐式转换混乱
"""

import os
import yaml
import logging
import numpy as np
from dataclasses import dataclass
from typing import List, Any


class ConfigError(Exception):
    """配置错误异常类"""
    pass


@dataclass
class ConnectionsConfig:
    """硬件连接配置（双臂）"""
    left_arm_ip: str
    right_arm_ip: str
    arm_port: int
    active_arm: str = "right"   # "left" 或 "right"，决定 ArmController 实际连接哪只臂


@dataclass
class ArmConfig:
    """机械臂配置"""
    home_pose: List[float]              # 关节角度，单位：度
    scanning_pose: List[float]          # 关节角度，单位：度
    zero_pose: List[float]              # 关节角度，单位：度
    dropoff_pose: List[float]           # 关节角度，单位：度
    checkout_scan_pose: List[float]     # 关节角度，单位：度
    scanning_pose_cartesian: List[float]  # 笛卡尔位姿，单位：米和弧度
    zero_pose_cartesian: List[float]    # 笛卡尔位姿，单位：米和弧度
    dropoff_pose_cartesian: List[float] # 笛卡尔位姿，单位：米和弧度
    checkout_scan_pose_cartesian: List[float]  # 笛卡尔位姿，单位：米和弧度


@dataclass
class GripperConfig:
    """夹爪配置（Realman Plus 内置夹爪，JSON 指令控制）"""
    open_time: float   # 夹爪从全闭到全开所需时间（秒），用于 sleep 估算


@dataclass
class UGVConfig:
    """UGV配置"""
    max_dist: float  # 最大移动距离，单位：米
    speed: float     # 移动速度，单位：米/秒


@dataclass
class CalibrationConfig:
    """标定配置"""
    T_end_to_camera: np.ndarray  # 4x4变换矩阵


@dataclass
class SpeechConfig:
    """语音系统配置"""
    app_id: str
    api_key: str
    api_secret: str


@dataclass
class LLMConfig:
    """大语言模型配置"""
    gemini_api_key: str
    model_name: str

@dataclass
class VisionConfig:
    """计算机视觉配置"""
    model_path: str  # YOLOv8模型路径


@dataclass
class CameraConfig:
    """RealSense 相机配置"""
    head_serial: str
    width: int = 640
    height: int = 480
    fps: int = 30


@dataclass
class AppConfig:
    """应用程序主配置类"""
    connections: ConnectionsConfig
    arm: ArmConfig
    gripper: GripperConfig
    ugv: UGVConfig
    calibration: CalibrationConfig
    speech: SpeechConfig
    llm: LLMConfig
    vision: VisionConfig
    camera: CameraConfig


def get_env_var(section: str, key: str, fallback: Any = None) -> Any:
    """
    获取环境变量，格式为 GRABBER_<SECTION>_<KEY>
    如果环境变量不存在，返回fallback值
    """
    env_var_name = f"GRABBER_{section.upper()}_{key.upper()}"
    return os.environ.get(env_var_name, fallback)


def load_config(path: str = 'config.yaml') -> AppConfig:
    """
    加载YAML配置文件
    
    Args:
        path: 配置文件路径
        
    Returns:
        AppConfig: 解析后的配置对象
        
    Raises:
        ConfigError: 配置文件不存在或解析失败
    """
    if not os.path.exists(path):
        raise ConfigError(f"Configuration file not found: {path}")
    
    try:
        with open(path, 'r', encoding='utf-8') as f:
            config_data = yaml.safe_load(f)
        
        if not config_data:
            raise ConfigError("Configuration file is empty")
        
        # 解析各个配置段，支持环境变量覆盖
        def _get_value(section_data: dict, key: str, section_name: str = "", env_converter=None) -> Any:
            """获取配置值，支持环境变量覆盖"""
            if section_name:
                env_value = get_env_var(section_name, key)
                if env_value is not None:
                    if env_converter:
                        try:
                            return env_converter(env_value)
                        except Exception as e:
                            raise ConfigError(f"Failed to convert env var {section_name}.{key}: {e}")
                    return env_value
            
            if key not in section_data:
                raise ConfigError(f"Missing required config key: {key}")
            
            return section_data[key]
        
        # 解析连接配置（双臂）
        conn_data = config_data.get('connections', {})
        connections = ConnectionsConfig(
            left_arm_ip=_get_value(conn_data, 'left_arm_ip', 'connections'),
            right_arm_ip=_get_value(conn_data, 'right_arm_ip', 'connections'),
            arm_port=_get_value(conn_data, 'arm_port', 'connections', int),
            active_arm=conn_data.get('active_arm', 'right'),
        )
        
        # 解析机械臂配置
        arm_data = config_data.get('arm', {})
        arm = ArmConfig(
            home_pose=_get_value(arm_data, 'home_pose'),
            scanning_pose=_get_value(arm_data, 'scanning_pose'),
            zero_pose=_get_value(arm_data, 'zero_pose'),
            dropoff_pose=_get_value(arm_data, 'dropoff_pose'),
            checkout_scan_pose=_get_value(arm_data, 'checkout_scan_pose'),
            scanning_pose_cartesian=_get_value(arm_data, 'scanning_pose_cartesian'),
            zero_pose_cartesian=_get_value(arm_data, 'zero_pose_cartesian'),
            dropoff_pose_cartesian=_get_value(arm_data, 'dropoff_pose_cartesian'),
            checkout_scan_pose_cartesian=_get_value(arm_data, 'checkout_scan_pose_cartesian')
        )
        
        # 解析夹爪配置（Realman Plus，仅需 open_time）
        gripper_data = config_data.get('gripper', {})
        gripper = GripperConfig(
            open_time=_get_value(gripper_data, 'open_time', 'gripper', float),
        )
        
        # 解析UGV配置
        ugv_data = config_data.get('ugv', {})
        ugv = UGVConfig(
            max_dist=_get_value(ugv_data, 'max_dist', 'ugv', float),
            speed=_get_value(ugv_data, 'speed', 'ugv', float)
        )
        
        # 解析标定配置
        calibration_data = config_data.get('calibration', {})
        T_matrix = _get_value(calibration_data, 'T_end_to_camera')
        calibration = CalibrationConfig(
            T_end_to_camera=np.array(T_matrix, dtype=float)
        )
        
        # 解析语音配置
        speech_data = config_data.get('speech', {})
        speech = SpeechConfig(
            app_id=_get_value(speech_data, 'app_id', 'speech'),
            api_key=_get_value(speech_data, 'api_key', 'speech'),
            api_secret=_get_value(speech_data, 'api_secret', 'speech')
        )
        
        # 解析LLM配置
        llm_data = config_data.get('llm', {})
        llm = LLMConfig(
            gemini_api_key=_get_value(llm_data, 'gemini_api_key', 'llm'),
            model_name=_get_value(llm_data, 'model_name', 'llm')
        )
        
        # 解析视觉配置
        vision_data = config_data.get('vision', {})
        vision = VisionConfig(
            model_path=_get_value(vision_data, 'model_path', 'vision')
        )

        # 解析相机配置
        cam_data = config_data.get('camera', {})
        camera = CameraConfig(
            head_serial=cam_data.get('head_serial', '153122071777'),
            width=int(cam_data.get('width', 640)),
            height=int(cam_data.get('height', 480)),
            fps=int(cam_data.get('fps', 30)),
        )

        # 创建主配置对象
        config = AppConfig(
            connections=connections,
            arm=arm,
            gripper=gripper,
            ugv=ugv,
            calibration=calibration,
            speech=speech,
            llm=llm,
            vision=vision,
            camera=camera,
        )
        
        logging.info(f"Successfully loaded configuration from {path}")
        return config
        
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse YAML configuration: {e}")
    except Exception as e:
        if isinstance(e, ConfigError):
            raise
        else:
            raise ConfigError(f"Failed to load configuration: {e}")