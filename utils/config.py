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
from typing import List, Optional, Any, Dict


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
    home_pose: List[float]              # 关节角度，单位：度
    scanning_pose: List[float]          # 关节角度，单位：度
    zero_pose: List[float]              # 关节角度，单位：度
    dropoff_pose: List[float]           # 关节角度，单位：度
    checkout_scan_pose: List[float]     # 关节角度，单位：度
    tcp_pose: List[float]               # TCP位姿，单位：米和弧度
    scanning_pose_cartesian: List[float]  # 笛卡尔位姿，单位：米和弧度
    zero_pose_cartesian: List[float]    # 笛卡尔位姿，单位：米和弧度
    dropoff_pose_cartesian: List[float] # 笛卡尔位姿，单位：米和弧度
    checkout_scan_pose_cartesian: List[float]  # 笛卡尔位姿，单位：米和弧度


@dataclass
class GripperConfig:
    """夹爪配置"""
    zero_speed: int
    init_speed: int
    run_speed: int


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
class AgentConfig:
    """智能Agent配置"""
    audio_sample_rate: int  # 采样率，单位：Hz
    audio_channels: int     # 声道数
    audio_chunk_size: int   # 音频块大小


@dataclass
class VisionConfig:
    """计算机视觉配置"""
    model_path: str  # YOLOv8模型路径


@dataclass
class ItemConfig:
    """单个物品配置"""
    z_offset: float        # Z轴偏移量，单位：米
    roll: float            # 抓取姿态roll角，单位：弧度  
    pitch: float           # 抓取姿态pitch角，单位：弧度
    yaw: float             # 抓取姿态yaw角，单位：弧度
    gripper_openness: float # 夹爪张开度，0.0=完全闭合，1.0=完全张开
    price: float           # 物品价格，单位：元


@dataclass
class ItemsConfig:
    """物品配置容器"""
    items: Dict[str, ItemConfig]
    
    def get_item_config(self, item_name: str) -> Optional[ItemConfig]:
        """获取指定物品配置"""
        return self.items.get(item_name)
    
    def get_all_items(self) -> List[str]:
        """获取所有物品名称"""
        return list(self.items.keys())
    
    def get_item_price(self, item_name: str) -> Optional[float]:
        """获取物品价格"""
        item_config = self.get_item_config(item_name)
        return item_config.price if item_config else None


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
    ugv: UGVConfig
    calibration: CalibrationConfig
    speech: SpeechConfig
    llm: LLMConfig
    agent: AgentConfig
    vision: VisionConfig
    items: ItemsConfig
    system: SystemConfig


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
        
        # 解析连接配置
        conn_data = config_data.get('connections', {})
        connections = ConnectionsConfig(
            arm_ip=_get_value(conn_data, 'arm_ip', 'connections'),
            arm_port=_get_value(conn_data, 'arm_port', 'connections', int)
        )
        
        # 解析机械臂配置
        arm_data = config_data.get('arm', {})
        arm = ArmConfig(
            home_pose=_get_value(arm_data, 'home_pose'),
            scanning_pose=_get_value(arm_data, 'scanning_pose'),
            zero_pose=_get_value(arm_data, 'zero_pose'),
            dropoff_pose=_get_value(arm_data, 'dropoff_pose'),
            checkout_scan_pose=_get_value(arm_data, 'checkout_scan_pose'),
            tcp_pose=_get_value(arm_data, 'tcp_pose'),
            scanning_pose_cartesian=_get_value(arm_data, 'scanning_pose_cartesian'),
            zero_pose_cartesian=_get_value(arm_data, 'zero_pose_cartesian'),
            dropoff_pose_cartesian=_get_value(arm_data, 'dropoff_pose_cartesian'),
            checkout_scan_pose_cartesian=_get_value(arm_data, 'checkout_scan_pose_cartesian')
        )
        
        # 解析夹爪配置
        gripper_data = config_data.get('gripper', {})
        gripper = GripperConfig(
            zero_speed=_get_value(gripper_data, 'zero_speed', 'gripper', int),
            init_speed=_get_value(gripper_data, 'init_speed', 'gripper', int),
            run_speed=_get_value(gripper_data, 'run_speed', 'gripper', int)
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
        
        # 解析Agent配置
        agent_data = config_data.get('agent', {})
        agent = AgentConfig(
            audio_sample_rate=_get_value(agent_data, 'audio_sample_rate', 'agent', int),
            audio_channels=_get_value(agent_data, 'audio_channels', 'agent', int),
            audio_chunk_size=_get_value(agent_data, 'audio_chunk_size', 'agent', int)
        )
        
        # 解析视觉配置
        vision_data = config_data.get('vision', {})
        vision = VisionConfig(
            model_path=_get_value(vision_data, 'model_path', 'vision')
        )
        
        # 解析系统配置
        system_data = config_data.get('system', {})
        system = SystemConfig(
            debug_mode=_get_value(system_data, 'debug_mode', 'system', bool),
            environment=_get_value(system_data, 'environment', 'system')
        )
        
        # 解析物品配置
        items_data = config_data.get('items', {})
        items_dict = {}
        
        for item_name, item_data in items_data.items():
            try:
                items_dict[item_name] = ItemConfig(
                    z_offset=float(item_data['z_offset']),
                    roll=float(item_data['roll']),
                    pitch=float(item_data['pitch']),
                    yaw=float(item_data['yaw']),
                    gripper_openness=float(item_data['gripper_openness']),
                    price=float(item_data['price'])
                )
            except (KeyError, ValueError, TypeError) as e:
                logging.warning(f"Failed to parse config for item '{item_name}': {e}")
                # 使用默认配置
                items_dict[item_name] = ItemConfig(
                    z_offset=0.0,
                    roll=3.14159,
                    pitch=0.0,
                    yaw=0.0,
                    gripper_openness=0.8,
                    price=0.0
                )
        
        items = ItemsConfig(items=items_dict)
        
        # 创建主配置对象
        config = AppConfig(
            connections=connections,
            arm=arm,
            gripper=gripper,
            ugv=ugv,
            calibration=calibration,
            speech=speech,
            llm=llm,
            agent=agent,
            vision=vision,
            items=items,
            system=system
        )
        
        # 验证配置
        validate_config(config)
        
        logging.info(f"Successfully loaded configuration from {path}")
        logging.info(f"Loaded {len(items.items)} item configurations")
        
        return config
        
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse YAML configuration: {e}")
    except Exception as e:
        if isinstance(e, ConfigError):
            raise
        else:
            raise ConfigError(f"Failed to load configuration: {e}")


def validate_config(config: AppConfig) -> None:
    """
    验证配置的有效性
    
    Args:
        config: 待验证的配置对象
        
    Raises:
        ConfigError: 配置验证失败
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
        ("home_pose", config.arm.home_pose),
        ("scanning_pose", config.arm.scanning_pose),
        ("zero_pose", config.arm.zero_pose),
        ("dropoff_pose", config.arm.dropoff_pose),
        ("checkout_scan_pose", config.arm.checkout_scan_pose)
    ]:
        if len(pose) != 6:
            raise ConfigError(f"Invalid {pose_name}: must have 6 joint angles, got {len(pose)}")
    
    # 验证TCP位姿长度
    if len(config.arm.tcp_pose) != 6:
        raise ConfigError(f"Invalid tcp_pose: must have 6 elements, got {len(config.arm.tcp_pose)}")
    
    # 验证笛卡尔位姿长度
    for pose_name, pose in [
        ("scanning_pose_cartesian", config.arm.scanning_pose_cartesian),
        ("zero_pose_cartesian", config.arm.zero_pose_cartesian),
        ("dropoff_pose_cartesian", config.arm.dropoff_pose_cartesian),
        ("checkout_scan_pose_cartesian", config.arm.checkout_scan_pose_cartesian)
    ]:
        if len(pose) != 6:
            raise ConfigError(f"Invalid {pose_name}: must have 6 elements, got {len(pose)}")
    
    # 验证手眼标定矩阵
    if config.calibration.T_end_to_camera.shape != (4, 4):
        raise ConfigError("T_end_to_camera must be a 4x4 matrix")
    
    # 验证环境类型
    valid_environments = ["development", "production", "testing"]
    if config.system.environment not in valid_environments:
        raise ConfigError(f"Invalid environment: {config.system.environment}")
    
    # 验证物品配置
    for item_name, item_config in config.items.items.items():
        # 验证夹爪张开度范围
        if not (0.0 <= item_config.gripper_openness <= 1.0):
            raise ConfigError(f"Invalid gripper_openness for {item_name}: must be between 0.0 and 1.0")
        
        # 验证价格非负
        if item_config.price < 0:
            raise ConfigError(f"Invalid price for {item_name}: must be non-negative")


def setup_logging(log_level: str = "INFO") -> None:
    """设置默认日志系统"""
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