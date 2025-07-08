import threading
import time
import numpy as np
from pyorbbecsdk import *
from external.pyorbbecsdk.examples.utils import frame_to_bgr_image

class CameraThread(threading.Thread):
    """
    后台摄像头线程
    持续地从相机硬件获取帧，并将其安全地放入共享状态对象中。
    """
    def __init__(self, shared_state, camera_config):
        super().__init__()
        self.shared_state = shared_state
        self.camera_config = camera_config
        # 使用 threading.Event 来控制线程的启停
        self.stop_event = threading.Event()
        # 将线程设置为“守护线程”，这样主程序退出时，它会自动结束
        self.daemon = True

        # --- 将硬件初始化与对象创建分离 ---
        self.pipeline = None
        self.color_intrinsics = None
        self.color_distortion = None
        
        # 尝试初始化，但不会让程序崩溃
        self.initialization_successful = self._initialize_camera()
        if not self.initialization_successful:
            print("[CameraThread] CRITICAL: Camera initialization failed. Thread will not produce data.")

    def _initialize_camera(self):
        """
        初始化相机。
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

            # 获取并验证目标彩色相机配置
            profile_list = self.pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
            if not profile_list:
                print("[CameraThread] CRITICAL FAIL: Could not get any color profiles.")
                return False
            
            color_profile = profile_list.get_video_stream_profile(
                target_color_width, target_color_height, target_color_format, target_color_fps
            )
            if not color_profile:
                print(f"[CameraThread] CRITICAL FAIL: The target color profile ({target_color_width}x{target_color_height}@{target_color_fps}) could not be found in the profile list.")
                return False
                
            print(f"[CameraThread] INFO: Successfully found target color profile: {color_profile}")

            # 使用深度到彩色的硬件对齐来获取深度profile，防止手搓对齐带来的误差
            hw_d2c_profile_list = self.pipeline.get_d2c_depth_profile_list(color_profile, OBAlignMode.HW_MODE)
            if not hw_d2c_profile_list or len(hw_d2c_profile_list) == 0:
                print(f"[CameraThread] CRITICAL FAIL: SDK reports NO compatible HW-aligned depth profiles for our chosen color profile. This should not happen based on our litmus test.")
                return False
            depth_profile = hw_d2c_profile_list[0]
            print(f"[CameraThread] INFO: Found compatible HW-aligned depth profile: {depth_profile}")
            
            # 保存color的内参和畸变，深度的不保存，因为深度的会对齐到彩色
            self.color_intrinsics = color_profile.as_video_stream_profile().get_intrinsic()
            self.color_distortion = color_profile.as_video_stream_profile().get_distortion()

            # 配置并启动Pipeline
            config.enable_stream(color_profile)
            config.enable_stream(depth_profile)
            config.set_align_mode(OBAlignMode.HW_MODE) # 硬件对齐模式
            self.pipeline.start(config)
            
            print("[CameraThread] Camera initialized successfully in Hardware D2C Align Mode.")
            print("[CameraThread] Camera initialized successfully.")
            print("[CameraThread] Device information:", Context().query_devices().get_device_by_index(0).get_device_info())
            print("[CameraThread] Color Intrinsics:", self.color_intrinsics)
            print("[CameraThread] Color Distortion:", self.color_distortion)
            return True
            
        except Exception as e:
            print(f"[CameraThread] ERROR during robust initialization: {e}")
            # 在异常情况下打印堆栈跟踪以获取更多信息
            import traceback
            traceback.print_exc()
            return False

    def run(self):
        """
        线程主循环。将以最大可能的速度获取和处理帧。
        """
        # 如果初始化失败，则此线程不执行任何操作
        if not self.initialization_successful:
            return

        while not self.stop_event.is_set():
            try:
                frames = self.pipeline.wait_for_frames(1000) # 等待1秒超时
                if frames is None:
                    continue

                color_frame = frames.get_color_frame()
                depth_frame = frames.get_depth_frame() # 深度帧是硬件对齐过的

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
                depth_data_meters = depth_data_mm / 1000.0  # 转换为米
                # 将最新数据安全地放入共享状态
                self.shared_state.update_frames(color_image, depth_data_meters)
                
            except Exception as e:
                print(f"[CameraThread] ERROR in run loop: {e}")
                time.sleep(1) # 如果发生错误，等待一秒再重试

    def stop(self):
        """
        向线程发送停止信号并清理资源。
        """
        print("[CameraThread] Stop signal received.")
        self.stop_event.set()
        
    def join(self, timeout=None):
        """
        确保在等待线程结束前先停止管线。
        """
        if self.pipeline and self.initialization_successful:
            self.pipeline.stop()
            print("[CameraThread] Pipeline stopped.")
        super().join(timeout)

    def get_camera_intrinsics(self):
        """
        安全地返回在初始化时获取的RGB相机内参和畸变。
        """
        if not self.initialization_successful:
            return None, None
            
        K = np.array([
            [self.color_intrinsics.fx, 0, self.color_intrinsics.cx],
            [0, self.color_intrinsics.fy, self.color_intrinsics.cy],
            [0, 0, 1]
        ])
        # 返回OpenCV期望的5元素的畸变向量
        dist = np.array([
            self.color_distortion.k1,
            self.color_distortion.k2,
            self.color_distortion.p1,
            self.color_distortion.p2,
            self.color_distortion.k3
        ])
        return K, dist