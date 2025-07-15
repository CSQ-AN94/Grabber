#!/usr/bin/env python3
"""
简单软件D2C对齐测试脚本
用于证明Y轴缺失是硬件对齐问题，而非硬件本身问题
基于SDK配置文档的真实对齐模式: 0=disable, 1=hardware, 2=software
"""

import cv2
import numpy as np
from pyorbbecsdk import *
from external.pyorbbecsdk.examples.utils import frame_to_bgr_image

class AlignmentComparison:
    """对齐模式对比工具"""
    
    def __init__(self):
        self.pipeline = None
        self.color_profile = None
        self.depth_profile = None
        self.current_mode = None
        
    def initialize_no_align(self):
        """初始化：不使用对齐（原始流）"""
        try:
            self.pipeline = Pipeline()
            config = Config()
            
            # 获取彩色相机Profile (640x480 BGR)
            color_profiles = self.pipeline.get_stream_profile_list(OBSensorType.COLOR_SENSOR)
            self.color_profile = None
            for i in range(len(color_profiles)):
                profile = color_profiles[i]
                video_profile = profile.as_video_stream_profile()
                if (video_profile.get_width() == 640 and 
                    video_profile.get_height() == 480 and
                    video_profile.get_format() == OBFormat.BGR):
                    self.color_profile = profile
                    break
            
            if self.color_profile is None:
                print("错误: 未找到640x480 BGR彩色Profile")
                return False
            
            # 获取深度相机Profile (选择最大分辨率)
            depth_profiles = self.pipeline.get_stream_profile_list(OBSensorType.DEPTH_SENSOR)
            self.depth_profile = None
            max_resolution = 0
            
            for i in range(len(depth_profiles)):
                profile = depth_profiles[i]
                video_profile = profile.as_video_stream_profile()
                resolution = video_profile.get_width() * video_profile.get_height()
                if resolution > max_resolution:
                    max_resolution = resolution
                    self.depth_profile = profile
            
            if self.depth_profile is None:
                print("错误: 未找到深度Profile")
                return False
            
            # 配置流 - 关键：不设置对齐模式 (AlignMode=0)
            config.enable_stream(self.color_profile)
            config.enable_stream(self.depth_profile)
            # 不调用 config.set_align_mode()，默认为0 (disable)
            
            # 启动Pipeline
            self.pipeline.start(config)
            self.current_mode = "NO_ALIGN"
            
            color_video = self.color_profile.as_video_stream_profile()
            depth_video = self.depth_profile.as_video_stream_profile()
            
            print(f"无对齐模式初始化成功")
            print(f"彩色流: {color_video.get_width()}x{color_video.get_height()}")
            print(f"深度流: {depth_video.get_width()}x{depth_video.get_height()}")
            
            return True
            
        except Exception as e:
            print(f"无对齐模式初始化失败: {e}")
            return False
    
    def initialize_hw_align(self):
        """初始化：硬件对齐模式"""
        try:
            self.pipeline = Pipeline()
            config = Config()
            
            # 使用相同的Profile
            if self.color_profile is None or self.depth_profile is None:
                print("错误: Profile未设置")
                return False
            
            # 获取硬件对齐的深度Profile
            hw_d2c_profiles = self.pipeline.get_d2c_depth_profile_list(self.color_profile, OBAlignMode.HW_MODE)
            if not hw_d2c_profiles or len(hw_d2c_profiles) == 0:
                print("错误: 没有硬件对齐的深度Profile")
                return False
            
            hw_depth_profile = hw_d2c_profiles[0]
            
            # 配置流 - 使用硬件对齐 (AlignMode=1)
            config.enable_stream(self.color_profile)
            config.enable_stream(hw_depth_profile)
            config.set_align_mode(OBAlignMode.HW_MODE)
            
            # 启动Pipeline
            self.pipeline.start(config)
            self.current_mode = "HW_ALIGN"
            
            hw_depth_video = hw_depth_profile.as_video_stream_profile()
            print(f"硬件对齐模式初始化成功")
            print(f"硬件对齐深度流: {hw_depth_video.get_width()}x{hw_depth_video.get_height()}")
            
            return True
            
        except Exception as e:
            print(f"硬件对齐模式初始化失败: {e}")
            return False
    
    def initialize_sw_align(self):
        """初始化：软件对齐模式"""
        try:
            self.pipeline = Pipeline()
            config = Config()
            
            # 使用相同的Profile
            if self.color_profile is None or self.depth_profile is None:
                print("错误: Profile未设置")
                return False
            
            # 获取软件对齐的深度Profile
            sw_d2c_profiles = self.pipeline.get_d2c_depth_profile_list(self.color_profile, OBAlignMode.SW_MODE)
            if not sw_d2c_profiles or len(sw_d2c_profiles) == 0:
                print("错误: 没有软件对齐的深度Profile")
                return False
            
            sw_depth_profile = sw_d2c_profiles[0]
            
            # 配置流 - 使用软件对齐 (AlignMode=2)
            config.enable_stream(self.color_profile)
            config.enable_stream(sw_depth_profile)
            config.set_align_mode(OBAlignMode.SW_MODE)
            
            # 启动Pipeline
            self.pipeline.start(config)
            self.current_mode = "SW_ALIGN"
            
            sw_depth_video = sw_depth_profile.as_video_stream_profile()
            print(f"软件对齐模式初始化成功")
            print(f"软件对齐深度流: {sw_depth_video.get_width()}x{sw_depth_video.get_height()}")
            
            return True
            
        except Exception as e:
            print(f"软件对齐模式初始化失败: {e}")
            return False
    
    def cleanup(self):
        """清理资源"""
        if self.pipeline:
            self.pipeline.stop()
            self.pipeline = None
    
    def run_alignment_comparison(self):
        """运行三种对齐模式的对比测试"""
        print("\n开始对齐模式对比测试...")
        print("将依次展示:")
        print("  1. 无对齐模式 (原始流)")
        print("  2. 硬件对齐模式 (当前使用)")
        print("  3. 软件对齐模式 (SDK内置)")
        print("按 'n' 切换到下一个模式，'q' 或 ESC 退出")
        
        modes = [
            ("NO_ALIGN", "无对齐 (原始流)", self.initialize_no_align),
            ("HW_ALIGN", "硬件对齐", self.initialize_hw_align),
            ("SW_ALIGN", "软件对齐", self.initialize_sw_align)
        ]
        
        current_mode_index = 0
        
        # 初始化第一个模式
        if not modes[current_mode_index][2]():
            print("初始化失败")
            return
        
        # 创建窗口
        cv2.namedWindow("Alignment Mode Comparison", cv2.WINDOW_NORMAL)
        cv2.resizeWindow("Alignment Mode Comparison", 1280, 480)
        
        frame_count = 0
        
        try:
            while True:
                # 获取帧
                frames = self.pipeline.wait_for_frames(100)
                if frames is None:
                    continue
                
                color_frame = frames.get_color_frame()
                depth_frame = frames.get_depth_frame()
                
                if color_frame is None or depth_frame is None:
                    continue
                
                frame_count += 1
                
                # 转换彩色图
                color_image = frame_to_bgr_image(color_frame)
                if color_image is None:
                    continue
                
                # 获取深度图
                try:
                    depth_data = np.frombuffer(depth_frame.get_data(), dtype=np.uint16).reshape(
                        depth_frame.get_height(), depth_frame.get_width()
                    )
                except ValueError:
                    print("深度数据reshape失败")
                    continue
                
                # 深度数据处理
                depth_scale = depth_frame.get_depth_scale()
                depth_meters = depth_data.astype(np.float32) * depth_scale
                
                # 可视化处理
                color_vis = cv2.resize(color_image, (640, 480))
                
                # 深度图可视化
                depth_vis = cv2.normalize(depth_meters, None, 0, 255, cv2.NORM_MINMAX)
                depth_vis = cv2.applyColorMap(depth_vis.astype(np.uint8), cv2.COLORMAP_JET)
                depth_vis = cv2.resize(depth_vis, (640, 480))
                
                # 组合显示
                combined = np.hstack([color_vis, depth_vis])
                
                # 添加模式信息
                mode_name = modes[current_mode_index][1]
                cv2.putText(combined, f"Mode: {mode_name}", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)
                cv2.putText(combined, "Color", (10, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                cv2.putText(combined, "Depth", (650, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)
                
                # 显示统计信息
                valid_depth = np.sum(depth_data > 0)
                total_pixels = depth_data.shape[0] * depth_data.shape[1]
                coverage = valid_depth / total_pixels
                
                cv2.putText(combined, f"Frame: {frame_count}", (10, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(combined, f"Color: {color_image.shape[1]}x{color_image.shape[0]}", (10, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(combined, f"Depth: {depth_data.shape[1]}x{depth_data.shape[0]}", (10, 130), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(combined, f"Coverage: {coverage:.1%}", (10, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                
                # 显示控制提示
                cv2.putText(combined, "Press 'n' for next mode, 'q' to quit", (10, 470), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 1)
                
                cv2.imshow("Alignment Mode Comparison", combined)
                
                # 键盘控制
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q') or key == 27:  # 'q' 或 ESC
                    break
                elif key == ord('n'):  # 'n' 切换到下一个模式
                    self.cleanup()
                    current_mode_index = (current_mode_index + 1) % len(modes)
                    print(f"\n切换到: {modes[current_mode_index][1]}")
                    if not modes[current_mode_index][2]():
                        print("模式切换失败")
                        break
                    frame_count = 0
                elif key == ord('s'):  # 's' 保存截图
                    filename = f"align_comparison_{modes[current_mode_index][0]}_frame_{frame_count}.jpg"
                    cv2.imwrite(filename, combined)
                    print(f"截图已保存: {filename}")
                
        except KeyboardInterrupt:
            print("\n用户中断")
        
        finally:
            # 清理资源
            cv2.destroyAllWindows()
            self.cleanup()
            print("对齐模式对比测试完成")

def main():
    """主函数"""
    print("对齐模式对比测试")
    print("=" * 50)
    print("目的: 证明Y轴覆盖率低是硬件对齐问题，而非硬件本身问题")
    print("基于OrbbecSDKConfig.xml: 0=disable, 1=hardware, 2=software")
    print()
    
    # 创建对齐对比对象
    comparison = AlignmentComparison()
    
    # 运行对比测试
    comparison.run_alignment_comparison()

if __name__ == "__main__":
    main()