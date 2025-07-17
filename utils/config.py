import configparser
import os
import logging
from dataclasses import dataclass
import numpy as np
from typing import List, Optional, Any, Dict
import ast


class ConfigError(Exception):
    """配置错误异常类"""
    pass


@dataclass
class ConnectionsConfig:
    """硬件连接配置"""
    arm_ip: str
    arm_port: int


@dataclass
class ArmConfig:
    """机械臂配置"""
    scanning_pose: List[float]
    zero_pose: List[float]
    dropoff_pose: List[float]
    checkout_scan_pose: List[float]
    scanning_pose_cartesian: List[float]
    zero_pose_cartesian: List[float]
    dropoff_pose_cartesian: List[float]
    checkout_scan_pose_cartesian: List[float]

@dataclass
class GripperConfig:
    """夹爪配置"""
    zero_speed: int
    init_speed: int
    run_speed: int


# CameraConfig 已删除 - 相机使用硬编码配置


@dataclass
class RailConfig:
    """导轨配置"""
    home_position: float
    scan_start: float
    scan_end: float
    scan_speed: float


@dataclass
class CalibrationConfig:
    """标定配置"""
    T_end_to_camera: np.ndarray


@dataclass
class SpeechConfig:
    """语音系统配置"""
    notebook_ip: str
    speaker_port: int
    app_id: str
    api_key: str
    api_secret: str


@dataclass
class LLMConfig:
    """大语言模型配置"""
    gemini_api_key: str
    model_name: str


@dataclass
class AgentConfig:
    """智能Agent配置"""
    audio_sample_rate: int
    audio_channels: int
    audio_chunk_size: int


@dataclass
class VisionConfig:
    """计算机视觉配置"""
    model_path: str

@dataclass
class SystemConfig:
    """系统配置"""
    debug_mode: bool
    environment: str


@dataclass
class AppConfig:
    """应用程序主配置类"""
    connections: ConnectionsConfig
    arm: ArmConfig
    gripper: GripperConfig
    rail: RailConfig
    calibration: CalibrationConfig
    speech: SpeechConfig
    llm: LLMConfig
    agent: AgentConfig
    vision: VisionConfig
    system: SystemConfig

def get_env_var(section: str, key: str, fallback: Any = None) -> Any:
    """
    获取环境变量，格式为 GRABBER_<SECTION>_<KEY>
    如果环境变量不存在，返回fallback值
    """
    env_var_name = f"GRABBER_{section.upper()}_{key.upper()}"
    return os.environ.get(env_var_name, fallback)


def validate_config(config: AppConfig) -> None:
    """
    验证配置的有效性
    """
    # 验证IP地址格式
    import socket
    try:
        socket.inet_aton(config.connections.arm_ip)
    except socket.error:
        raise ConfigError(f"Invalid arm IP address: {config.connections.arm_ip}")
    
    # 验证端口范围
    if not (1 <= config.connections.arm_port <= 65535):
        raise ConfigError(f"Invalid arm port: {config.connections.arm_port}")
    
    # 验证关节姿态长度
    for pose_name, pose in [
        ("scanning_pose", config.arm.scanning_pose),
        ("zero_pose", config.arm.zero_pose),
        ("dropoff_pose", config.arm.dropoff_pose),
        ("checkout_scan_pose", config.arm.checkout_scan_pose)
    ]:
        if len(pose) != 6:
            raise ConfigError(f"Invalid {pose_name}: must have 6 joint angles, got {len(pose)}")
    
    # 验证导轨位置范围
    if config.rail.scan_start > config.rail.scan_end:
        raise ConfigError("Rail scan_start must be <= scan_end")
    
    # 验证手眼标定矩阵
    if config.calibration.T_end_to_camera.shape != (4, 4):
        raise ConfigError("T_end_to_camera must be a 4x4 matrix")
    
    # 验证环境类型
    valid_environments = ["development", "production", "testing"]
    if config.system.environment not in valid_environments:
        raise ConfigError(f"Invalid environment: {config.system.environment}")


def load_config(path: str = 'config.ini') -> AppConfig:
    """
    读取.ini文件，解析所有部分，并返回一个结构化的AppConfig对象。
    支持环境变量覆盖敏感配置。
    """
    if not os.path.exists(path):
        raise ConfigError(f"Configuration file not found: {path}")
    
    parser = configparser.ConfigParser()
    parser.read(path, encoding='utf-8')

    def _parse_list(s: str) -> List[float]:
        """解析逗号分隔的字符串为浮点数列表"""
        try:
            return [float(x.strip()) for x in s.split(',')]
        except ValueError as e:
            raise ConfigError(f"Failed to parse list: {s}, error: {e}")
    
    def _parse_joint_angles(s: str) -> List[float]:
        """解析关节角度并转换为弧度"""
        try:
            degrees = [float(x.strip()) for x in s.split(',')]
            return [np.deg2rad(deg) for deg in degrees]
        except ValueError as e:
            raise ConfigError(f"Failed to parse joint angles: {s}, error: {e}")
    
    def _parse_matrix(s: str) -> np.ndarray:
        """解析形如[[...],[...],[...],[...]]的字符串为numpy数组"""
        try:
            return np.array(ast.literal_eval(s), dtype=float)
        except (ValueError, SyntaxError) as e:
            raise ConfigError(f"Failed to parse matrix: {s}, error: {e}")
    
    def _get_config_value(section: str, key: str, parser_func=None, fallback=None, required=True):
        """获取配置值，支持环境变量覆盖"""
        # 首先检查环境变量
        env_value = get_env_var(section, key)
        if env_value is not None:
            if parser_func:
                try:
                    return parser_func(env_value)
                except Exception as e:
                    raise ConfigError(f"Failed to parse environment variable GRABBER_{section.upper()}_{key.upper()}: {e}")
            return env_value
        
        # 然后检查配置文件
        try:
            if parser_func:
                return parser_func(section, key, fallback=fallback)
            else:
                return parser.get(section, key, fallback=fallback)
        except configparser.NoSectionError:
            if required and fallback is None:
                raise ConfigError(f"Missing configuration section: {section}")
            return fallback
        except configparser.NoOptionError:
            if required and fallback is None:
                raise ConfigError(f"Missing configuration option: {section}.{key}")
            return fallback
    
    try:
        # 连接配置
        conn_config = ConnectionsConfig(
            arm_ip=_get_config_value('connections', 'arm_ip'),
            arm_port=_get_config_value('connections', 'arm_port', parser.getint)
        )

        # 机械臂配置
        arm_config = ArmConfig(
            scanning_pose=_parse_joint_angles(_get_config_value('arm', 'scanning_pose')),
            zero_pose=_parse_joint_angles(_get_config_value('arm', 'zero_pose')),
            dropoff_pose=_parse_joint_angles(_get_config_value('arm', 'dropoff_pose')),
            checkout_scan_pose=_parse_joint_angles(_get_config_value('arm', 'checkout_scan_pose')),
            scanning_pose_cartesian=_parse_list(_get_config_value('arm', 'scanning_pose_cartesian')),
            zero_pose_cartesian=_parse_list(_get_config_value('arm', 'zero_pose_cartesian')),
            dropoff_pose_cartesian=_parse_list(_get_config_value('arm', 'dropoff_pose_cartesian')),
            checkout_scan_pose_cartesian=_parse_list(_get_config_value('arm', 'checkout_scan_pose_cartesian'))
        )

        # 夹爪配置
        gripper_config = GripperConfig(
            zero_speed=_get_config_value('gripper', 'zero_speed', parser.getint),
            init_speed=_get_config_value('gripper', 'init_speed', parser.getint),
            run_speed=_get_config_value('gripper', 'run_speed', parser.getint)
        )

        # 导轨配置
        rail_config = RailConfig(
            home_position=_get_config_value('rail', 'home_position', parser.getfloat, 0.0),
            scan_start=_get_config_value('rail', 'scan_start', parser.getfloat, 0.0),
            scan_end=_get_config_value('rail', 'scan_end', parser.getfloat, 1.0),
            scan_speed=_get_config_value('rail', 'scan_speed', parser.getfloat, 0.1)
        )

        # 标定配置
        T_end_to_camera = _parse_matrix(_get_config_value('calibration', 'T_end_to_camera', 
                                                          fallback=str(np.eye(4).tolist())))
        calibration_config = CalibrationConfig(
            T_end_to_camera=T_end_to_camera
        )

        # Speech配置
        speech_config = SpeechConfig(
            notebook_ip=_get_config_value('speech', 'notebook_ip'),
            speaker_port=_get_config_value('speech', 'speaker_port', parser.getint),
            app_id=_get_config_value('speech', 'app_id'),
            api_key=_get_config_value('speech', 'api_key'),
            api_secret=_get_config_value('speech', 'api_secret')
        )

        # LLM配置
        llm_config = LLMConfig(
            gemini_api_key=_get_config_value('llm', 'gemini_api_key'),
            model_name=_get_config_value('llm', 'model_name', fallback="gemini-2.0-flash-live-001")
        )

        # Agent配置
        agent_config = AgentConfig(
            audio_sample_rate=_get_config_value('agent', 'audio_sample_rate', parser.getint, 16000),
            audio_channels=_get_config_value('agent', 'audio_channels', parser.getint, 1),
            audio_chunk_size=_get_config_value('agent', 'audio_chunk_size', parser.getint, 1024)
        )

        # 视觉配置
        vision_config = VisionConfig(
            model_path=_get_config_value('vision', 'model_path')
        )

        # 系统配置
        system_config = SystemConfig(
            debug_mode=_get_config_value('system', 'debug_mode', parser.getboolean, False),
            environment=_get_config_value('system', 'environment', fallback="development")
        )

        # 创建主配置对象
        config = AppConfig(
            connections=conn_config,
            arm=arm_config,
            gripper=gripper_config,
            rail=rail_config,
            calibration=calibration_config,
            speech=speech_config,
            llm=llm_config,
            agent=agent_config,
            vision=vision_config,
            system=system_config
        )

        # 验证配置
        validate_config(config)
        
        return config

    except Exception as e:
        if isinstance(e, ConfigError):
            raise
        else:
            raise ConfigError(f"Failed to load configuration: {e}")


def setup_logging(log_level: str = "INFO") -> None:
    """
    设置默认日志系统
    """
    # 创建日志目录
    log_dir = "logs"
    if not os.path.exists(log_dir):
        os.makedirs(log_dir, exist_ok=True)
    
    # 配置日志
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    handlers = []
    
    # 控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(log_format))
    handlers.append(console_handler)
    
    # 文件处理器
    from logging.handlers import RotatingFileHandler
    file_handler = RotatingFileHandler(
        "logs/grabber.log",
        maxBytes=10485760,  # 10MB
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(logging.Formatter(log_format))
    handlers.append(file_handler)
    
    logging.basicConfig(
        level=getattr(logging, log_level.upper()),
        handlers=handlers,
        format=log_format
    )