import threading
import time
import numpy as np
import cv2
import os
from typing import Optional, Tuple, Dict, Any
from enum import Enum
from pyorbbecsdk import *
from external.pyorbbecsdk.examples.utils import frame_to_bgr_image

class DisplayMode(Enum):
    """显示模式枚举"""
    COLOR = "color"
    DEPTH = "depth"
    COLOR_DEPTH = "color_depth"
    COLOR_VISION = "color_vision"
    ALL = "all"
    NONE = "none"

class CameraThread(threading.Thread):
    """
    后台摄像头线程
    """
    def __init__(self):
        super().__init__()
        # 使用 threading.Event 来控制线程的启停
        self.stop_event = threading.Event()
        # 将线程设置为“守护线程”，这样主程序退出时，它会自动结束
        self.daemon = True

        self.pipeline = None
        self.color_intrinsics = None
        self.color_distortion = None
        
        self._frame_lock = threading.Lock()
        self._latest_color = None
        self._latest_depth = None
        self._latest_pointcloud = None
        self._frame_timestamp = 0
        
        self._display_thread = None
        self._display_mode = DisplayMode.NONE
        self._vision_analyzer = None
        self._point_cloud_filter = None
        
        self.initialization_successful = self._initialize_camera()
        if not self.initialization_successful:
            print("[CameraThread] CRITICAL: Camera initialization failed.")

    def _initialize_camera(self):
        """
        初始化相机
        """
        try:
            self.pipeline = Pipeline()
            config = Config()
            
            # 虽然官网https://www.orbbec.com/products/stereo-vision-camera/gemini-336l/ 提到color分辨率支持(1280,800)
            # 但硬件对齐的深度分辨率是640x480，所以这里使用640x480的彩色分辨率 
            target_color_width = 640
            target_color_height = 480
            target_color_format = OBFormat.BGR
            target_color_fps = 60

            # 获取并验证目标彩色相机配
            profile_list = self.pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
            if not profile_list:
                print("[CameraThread] CRITICAL: Could not get color profiles.")
                return False
            
            color_profile = profile_list.get_video_stream_profile(
                target_color_width, target_color_height, target_color_format, target_color_fps
            )
            if not color_profile:
                print(f"[CameraThread] CRITICAL: Target color profile not found.")
                return False
                
            print(f"[CameraThread] Color profile: {color_profile}")

            # 使用深度到彩色的硬件对齐来获取深度profile，防止手搓对齐带来的误差
            hw_d2c_profile_list = self.pipeline.get_d2c_depth_profile_list(color_profile, OBAlignMode.HW_MODE)
            if not hw_d2c_profile_list or len(hw_d2c_profile_list) == 0:
                print("[CameraThread] CRITICAL: No HW-aligned depth profiles.")
                return False
            depth_profile = hw_d2c_profile_list[1] # 680x480profile
            print(f"[CameraThread] Depth profile: {depth_profile}")
            
            # 保存color的内参和畸变，深度的不保存，因为深度的会对齐到彩色 
            self.color_intrinsics = color_profile.as_video_stream_profile().get_intrinsic()
            self.color_distortion = color_profile.as_video_stream_profile().get_distortion()

            # 配置并启动Pipeline
            config.enable_stream(color_profile)
            config.enable_stream(depth_profile)
            config.set_align_mode(OBAlignMode.HW_MODE)
            self.pipeline.start(config)
            
            print("[CameraThread] Camera initialized successfully with HW D2C alignment.")
            print(f"[CameraThread] Intrinsics: fx={self.color_intrinsics.fx:.1f}, fy={self.color_intrinsics.fy:.1f}")
            print(f"[CameraThread] Principal point: cx={self.color_intrinsics.cx:.1f}, cy={self.color_intrinsics.cy:.1f}")
            return True
            
        except Exception as e:
            print(f"[CameraThread] Initialization failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    def run(self):
        """
        线程主循环。将以最大可能的速度获取和处理帧，合成点云
        """
        # 如果初始化失败，则此线程不执行任何操作
        if not self.initialization_successful:
            return

        while not self.stop_event.is_set():
            try:
                frames = self.pipeline.wait_for_frames(1000)
                if frames is None:
                    continue

                color_frame = frames.get_color_frame()
                depth_frame = frames.get_depth_frame()

                if color_frame is None or depth_frame is None:
                    continue
                
                # --- 数据处理 ---
                color_image = frame_to_bgr_image(color_frame)
                # 深度帧转ndarray
                depth_data_uint16 = np.frombuffer(depth_frame.get_data(), dtype=np.uint16).reshape(
                    depth_frame.get_height(), depth_frame.get_width()
                )
                # 转float32计算
                depth_data_mm = depth_data_uint16.astype(np.float32) * depth_frame.get_depth_scale()
                depth_data_meters = depth_data_mm / 1000.0
                
                # 同步的color,depth,pointcloud
                with self._frame_lock:
                    self._latest_color = color_image.copy()
                    self._latest_depth = depth_data_meters.copy()
                    self._frame_timestamp = time.time()
                    self._latest_pointcloud = None
                
            except Exception as e:
                print(f"[CameraThread] Error in main loop: {e}")
                time.sleep(1)

    def get_latest_frames(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """
        获取最新的color/depth帧
        """
        with self._frame_lock:
            color = self._latest_color.copy() if self._latest_color is not None else None
            depth = self._latest_depth.copy() if self._latest_depth is not None else None
            return color, depth

    def get_frame_timestamp(self) -> float:
        """
        获取最新的timestamp
        """
        with self._frame_lock:
            return self._frame_timestamp

    def generate_pointcloud(self, max_depth: float = 3.0) -> Optional[np.ndarray]:
        """
        用color和depth合成点云
        Args:
            max_depth: 最大深度阈值（米），超过此距离的点将被忽略
            
        Returns:
            形状为[N, 6] [x, y, z, r, g, b]的点云Numpy数组，失败则返回None
        """
        if not self.initialization_successful:
            return None
            
        color, depth = self.get_latest_frames()
        if color is None or depth is None:
            return None

        # 如果已经有缓存的点云，直接返回
        with self._frame_lock:
            if self._latest_pointcloud is not None:
                return self._latest_pointcloud.copy()

        # 生成点云
        try:
            fx, fy = self.color_intrinsics.fx, self.color_intrinsics.fy
            cx, cy = self.color_intrinsics.cx, self.color_intrinsics.cy
            
            h, w = depth.shape
            points = []
            colors = []
            
            # 创建网格坐标，并进行下采样以提高性能
            v, u = np.mgrid[0:h:4, 0:w:4]  # 每4个像素取一个点
            v_flat, u_flat = v.flatten(), u.flatten()
            
            # 获取深度值
            z_vals = depth[v_flat, u_flat]
            
            # 过滤无效深度值
            valid_mask = (z_vals > 0) & (z_vals < max_depth)
            v_valid = v_flat[valid_mask]
            u_valid = u_flat[valid_mask]
            z_valid = z_vals[valid_mask]
            
            if len(z_valid) == 0:
                return None
            
            # 计算3D坐标
            x = (u_valid - cx) * z_valid / fx
            y = (v_valid - cy) * z_valid / fy
            
            colors = color[v_valid, u_valid]
            colors_rgb = colors[:, [2, 1, 0]]  # BGR -> RGB
            
            # 合并为 [N, 6]: [x, y, z, r, g, b]
            pointcloud = np.column_stack([x, y, z_valid, colors_rgb])
            
            # 缓存结果
            with self._frame_lock:
                self._latest_pointcloud = pointcloud.copy()
                
            return pointcloud
            
        except Exception as e:
            print(f"[CameraThread] Point cloud generation failed: {e}")
            return None
    
    def save_pointcloud_ply(self, filepath: str, max_depth: float = 3.0) -> bool:
        """
        将当前场景的点云保存为PLY文件
        
        Args:
            filepath: PLY文件的保存路径
            max_depth: 最大深度阈值（米）
            
        Returns:
            布尔值，表示是否保存成功
        """
        pointcloud = self.generate_pointcloud(max_depth)
        if pointcloud is None:
            print(f"[CameraThread] Cannot save PLY: point cloud generation failed")
            return False
            
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            
            # 写入PLY文件
            with open(filepath, 'w') as f:
                # PLY文件头
                f.write("ply\n")
                f.write("format ascii 1.0\n")
                f.write(f"element vertex {len(pointcloud)}\n")
                f.write("property float x\n")
                f.write("property float y\n")
                f.write("property float z\n")
                f.write("property uchar red\n")
                f.write("property uchar green\n")
                f.write("property uchar blue\n")
                f.write("end_header\n")
                
                # 写入点数据
                for point in pointcloud:
                    x, y, z, r, g, b = point
                    f.write(f"{x:.6f} {y:.6f} {z:.6f} {int(r)} {int(g)} {int(b)}\n")
            
            print(f"[CameraThread] Point cloud saved to {filepath} ({len(pointcloud)} points)")
            return True
            
        except Exception as e:
            print(f"[CameraThread] Failed to save PLY file: {e}")
            return False

    def start_display(self, mode: DisplayMode = DisplayMode.COLOR, vision_analyzer=None):
        """
        启动一个独立的线程来显示摄像头画面
        
        Args:
            mode: 显示模式 (DisplayMode枚举)
            vision_analyzer: 一个可选的视觉分析器实例（如YOLO），用于在图像上绘制检测结果
        """
        if self._display_thread and self._display_thread.is_alive():
            print("[CameraThread] Display already running")
            return
            
        self._display_mode = mode
        self._vision_analyzer = vision_analyzer
        self._display_thread = threading.Thread(target=self._display_worker, daemon=True)
        self._display_thread.start()
        print(f"[CameraThread] Display started with mode: {mode.value}")

    def stop_display(self):
        """停止显示线程"""
        if self._display_thread:
            self._display_mode = DisplayMode.NONE
            if self._display_thread.is_alive():
                self._display_thread.join(timeout=2)
            self._display_thread = None  # 清理线程引用
            cv2.destroyAllWindows()
            print("[CameraThread] Display stopped")
            
    def is_display_running(self):
        """检查显示线程是否正在运行"""
        return self._display_thread and self._display_thread.is_alive()

    def _display_worker(self):
        """显示线程的工作循环"""
        print(f"[Display] Started with mode: {self._display_mode.value}")
        print("[Display] Press 'q' in any OpenCV window to stop display")
        
        try:
            while self._display_mode != DisplayMode.NONE:
                color, depth = self.get_latest_frames()
                if color is None:
                    time.sleep(0.01)
                    continue
                
                # 根据模式选择显示内容
                if self._display_mode == DisplayMode.COLOR:
                    self._show_color(color)
                    
                elif self._display_mode == DisplayMode.DEPTH:
                    self._show_depth(depth)
                    
                elif self._display_mode == DisplayMode.COLOR_DEPTH:
                    self._show_color_depth(color, depth)
                    
                elif self._display_mode == DisplayMode.COLOR_VISION:
                    self._show_color_vision(color, depth)
                    
                elif self._display_mode == DisplayMode.ALL:
                    self._show_all(color, depth)

                # 检测退出键
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    print("[Display] 'q' pressed, stopping display")
                    break
                    
        except Exception as e:
            print(f"[Display] Error: {e}")
        finally:
            self._display_mode = DisplayMode.NONE  # 确保状态清理
            cv2.destroyAllWindows()
            print("[Display] Windows closed")

    def _show_color(self, color):
        """显示彩色图像"""
        if color is not None:
            color_rgb = cv2.cvtColor(color, cv2.COLOR_BGR2RGB)
            cv2.imshow('Color Feed', color_rgb)

    def _show_depth(self, depth):
        """显示深度图像"""
        if depth is not None:
            depth_vis = cv2.normalize(depth, None, 0, 255, cv2.NORM_MINMAX, dtype=cv2.CV_8U)
            depth_vis = cv2.applyColorMap(depth_vis, cv2.COLORMAP_JET)
            cv2.imshow('Depth Feed', depth_vis)

    def _show_color_depth(self, color, depth):
        """同时显示彩色和深度图像"""
        self._show_color(color)
        self._show_depth(depth)

    def _show_color_vision(self, color, depth):
        """显示带有视觉分析结果的彩色图像"""
        if color is not None and self._vision_analyzer:
            try:
                detections = self._vision_analyzer.analyze_image(color, depth)
                color_with_detections = self._vision_analyzer.draw_detections(color, detections)
                color_rgb = cv2.cvtColor(color_with_detections, cv2.COLOR_BGR2RGB)
                cv2.imshow('Color + Vision', color_rgb)
            except Exception as e:
                print(f"[Display] Vision analysis failed: {e}")
                self._show_color(color)
        else:
            self._show_color(color)

    def _show_all(self, color, depth):
        """显示所有视图"""
        self._show_color(color)
        self._show_depth(depth)
        if self._vision_analyzer:
            self._show_color_vision(color, depth)

    def get_camera_intrinsics(self) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """获取相机内参和畸变系数"""
        if not self.initialization_successful:
            return None, None
            
        K = np.array([
            [self.color_intrinsics.fx, 0, self.color_intrinsics.cx],
            [0, self.color_intrinsics.fy, self.color_intrinsics.cy],
            [0, 0, 1]
        ])
        
        dist = np.array([
            self.color_distortion.k1,
            self.color_distortion.k2,
            self.color_distortion.p1,
            self.color_distortion.p2,
            self.color_distortion.k3
        ])
        
        return K, dist
    
    def get_pointcloud_data(self, max_depth: float = 3.0) -> Optional[Dict[str, Any]]:
        """
        获取用于数据传输的点云信息，格式为JSON友好型
        
        Args:
            max_depth: 最大深度（米）
            
        Returns:
            一个包含点云数据、时间戳和相机参数的字典，失败则返回None
        """
        pointcloud = self.generate_pointcloud(max_depth)
        if pointcloud is None:
            return None
            
        K, dist = self.get_camera_intrinsics()
        if K is None:
            return None
            
        return {
            "points": pointcloud.tolist(),  # 转换为list以便JSON序列化
            "timestamp": self.get_frame_timestamp(),
            "camera_intrinsics": {
                "fx": float(K[0, 0]),
                "fy": float(K[1, 1]),
                "cx": float(K[0, 2]),
                "cy": float(K[1, 2])
            },
            "distortion": dist.tolist() if dist is not None else None,
            "point_count": len(pointcloud),
            "depth_range": {
                "min": float(pointcloud[:, 2].min()),
                "max": float(pointcloud[:, 2].max())
            }
        }
    
    def export_scene_data(self, output_dir: str = "./exports", max_depth: float = 3.0) -> Optional[str]:
        """
        将当前场景导出为PLY文件，并以时间戳命名
        
        Args:
            output_dir: 导出目录
            max_depth: 最大深度
            
        Returns:
            成功则返回PLY文件路径，否则返回None
        """
        timestamp = int(time.time() * 1000)  # 毫秒级时间戳
        filename = f"scene_{timestamp}.ply"
        filepath = os.path.join(output_dir, filename)
        
        if self.save_pointcloud_ply(filepath, max_depth):
            return filepath
        else:
            return None

    def stop(self):
        """停止线程"""
        print("[CameraThread] Stop signal received")
        self.stop_display()
        self.stop_event.set()

    def join(self, timeout=None):
        """重写join方法，确保Pipeline在线程结束前停止"""
        if self.pipeline and self.initialization_successful:
            try:
                self.pipeline.stop()
                print("[CameraThread] Pipeline stopped")
            except Exception as e:
                print(f"[CameraThread] Error stopping pipeline: {e}")
        super().join(timeout)
    
    def get_export_info(self) -> Dict[str, Any]:
        """获取用于导出的相关信息"""
        return {
            "camera_ready": self.initialization_successful,
            "has_frames": self._latest_color is not None and self._latest_depth is not None,
            "frame_timestamp": self.get_frame_timestamp(),
            "supported_formats": ["PLY"],
            "max_points": 50000,  # 这是一个估计值
            "export_directory": "./exports"
        }
