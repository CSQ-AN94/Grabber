# intelligence/vision.py - The Brain of Perception

from ultralytics import YOLO
import numpy as np

class VisionAnalyzer:
    def __init__(self, config, calibration_tool):
        self.yolo_model = YOLO(config['yolo_model_path'])
        self.calibration = calibration_tool
        self._raw_detections = []

    def analyze_frame(self, color_frame, depth_frame, arm_joints, rail_pos):
        """
        对单帧进行目标检测与世界坐标转换，返回[{name, world_coords, bbox, conf}, ...]
        """
        results = self.yolo_model(color_frame)
        detections = []
        for res in results:
            for box, cls, conf in zip(res.boxes.xywh, res.boxes.cls, res.boxes.conf):
                center_u, center_v = int(box[0]), int(box[1])
                if (0 <= center_v < depth_frame.shape[0]) and (0 <= center_u < depth_frame.shape[1]):
                    depth_value = depth_frame[center_v, center_u]
                else:
                    depth_value = 0
                # 相机像素坐标(u,v)和深度转为相机系3D点
                camera_point = self.pixel_to_camera(center_u, center_v, depth_value)
                # 转为世界坐标
                world_coords = self.calibration.transform_camera_to_world(camera_point, arm_joints, rail_pos)
                name = res.names[int(cls)] if hasattr(res, 'names') else str(int(cls))
                detections.append({
                    'name': name,
                    'world_coords': world_coords,
                    'bbox': box.tolist(),
                    'conf': float(conf)
                })
        return detections

    def pixel_to_camera(self, u, v, depth):
        # 这里应调用pyorbbecsdk的transformation2dto3d，暂用简单占位
        # 实际项目中应传入相机内参和畸变参数
        return np.array([u * 0.001, v * 0.001, depth * 0.001])

    def start_world_building_scan(self, robot_state, rail_controller):
        """
        持续处理视频流，直到导轨停止。每帧检测并转换世界坐标，结果存入self._raw_detections。
        """
        self._raw_detections = []
        while rail_controller.is_moving():
            color_frame, depth_frame = robot_state.get_latest_frames()
            if color_frame is None or depth_frame is None:
                continue
            arm_joints = robot_state.get_arm_joints()
            rail_pos = rail_controller.get_current_position()
            detections = self.analyze_frame(color_frame, depth_frame, arm_joints, rail_pos)
            self._raw_detections.extend(detections)

    def analyze_static(self, color_frame, depth_frame, arm_joints, rail_pos):
        """
        对单帧静态图片进行检测与世界坐标转换。
        """
        return self.analyze_frame(color_frame, depth_frame, arm_joints, rail_pos)

    def stop_and_process_scan(self):
        """
        对扫描期间收集到的所有点进行聚类和处理，返回最终的世界地图。
        """
        # 伪代码: DBSCAN聚类，取均值
        if not self._raw_detections:
            return {}
        from sklearn.cluster import DBSCAN
        X = np.array([d['world_coords'] for d in self._raw_detections])
        if len(X) == 0:
            return {}
        clustering = DBSCAN(eps=0.05, min_samples=2).fit(X)
        labels = clustering.labels_
        world_map = {}
        for label in set(labels):
            if label == -1:
                continue  # 噪声点
            indices = np.where(labels == label)[0]
            names = [self._raw_detections[i]['name'] for i in indices]
            coords = X[indices]
            # 取出现最多的name
            from collections import Counter
            name = Counter(names).most_common(1)[0][0]
            mean_coord = coords.mean(axis=0)
            world_map[name] = mean_coord.tolist()
        return world_map