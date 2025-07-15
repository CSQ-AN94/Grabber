# intelligence/vision.py

import cv2
import numpy as np
from ultralytics import YOLO
import time

# 为了独立测试，我们需要能够模拟或接收来自外部的数据
# 在真实集成时，这些对象将由主程序传入
from utils.state import WorldState
from sensors.camera_thread import CameraThread
from utils.config import load_config

class VisionAnalyzer:
    """
    视觉分析专家。
    负责所有与图像理解相关的任务，主要是YOLOv8的目标检测。
    它被设计为松耦合的，可以处理来自视频流或静态图片的图像。
    """
    def __init__(self, model_path: str = "intelligence/models/yolov8n.pt"):
        """
        初始化视觉分析器。
        
        Args:
            model_path (str): 指向预训练的YOLOv8模型文件 (.pt) 的路径。
        """
        print(f"[Vision] Loading YOLOv8 model from: {model_path}...")
        try:
            self.model = YOLO(model_path)
            # 打印模型信息以确认加载成功
            self.model.info() 
            print("[Vision] YOLOv8 model loaded successfully.")
        except Exception as e:
            print(f"[Vision] CRITICAL: Failed to load YOLOv8 model: {e}")
            # 在实际应用中，这里应该抛出异常或设置一个失败状态
            raise

    # ----------------------------------------------------------------------
    # 目标 1: 实现对单张图片和视频帧的分析
    # ----------------------------------------------------------------------
    def analyze_image(self, image: np.ndarray, depth_map: np.ndarray = None):
        """
        分析单张静态图像，返回检测结果。
        这是所有检测功能的基础。
        
        Args:
            image (np.ndarray): 输入的RGB彩色图像。
            depth_map (np.ndarray, optional): 与彩色图像对齐的、单位为米的深度图。
                                              如果提供了深度图，结果中会包含深度信息。

        Returns:
            list[dict]: 一个包含所有检测到物体的列表。每个物体是一个字典。
                        例如: [{'name': 'bottle', 'confidence': 0.85, 'box': [x1,y1,x2,y2], 'center_depth_m': 0.54}]
        """
        if image is None:
            return []

        # 使用YOLOv8进行推理
        results = self.model(image, verbose=False) # verbose=False可以减少不必要的控制台输出
        
        detected_objects = []
        # 遍历检测结果
        for result in results:
            for box in result.boxes:
                # 获取类别名称
                class_id = int(box.cls[0])
                class_name = self.model.names[class_id]
                
                # 获取置信度
                confidence = float(box.conf[0])
                
                # 获取边界框坐标 (x1, y1, x2, y2)
                x1, y1, x2, y2 = map(int, box.xyxy[0])
                
                # 创建一个字典来存储这个物体的信息
                obj_data = {
                    "name": class_name,
                    "confidence": confidence,
                    "box": [x1, y1, x2, y2]
                }
                
                # ----------------------------------------------------------
                # 目标 2: 结合深度图，获取框中心的深度值
                # ----------------------------------------------------------
                if depth_map is not None:
                    # 计算框的中心点
                    center_x = (x1 + x2) // 2
                    center_y = (y1 + y2) // 2
                    
                    # 确保中心点在图像范围内
                    if 0 <= center_y < depth_map.shape[0] and 0 <= center_x < depth_map.shape[1]:
                        # 从深度图中获取深度值 (单位：米)
                        depth_value = depth_map[center_y, center_x]
                        
                        # 只有当深度值有效时才添加 (大于0)
                        if depth_value > 0:
                            obj_data["center_depth_m"] = round(depth_value, 3) # 保留3位小数

                detected_objects.append(obj_data)
                
        return detected_objects

    # ----------------------------------------------------------------------
    # 辅助函数: 在图像上绘制结果，用于调试
    # ----------------------------------------------------------------------
    @staticmethod
    def draw_detections(image: np.ndarray, detections: list):
        """
        在给定的图像上绘制检测结果。
        这是一个静态方法，因为它不依赖于类的任何状态（如模型）。
        
        Args:
            image (np.ndarray): 要绘制的图像。
            detections (list[dict]): 来自 analyze_image 的检测结果列表。
        
        Returns:
            np.ndarray: 绘制了边界框和标签的图像。
        """
        if not detections:
            return image

        img_with_boxes = image.copy()
        for obj in detections:
            x1, y1, x2, y2 = obj['box']
            name = obj['name']
            confidence = obj['confidence']
            
            # 绘制边界框 (绿色)
            cv2.rectangle(img_with_boxes, (x1, y1), (x2, y2), (0, 255, 0), 2)
            
            # 准备标签文本
            label = f"{name}: {confidence:.2f}"
            if "center_depth_m" in obj:
                label += f" D:{obj['center_depth_m']}m"
                
            # 绘制标签背景
            (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
            cv2.rectangle(img_with_boxes, (x1, y1 - h - 5), (x1 + w, y1), (0, 255, 0), -1)
            
            # 绘制标签文本
            cv2.putText(img_with_boxes, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 2)
            
        return img_with_boxes

# ======================================================================
#  独立的测试入口 (vision.py自己的main方法)
# ======================================================================
if __name__ == '__main__':
    print("--- [Test Vision Module] ---")

    # --- 1. 加载配置和初始化 ---
    try:
        # 假设模型路径在config.ini中定义
        config = load_config('config.ini') # 注意路径，因为我们在intelligence目录下
        model_path = config.vision.model_path # 假设config.py中会解析出vision部分
        analyzer = VisionAnalyzer(model_path=model_path)
    except Exception as e:
        print(f"初始化失败，请检查config.ini和模型文件: {e}")
        # 如果模型加载失败，后续测试无意义，直接退出
        exit()

    # --- 2. 创建测试菜单 ---
    while True:
        print("\nSelect a test mode:")
        print("1. Analyze a single image file")
        print("2. Analyze live video stream from camera")
        print("Q. Quit")
        choice = input("Enter your choice: ").strip().upper()

        # --- 模式一：分析静态图片 ---
        if choice == '1':
            image_path = input("Enter path to image file: ")
            try:
                image = cv2.imread(image_path)
                if image is None:
                    print("Error: Could not read image file.")
                    continue
                
                # 分析图像
                detections = analyzer.analyze_image(image)
                
                # 绘制结果并显示
                image_with_boxes = VisionAnalyzer.draw_detections(image, detections)
                cv2.imshow("Static Image Analysis", image_with_boxes)
                print(f"Found {len(detections)} objects. Press any key to close window.")
                cv2.waitKey(0)
                cv2.destroyWindow("Static Image Analysis")

            except Exception as e:
                print(f"An error occurred during image analysis: {e}")

        # --- 模式二：分析实时视频流 ---
        elif choice == '2':
            print("Starting live video analysis... (Press 'q' in the window to stop)")
            
            # 初始化相机线程和共享状态
            # 这是vision.py与系统其他部分唯一的连接点
            world_state = WorldState()
            camera_thread = CameraThread(world_state, None)
            camera_thread.start()
            
            # 等待相机启动
            time.sleep(3) 
            if world_state.get_latest_frames()[0] is None:
                print("Error: Failed to start camera stream.")
                camera_thread.stop()
                camera_thread.join()
                continue

            try:
                while True:
                    # 从共享状态获取最新的彩色图和深度图
                    color_frame, depth_frame = world_state.get_latest_frames()
                    
                    if color_frame is not None:
                        # 分析当前帧
                        detections = analyzer.analyze_image(color_frame, depth_frame)
                        
                        # 在帧上绘制检测结果
                        frame_with_boxes = VisionAnalyzer.draw_detections(color_frame, detections)
                        
                        # 显示处理后的帧
                        cv2.imshow("Live Video Analysis", frame_with_boxes)

                    # 按 'q' 键退出循环
                    if cv2.waitKey(1) & 0xFF == ord('q'):
                        break
            finally:
                # 确保线程和窗口被正确关闭
                camera_thread.stop()
                camera_thread.join(timeout=2)
                cv2.destroyAllWindows()
                print("Live video analysis stopped.")
        
        elif choice == 'Q':
            break
        
        else:
            print("Invalid choice.")

    print("--- Vision Module Test Finished ---")