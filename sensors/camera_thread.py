import threading
import time
import numpy as np
import cv2
from pyorbbecsdk import *
from external.pyorbbecsdk.examples.utils import frame_to_bgr_image

class CameraThread(threading.Thread):
    def __init__(self, shared_state, camera_config):
        super().__init__()
        self.shared_state = shared_state
        self.is_running = True
        self.camera_config = camera_config

        # 摄像头初始化
        self.config = Config()
        self.pipeline = Pipeline()
        if self.camera_config.enable_color:
            color_profile_list = self.pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
            color_profile = color_profile_list.get_default_video_stream_profile()
            self.config.enable_stream(color_profile)
        if self.camera_config.enable_depth:
            depth_profile_list = self.pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
            depth_profile = depth_profile_list.get_default_video_stream_profile()
            self.config.enable_stream(depth_profile)
        self.pipeline.start(self.config)
        print("相机线程已启动")
        print("设备信息:", Context().query_devices().get_device_by_index(0).get_device_info())
        print("RGB内参:", color_profile.as_video_stream_profile().get_intrinsic())
        print("深度内参:", depth_profile.as_video_stream_profile().get_intrinsic())
        print("深度到RGB转换矩阵", depth_profile.get_extrinsic_to(color_profile))
        print("RGB畸变:", color_profile.get_distortion())
        print("深度畸变:", depth_profile.get_distortion())

    def run(self):
        while self.is_running:
            frames = self.pipeline.wait_for_frames(self.camera_config.frame_timeout_ms)
            if frames is None:
                time.sleep(self.camera_config.sleep_interval)
                continue
            color_frame = frames.get_color_frame() if self.camera_config.enable_color else None
            depth_frame = frames.get_depth_frame() if self.camera_config.enable_depth else None
            if (self.camera_config.enable_color and color_frame is None) or (self.camera_config.enable_depth and depth_frame is None):
                time.sleep(self.camera_config.sleep_interval)
                continue
            color_image = frame_to_bgr_image(color_frame) if color_frame is not None else None
            try:
                depth_data = None
                if depth_frame is not None:
                    depth_data = np.frombuffer(depth_frame.get_data(), dtype=np.uint16)
                    depth_data = depth_data.reshape(depth_frame.get_height(), depth_frame.get_width())
            except Exception:
                depth_data = None
            self.shared_state.update_frames(color_image, depth_data)
            time.sleep(self.camera_config.sleep_interval)

    def stop(self):
        self.is_running = False
        if self.pipeline:
            self.pipeline.stop()

    def get_camera_intrinsics(self):
        """
        返回RGB相机的内参矩阵和畸变系数。
        """
        try:
            K = np.array([
                [self.color_intrinstic.fx, 0, self.color_intrinstic.cx],
                [0, self.color_intrinstic.fy, self.color_intrinstic.cy],
                [0, 0, 1]
            ])
            # pyorbbecsdk的distortion字段可能不存在，若无则返回全零
            if hasattr(self.color_intrinstic, 'distortion'):
                dist = np.array(self.color_intrinstic.distortion[:5])
            else:
                dist = np.zeros(5)
            return K, dist
        except Exception:
            # 占位返回
            return np.eye(3), np.zeros(5)