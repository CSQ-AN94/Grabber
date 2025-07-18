#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
图像采集脚本
用于采集相机图像数据，用于YOLOv8模型微调
"""

import os
import sys
import time
import cv2
import numpy as np
from datetime import datetime
import argparse

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.config import load_config
from utils.state import WorldState
from sensors.camera_thread import CameraThread


class ImageCollector:
    """
    图像采集器
    可视化相机画面并定期保存图像用于YOLOv8训练
    """
    
    def __init__(self, save_interval=5, output_dir="intelligence/data"):
        """
        初始化图像采集器
        
        Args:
            save_interval: 图像保存间隔（秒）
            output_dir: 图像保存目录
        """
        self.save_interval = save_interval
        self.output_dir = output_dir
        self.image_count = 0
        
        # 创建输出目录
        os.makedirs(self.output_dir, exist_ok=True)
        
        # 初始化组件
        self.world_state = WorldState()
        self.camera_thread = None
        
        self._initialize_camera()
        
    def _initialize_camera(self):
        """初始化相机"""
        try:
            print("初始化相机...")
            self.camera_thread = CameraThread(self.world_state, None)
            self.camera_thread.start()
            
            # 等待相机稳定
            print("等待相机稳定...")
            time.sleep(3)
            
            # 验证相机是否正常工作
            color_frame, depth_frame = self.world_state.get_latest_frames()
            if color_frame is None:
                raise RuntimeError("相机初始化失败：无法获取彩色图像")
            
            print(f"相机初始化成功")
            print(f"彩色图像尺寸: {color_frame.shape}")
            if depth_frame is not None:
                print(f"深度图像尺寸: {depth_frame.shape}")
            
        except Exception as e:
            print(f"相机初始化失败: {e}")
            raise
    
    def _save_image(self, image):
        """
        保存图像到文件
        
        Args:
            image: 要保存的图像 (RBG)
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"image_{timestamp}_{self.image_count:04d}.jpg"
        filepath = os.path.join(self.output_dir, filename)
        
        if len(image.shape) == 3 and image.shape[2] == 3:
            success = cv2.imwrite(filepath, image)
            
            if success:
                print(f"图像已保存: {filepath}")
                self.image_count += 1
                return True
            else:
                print(f"图像保存失败: {filepath}")
                return False
        else:
            print(f"图像格式错误: {image.shape}")
            return False
    
    def run(self):
        """
        运行图像采集
        显示实时画面并定期保存图像
        """
        print("开始图像采集...")
        print(f"保存间隔: {self.save_interval}秒")
        print(f"保存目录: {self.output_dir}")
        print("按 'q' 退出，按 's' 手动保存图像")
        print("-" * 50)
        
        last_save_time = time.time()
        
        try:
            while True:
                # 获取最新图像
                color_frame, depth_frame = self.world_state.get_latest_frames()
                
                if color_frame is not None:
                    # 显示RGB图像
                    color_frame = cv2.cvtColor(color_frame, cv2.COLOR_BGR2RGB)
                    display_frame = color_frame.copy()
                    
                    # 添加信息叠加
                    current_time = time.time()
                    time_since_last_save = current_time - last_save_time
                    next_save_in = max(0, self.save_interval - time_since_last_save)
                    
                    # 添加文字信息
                    info_text = f"Images saved: {self.image_count}"
                    time_text = f"Next save in: {next_save_in:.1f}s"
                    
                    cv2.putText(display_frame, info_text, (10, 30), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.putText(display_frame, time_text, (10, 60), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                    cv2.putText(display_frame, "Press 'q' to quit, 's' to save", (10, 90), 
                              cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                    
                    # 显示图像
                    cv2.imshow('Image Collector', display_frame)
                    
                    # 如果有深度图像，也显示出来
                    if depth_frame is not None:
                        # 将深度图归一化到0-255范围用于显示
                        depth_normalized = cv2.normalize(depth_frame, None, 0, 255, cv2.NORM_MINMAX)
                        depth_colored = cv2.applyColorMap(depth_normalized.astype(np.uint8), cv2.COLORMAP_JET)
                        cv2.imshow('Depth Image', depth_colored)
                    
                    # 定期保存图像
                    if current_time - last_save_time >= self.save_interval:
                        self._save_image(color_frame)
                        last_save_time = current_time
                
                # 处理按键
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    print("用户退出")
                    break
                elif key == ord('s'):
                    # 手动保存图像
                    if color_frame is not None:
                        self._save_image(color_frame)
                        last_save_time = time.time()  # 重置计时器
                
                # 避免CPU占用过高
                time.sleep(0.03)  # 约30FPS
                
        except KeyboardInterrupt:
            print("\n用户中断")
        
        finally:
            self._cleanup()
    
    def _cleanup(self):
        """清理资源"""
        print("正在清理资源...")
        
        # 关闭OpenCV窗口
        cv2.destroyAllWindows()
        
        # 停止相机线程
        if self.camera_thread and self.camera_thread.is_alive():
            self.camera_thread.stop()
            self.camera_thread.join(timeout=5)
            if self.camera_thread.is_alive():
                print("警告：相机线程未能正常停止")
            else:
                print("相机线程已停止")
        
        print(f"采集完成，共保存 {self.image_count} 张图像")
        print(f"图像保存在: {os.path.abspath(self.output_dir)}")


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="图像采集脚本")
    parser.add_argument("--interval", type=int, default=0.5, 
                      help="图像保存间隔（秒），默认0.5秒")
    parser.add_argument("--output", type=str, default="intelligence/data",
                      help="图像保存目录，默认intelligence/data")
    parser.add_argument("--config", type=str, default="config.ini",
                      help="配置文件路径，默认config.ini")
    
    args = parser.parse_args()
    
    try:
        # 加载配置
        print("加载配置...")
        config = load_config(args.config)
        
        # 创建图像采集器
        collector = ImageCollector(
            save_interval=args.interval,
            output_dir=args.output
        )
        
        # 运行采集
        collector.run()
        
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()