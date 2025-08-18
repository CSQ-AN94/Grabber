import numpy as np
import os
import cv2

from intelligence.vision import VisionAnalyzer

# --- 配置 (Configuration) ---
YOLO_MODEL_PATH = os.path.join("intelligence/models/", "8_17.pt")

# --- 相机内参 (Camera Intrinsics) ---
MY_CAMERA_INTRINSICS = {
    "fx": 367.5447998,
    "fy": 367.60284424,
    "cx": 320.26034546,
    "cy": 244.70648193
}
FACTOR_DEPTH = 1000.0

def _calculate_3d_coords(center_x, center_y, depth_image):
    """内部辅助函数，用于计算单个点的3D坐标"""
    if depth_image is None:
        return None

    height, width = depth_image.shape[:2]
    if not (0 <= center_y < height and 0 <= center_x < width):
        return None

    depth_value = depth_image[center_y, center_x]

    # 根据深度图的数据类型转换单位
    if depth_image.dtype == np.uint16:
        center_depth_meters = float(depth_value) / FACTOR_DEPTH
    elif depth_image.dtype in [np.float32, np.float64]:
        center_depth_meters = float(depth_value)
    else:
        return None

    if center_depth_meters <= 0:
        return None

    Z = center_depth_meters
    X = (center_x - MY_CAMERA_INTRINSICS['cx']) * Z / MY_CAMERA_INTRINSICS['fx']
    Y = (center_y - MY_CAMERA_INTRINSICS['cy']) * Z / MY_CAMERA_INTRINSICS['fy']
    
    return [Y, -X, Z]

def get_all_targets(analyzer, color_image, depth_image):
    """
    全自动分析图像，找到所有物体并返回它们的3D坐标列表。
    
    Returns:
        list: 一个字典列表，每个字典包含 name, confidence, 和 coords_3d。
              例如: [{'name': 'Coke', 'confidence': 0.9, 'coords_3d': [0.1, 0.2, 0.5]}]
    """
    if color_image is None:
        print("--- ❌ 错误: 传入了空的彩色图像。 ---")
        return []

    # 调用VisionAnalyzer时传入深度图，这样能直接获得深度信息
    detections = analyzer.analyze_image(color_image, depth_image)
    if not detections:
        return []

    targets = []
    for obj in detections:
        bbox = obj['box']
        center_x = int((bbox[0] + bbox[2]) / 2)
        center_y = int((bbox[1] + bbox[3]) / 2)
        
        coords = _calculate_3d_coords(center_x, center_y, depth_image)
        
        if coords:
            targets.append({
                'name': obj['name'],
                'confidence': obj['confidence'],
                'coords_3d': coords,
                #'box': obj['box']
            })
            
    return targets

def get_single_best_target(analyzer, color_image, depth_image):
    """
    (旧函数) 自动选择置信度最高的物体并返回其3D坐标。
    """
    targets = get_all_targets(analyzer, color_image, depth_image)
    if not targets:
        return None
    
    # 选择置信度最高的物体
    best_target = max(targets, key=lambda t: t['confidence'])
    print(f"--- 自动选择置信度最高的目标: {best_target['name']} (Conf: {best_target['confidence']:.2f}) ---")
    return best_target['coords_3d']

def main_test():
    """
    用于单独测试本模块功能的函数
    """
    print("--- 启动YOLO模块独立测试 ---")
    
    try:
        analyzer = VisionAnalyzer(model_path=YOLO_MODEL_PATH)
    except Exception as e:
        print(f"❌ 错误: 初始化VisionAnalyzer失败: {e}")
        return

    color_img_path = "test_data_YOLO/888_color.png"
    depth_img_path = "test_data_YOLO/888_depth.png"
    
    color_image = cv2.imread(color_img_path)
    depth_image = cv2.imread(depth_img_path, cv2.IMREAD_UNCHANGED)

    if color_image is None or depth_image is None:
        print("❌ 错误: 加载测试图像失败。")
        return

    print("\n--- 测试 get_all_targets 函数 ---")
    all_targets = get_all_targets(analyzer, color_image, depth_image)

    if all_targets:
        print("\n================== 测试成功 ==================")
        print("检测到以下目标:")
        for i, target in enumerate(all_targets):
            print(f"  [{i}] {target['name']} (Conf: {target['confidence']:.2f}) -> Coords: {np.round(target['coords_3d'], 4)}")
        print("============================================\n")
    else:
        print("\n================== 测试失败 ==================\n")

if __name__ == "__main__":
    main_test()
