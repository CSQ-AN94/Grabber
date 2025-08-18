#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
相机硬件处理模块

封装了相机线程的启动、拍照、保存和关闭逻辑。
"""

import os
import time
import numpy as np
import cv2
from datetime import datetime

from sensors.camera_thread import CameraThread

class Camera:
    """一个封装了相机功能的类"""
    def __init__(self):
        self.cam_thread = None
        self.is_initialized = False

    def initialize(self):
        """初始化相机线程并启动"""
        print("--- 正在初始化相机... ---")
        self.cam_thread = CameraThread()

        if not self.cam_thread.initialization_successful:
            print("--- ❌ 错误: 相机初始化失败。请检查相机连接。 ---")
            self.is_initialized = False
            return False

        self.cam_thread.start()
        print("--- 相机线程已启动，等待图像稳定... ---")
        time.sleep(1) # 等待1秒以确保图像稳定
        self.is_initialized = True
        return True

    def capture_and_save_images(self, save_dir):
        """拍照、保存彩色和深度图，并返回文件路径"""
        if not self.is_initialized:
            print("--- 错误: 相机未初始化，无法拍照。 ---")
            return None, None

        print("\n--- 准备拍照... ---")
        try:
            os.makedirs(save_dir, exist_ok=True)
        except OSError as e:
            print(f"--- 错误: 无法创建保存目录 '{save_dir}': {e} ---")
            return None, None

        color_image, depth_map_meters = self.cam_thread.get_latest_frames()

        if color_image is None or depth_map_meters is None:
            print("--- 错误: 未能从相机捕获到有效的图像。 ---")
            return None, None

        # 使用时间戳生成唯一文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        color_filename = os.path.join(save_dir, f"{timestamp}_color.png")
        depth_filename = os.path.join(save_dir, f"{timestamp}_depth.png")

        try:
            # 保存彩色图
            cv2.imwrite(color_filename, color_image)
            print(f"--- 彩色图像已保存至: {color_filename} ---")

            # 将深度图从米(float)转换为毫米(uint16)并保存
            depth_map_mm_uint16 = (depth_map_meters * 1000).astype(np.uint16)
            cv2.imwrite(depth_filename, depth_map_mm_uint16)
            print(f"--- 深度图像已保存至: {depth_filename} ---")

            return color_filename, depth_filename
        except Exception as e:
            print(f"--- 保存文件时发生错误: {e} ---")
            return None, None

    def shutdown(self):
        """停止相机线程"""
        if self.is_initialized and self.cam_thread:
            print("--- 正在停止相机线程... ---")
            self.cam_thread.stop()
            self.cam_thread.join(timeout=2)
            self.is_initialized = False
            print("--- 相机线程已停止。 ---")
