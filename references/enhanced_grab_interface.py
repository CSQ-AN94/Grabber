#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
抓取接口实现

特性：
- 使用robot_tools.py中的统一硬件实例
- 采用双阶段扫描策略
- 实现智能目标匹配算法
- 执行完整抓取序列
"""

import numpy as np
import time
import math
from typing import Dict, Any, Optional, List
import cv2
from scipy.spatial.transform import Rotation

# 全局放置计数器（模拟reference中的placement_counter）
_placement_counter = 0

def get_next_placement_index():
    """获取下一个放置位置索引并递增计数器"""
    global _placement_counter
    index = _placement_counter % 3  # 循环使用3个放置点
    _placement_counter += 1
    return index


def matrix_to_pose6d(matrix):
    """Convert a 4x4 pose matrix to [x, y, z, roll, pitch, yaw]."""
    rotation = Rotation.from_matrix(matrix[:3, :3])
    roll, pitch, yaw = rotation.as_euler("xyz", degrees=False)
    x, y, z = matrix[:3, 3]
    return [float(x), float(y), float(z), float(roll), float(pitch), float(yaw)]


def _build_pose_row(z: float, roll: float, pitch: float, yaw: float) -> np.ndarray:
    """Build a provisional shelf pose row until the dual-arm shelf is recalibrated."""
    xs = np.linspace(-0.15, 0.19, 35)
    return np.asarray([[float(x), 0.30, z, roll, pitch, yaw] for x in xs], dtype=float)


# Temporary pose rows for direct mode. These are intentionally simple because
# config.yaml still marks all dual-arm shelf/dropoff poses as calibration TODOs.
ROW1_POSES = _build_pose_row(0.61, 0.20, 1.30, 1.55)
ROW2_POSES = _build_pose_row(0.40, 2.85, 1.40, -1.75)


def pick_nearest_pose_lex(target_pose6d, yolopose=None, image_match=False):
    """
    Select a shelf pose without importing the legacy main_workflow module.

    If image_match is enabled, choose row by image y and x by a simple calibrated
    pixel-to-shelf-x mapping. Otherwise choose row by target z and pose by x.
    """
    row1_mat = ROW1_POSES
    row2_mat = ROW2_POSES

    if image_match and yolopose is not None:
        yolo_x = (yolopose[0] + yolopose[2]) / 2
        yolo_y = (yolopose[1] + yolopose[3]) / 2
        shelf_x = 0.0009812949 * yolo_x - 0.30355394
        selected = row1_mat if 0 < yolo_y < 210 else row2_mat
        idx = int(np.argmin(np.abs(selected[:, 0] - shelf_x)))
        best_vec = selected[idx]
        print(f"位姿库选择: image row={'ROW1' if selected is row1_mat else 'ROW2'}, x={shelf_x:.3f}, idx={idx}")
        return [float(v) for v in best_vec.tolist()], 0

    if not target_pose6d or len(target_pose6d) < 3:
        return None, None

    tx, ty, tz = float(target_pose6d[0]), float(target_pose6d[1]), float(target_pose6d[2])
    zdiff_row1 = float(np.min(np.abs(row1_mat[:, 2] - tz)))
    zdiff_row2 = float(np.min(np.abs(row2_mat[:, 2] - tz)))
    selected = row1_mat if zdiff_row1 <= zdiff_row2 else row2_mat
    selected_row_name = "ROW1" if selected is row1_mat else "ROW2"
    idx = int(np.argmin(np.abs(selected[:, 0] - tx)))
    best_vec = selected[idx]
    bx, by, bz = float(best_vec[0]), float(best_vec[1]), float(best_vec[2])
    diffs = (bz - tz, bx - tx, by - ty)
    print(
        f"位姿库选择: {selected_row_name}, idx={idx}, "
        f"delta_z={diffs[0]:+.3f}, delta_x={diffs[1]:+.3f}, delta_y={diffs[2]:+.3f}"
    )
    return [float(v) for v in best_vec.tolist()], diffs


def execute_grab_with_hardware(item_name: str, 
                              vision_analyzer, camera_thread, arm_controller) -> Dict[str, Any]:
    """
    抓取执行函数 - 使用统一硬件组件实现reference算法逻辑
    
    Args:
        item_name: 要抓取的商品名称，英文
        vision_analyzer: 视觉分析器实例
        camera_thread: 相机线程实例
        arm_controller: 机械臂控制器实例
    
    Returns:
        dict: 抓取结果
    """
    print(f"======= 增强抓取开始: {item_name} =======")
    
    try:
        # === 第1步：粗定位扫描（使用统一相机系统）===
        print("--- 第1步：粗定位扫描 ---")
        coarse_targets = scan_with_camera(vision_analyzer, camera_thread)
        if not coarse_targets:
            return {"success": False, "message": "粗定位扫描未检测到任何物体", "item_name": item_name}
        
        # === 第2步：智能目标选择（reference算法）===
        print("--- 第2步：智能目标选择 ---")
        selected_target = smart_target_selection(item_name, coarse_targets)
        if not selected_target:
            available_items = [t['name'] for t in coarse_targets]
            return {"success": False, "message": f"未找到目标 '{item_name}'，可用: {available_items}", "item_name": item_name}
        
        # === 第3步：基座旋转对准（使用统一硬件 + reference算法）===
        print("--- 第3步：基座旋转对准 ---")
        touch_pose, pre_grasp_pose = calculate_grasp_poses(selected_target, arm_controller)
        final_touch_pose, diff = pick_nearest_pose_lex(touch_pose, selected_target['box'], True)
        if not final_touch_pose:
            return {"success": False, "message": "抓取位姿计算失败", "item_name": item_name}
        
        success = orient_base_to_target(final_touch_pose[:3], arm_controller)
        if not success:
            return {"success": False, "message": "基座旋转失败", "item_name": item_name}
        
        # # === 第4步：精定位扫描（reference策略）===
        # print("--- 第4步：精定位扫描 ---")
        # fine_targets = scan_with_camera(vision_analyzer, camera_thread)
        # if not fine_targets:
        #     return {"success": False, "message": "精定位扫描失败", "item_name": item_name}
        
        # # 选择最接近中心的目标
        # final_target = find_center_most_target(fine_targets, 640, 480)  # 640x480分辨率
        # if not final_target:
        #     return {"success": False, "message": "精定位无法确定目标", "item_name": item_name}
        
        # === 第5步：执行抓取序列（使用统一硬件）===
        print("--- 第5步：执行抓取序列 ---")
        # final_touch_pose, final_pre_grasp_pose = calculate_grasp_poses(final_target, arm_controller)
        if not final_touch_pose:
            return {"success": False, "message": "最终位姿计算失败", "item_name": item_name}
        
        success = execute_grasp(final_touch_pose, arm_controller)
        if not success:
            return {"success": False, "message": "抓取序列执行失败", "item_name": item_name}
        
        # === 第6步：完整放置序列（reference实现）===
        print("--- 第6步：完整放置序列 ---")
        
        # 6.1 返回HOME位置
        print("6.1 返回HOME位置")
        success = go_to_home_position(arm_controller)
        if not success:
            print("警告: 返回HOME位置失败，但抓取已完成")
        
        # 6.2 放置物体到指定位置（循环使用放置点）
        placement_index = get_next_placement_index()
        print(f"6.2 放置物体到位置 {placement_index + 1}")
        success = place_object_at_position(arm_controller, placement_index=placement_index)
        if not success:
            print("警告: 物体放置失败，但抓取已完成")
        
        # 6.3 最终返回HOME位置
        print("6.3 最终返回HOME位置")
        go_to_home_position(arm_controller)
        
        # 获取放置点坐标
        # !! 占位值：需在双臂机器人实际场景中标定后填入 !!
        placement_poses = [
            [0.4, 0.2, 0.3, 0.0, 1.571, 0.0],
            [0.4, 0.0, 0.3, 0.0, 1.571, 0.0],
            [0.4, -0.2, 0.3, 0.0, 1.571, 0.0],
        ]
        placement_position = placement_poses[placement_index][:3]
        
        return {
            "success": True,
            "message": f"成功抓取并放置商品 '{item_name}' 到位置 {placement_index + 1}",
            "item_name": item_name,
            "placement_index": placement_index,
            "placement_position": placement_position
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"抓取过程异常: {str(e)}",
            "error": str(e),
            "item_name": item_name
        }


def scan_with_camera(vision_analyzer, camera_thread) -> List[Dict]:
    """使用统一相机系统进行扫描"""
    try:
        # 获取最新帧
        color_frame, depth_frame = camera_thread.get_latest_frames()
        if color_frame is None or depth_frame is None:
            print("无法获取相机帧")
            return []
        
        # 使用视觉分析器
        detections = vision_analyzer.analyze_image(cv2.cvtColor(color_frame, cv2.COLOR_BGR2RGB), depth_frame)
        
        # 转换为标准格式
        targets = []
        for det in detections:
            if 'center_depth_m' in det and det['center_depth_m'] > 0:
                # 计算3D坐标（使用reference坐标系约定）
                bbox = det['box']
                center_x = (bbox[0] + bbox[2]) / 2
                center_y = (bbox[1] + bbox[3]) / 2
                depth = det['center_depth_m']
                
                # 从 camera_thread 获取运行时内参（RealSense 相机）
                K, _ = camera_thread.get_camera_intrinsics()
                if K is None:
                    continue
                fx, fy = K[0, 0], K[1, 1]
                cx_intr, cy_intr = K[0, 2], K[1, 2]
                Z = depth
                X = (center_x - cx_intr) * Z / fx
                Y = (center_y - cy_intr) * Z / fy
                coords_3d = [Y, -X, Z]  # reference坐标系约定
                
                targets.append({
                    'name': det['name'],
                    'confidence': det['confidence'],
                    'coords_3d': coords_3d,
                    'box': det['box']
                })
        
        print(f"扫描到 {len(targets)} 个目标: {[t['name'] for t in targets]}")
        return targets
        
    except Exception as e:
        print(f"相机扫描失败: {e}")
        return []


def smart_target_selection(item_name: str, targets: List[Dict]) -> Optional[Dict]:
    for target in targets:
        if target.get('name') == item_name:
            return target
    return None


def calculate_grasp_poses(target: Dict, arm_controller) -> tuple:
    """使用reference位姿计算算法（calibration参数保持接口一致性）"""
    try:
        coords_3d = target.get('coords_3d', target.get('center_3d_base'))
        if not coords_3d:
            return None, None
        
        # 使用reference算法逻辑
        yolo_Y, yolo_neg_X, yolo_Z = coords_3d
        cam_x, cam_y, cam_z = yolo_Y, yolo_neg_X, yolo_Z
        
        # 手眼标定矩阵（T_tool0_to_camera）
        # !! 占位值：更换为 RealSense 头部相机后必须重新标定 !!
        HAND_EYE_T_tool0_cam = np.array([
            [ 1.0,  0.0,  0.0, -0.05],
            [ 0.0,  1.0,  0.0,  0.00],
            [ 0.0,  0.0,  1.0, -0.08],
            [ 0.0,  0.0,  0.0,  1.0 ]
        ])
        
        T_cam_grasp = np.identity(4)
        T_cam_grasp[:3, 3] = [cam_x, cam_y, cam_z]
        
        # 获取当前位姿
        current_pose_matrix = arm_controller.get_base_to_end_pose_matrix()
        if current_pose_matrix is None:
            return None, None
        
        T_base_touch_target = current_pose_matrix @ HAND_EYE_T_tool0_cam @ T_cam_grasp
        
        # 计算预抓取位置
        PRE_GRASP_OFFSET_METERS = 0.2
        final_rotation_mat = T_base_touch_target[:3, :3]
        z_axis_vector = final_rotation_mat[:, 2]
        final_position = T_base_touch_target[:3, 3]
        pre_grasp_position = final_position - z_axis_vector * PRE_GRASP_OFFSET_METERS
        
        T_base_pre_grasp_target = np.identity(4)
        T_base_pre_grasp_target[:3, :3] = final_rotation_mat
        T_base_pre_grasp_target[:3, 3] = pre_grasp_position
        
        # 转换为6D位姿格式
        touch_pose_6d = matrix_to_pose6d(T_base_touch_target)
        pre_grasp_pose_6d = matrix_to_pose6d(T_base_pre_grasp_target)
        
        print(f"位姿计算完成: 抓取位姿 {np.round(touch_pose_6d, 3)}")
        return touch_pose_6d, pre_grasp_pose_6d
        
    except Exception as e:
        print(f"位姿计算失败: {e}")
        return None, None


def orient_base_to_target(world_coords_xyz, arm_controller) -> bool:
    """基座旋转对准目标"""
    try:
        target_x, target_y, _ = world_coords_xyz
        print(f"基座旋转对准坐标: ({target_x:.3f}, {target_y:.3f})")
        
        # 计算目标角度
        target_angle_rad = math.atan2(target_y, target_x)
        target_angle_deg = math.degrees(target_angle_rad)
        target_angle_deg = target_angle_deg + 180 # 加180
        
        if target_angle_deg > 180: 
            target_angle_deg -= 360
        elif target_angle_deg < -180: 
            target_angle_deg += 360
        
        # 获取当前关节角度
        current_joints_rad = arm_controller.get_current_joint_angles()
        if current_joints_rad is None:
            return False
        
        current_joints_deg = [math.degrees(j) for j in current_joints_rad]
        target_joints_deg = current_joints_deg.copy()
        target_joints_deg[0] = target_angle_deg
        
        print(f"基座旋转: {current_joints_deg[0]:.1f}° -> {target_angle_deg:.1f}°")
        
        # 执行旋转
        result = arm_controller.move_to_joints(target_joints_deg, speed=30, wait=True)
        return result == 0
        
    except Exception as e:
        print(f"基座旋转失败: {e}")
        return False


def execute_grasp(touch_pose, arm_controller) -> bool:
    """执行抓取序列"""
    try:
        print("开始抓取序列...")
        
        # 1. 打开夹爪
        print("1. 打开夹爪")
        if arm_controller.set_gripper_openness(1.0) != 0:
            return False
        
        # 2. 移动到预抓取位置
        print("2. 移动到预抓取位置")
        if arm_controller.movej_to_cartesian_pose(touch_pose, speed=40, wait=True) != 0:
            return False
        
        # 4. 夹取物体
        print("4. 夹取物体")
        if arm_controller.set_gripper_openness(0.1) != 0:
            return False
        time.sleep(1)  # 确保夹取稳定
        
        print("抓取序列完成")
        return True
        
    except Exception as e:
        print(f"抓取序列执行失败: {e}")
        return False


def go_to_home_position(arm_controller) -> bool:
    """返回HOME位置（参考reference实现）"""
    try:
        # HOME 位姿（笛卡尔，[x,y,z,rx,ry,rz]，单位 m/rad）
        # !! 占位值：需在双臂机器人上实测后填入 !!
        home_pose = [0.3, 0.0, 0.5, 0.0, 1.571, 0.0]
        
        print("--- 正在返回HOME位置 ---")
        result = arm_controller.movej_to_cartesian_pose(home_pose, speed=50, wait=True)
        if result == 0:
            print("--- HOME位置到达成功 ---")
            return True
        else:
            print(f"--- HOME位置移动失败，错误码: {result} ---")
            return False
        
    except Exception as e:
        print(f"返回HOME失败: {e}")
        return False


def place_object_at_position(arm_controller, placement_index: int = 0) -> bool:
    """
    放置物体到指定位置（完全参考reference实现）
    
    Args:
        arm_controller: 机械臂控制器
        placement_index: 放置位置索引 (0, 1, 2)
    
    Returns:
        bool: 放置是否成功
    """
    try:
        # 放置点位姿（笛卡尔，[x,y,z,rx,ry,rz]，单位 m/rad）
        # !! 占位值：需在双臂机器人实际场景中标定购物车位置后填入 !!
        placement_poses = [
            [0.4, 0.2, 0.3, 0.0, 1.571, 0.0],   # 放置点1
            [0.4, 0.0, 0.3, 0.0, 1.571, 0.0],   # 放置点2
            [0.4, -0.2, 0.3, 0.0, 1.571, 0.0],  # 放置点3
        ]
        
        actual_index = placement_index % len(placement_poses)
        place_pose = placement_poses[actual_index]
        
        print(f"--- 准备移动到放置点 {actual_index + 1} ---")
        result = arm_controller.movej_to_cartesian_pose(place_pose, speed=30, wait=True)
        if result != 0:
            print(f"移动到放置点失败，错误码: {result}")
            return False
            
        time.sleep(1)  # 稳定等待
        
        print("--- 已到达放置点，释放物体 ---")
        result = arm_controller.set_gripper_openness(1.0)  # 完全打开夹爪
        if result != 0:
            print(f"打开夹爪失败，错误码: {result}")
            return False
            
        time.sleep(1)  # 等待物体掉落
        print(f"--- 在放置点 {actual_index + 1} 放置完毕 ---")
        return True
        
    except Exception as e:
        print(f"放置物体失败: {e}")
        return False
