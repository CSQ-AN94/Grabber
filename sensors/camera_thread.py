import threading
import time
import numpy as np
import cv2
from pyorbbecsdk import *
from external.pyorbbecsdk.examples.utils import frame_to_bgr_image

class CameraThread(threading.Thread):
    def __init__(self, shared_state):
        super().__init__()
        self.shared_state = shared_state
        self.is_running = True
        self.pipeline = None
        self.config = None

        # 摄像头初始化
        self.config = Config()
        self.pipeline = Pipeline()
        # 启用彩色流
        color_profile_list = self.pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
        color_profile = color_profile_list.get_default_video_stream_profile()
        self.config.enable_stream(color_profile)
        # 启用深度流
        depth_profile_list = self.pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
        depth_profile = depth_profile_list.get_default_video_stream_profile()
        self.config.enable_stream(depth_profile)
        self.pipeline.start(self.config)

    def run(self):
        while self.is_running:
            frames = self.pipeline.wait_for_frames(100)
            if frames is None:
                time.sleep(0.01)
                continue
            color_frame = frames.get_color_frame()
            depth_frame = frames.get_depth_frame()
            if color_frame is None or depth_frame is None:
                time.sleep(0.01)
                continue
            # 彩色帧转BGR
            color_image = frame_to_bgr_image(color_frame)
            # 深度帧转16位灰度
            try:
                depth_data = np.frombuffer(depth_frame.get_data(), dtype=np.uint16)
                depth_data = depth_data.reshape(depth_frame.get_height(), depth_frame.get_width())
            except Exception:
                depth_data = None
            self.shared_state.update_frames(color_image, depth_data)
            time.sleep(0.01)

    def stop(self):
        self.is_running = False
        if self.pipeline:
            self.pipeline.stop()