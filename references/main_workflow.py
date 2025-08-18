#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进入docker容器代码
docker run -it --rm --privileged -p 8000:8000 -v /home/xjtlu/Documents/Grabber:/app 511068f754f2 bash

主工作流程脚本 (V5 - 二次扫描精定位版)

采用“粗定位->精定位”策略，先转身对准，再进行二次扫描以精确抓取。
本版新增：外部可注入“标签队列”，按标签自动选择抓取对象；未命中时回退人工输入。
本版增强：AUTO_CONFIRM 自动确认所有交互步骤（除第一步是否扫描）。
本版增强：AUTO_FIRST_MODE 环境变量可控制第一步是否扫描（免交互）。
"""

import sys
import os
import cv2
import configparser
import time
import numpy as np
import re

# --- 自动确认总开关（除第一步是否扫描） ---
AUTO_CONFIRM = True

# --- 路径设置 ---
# 修复路径指向正确的项目目录结构
references_dir = os.path.dirname(__file__)  # /path/to/Grabber/references
project_root = os.path.dirname(references_dir)  # /path/to/Grabber

sdk_path = os.path.join(project_root, 'external/RM_API2/Python')
intelligence_path = os.path.join(project_root, 'intelligence')
references_path = os.path.join(project_root, 'references')

sys.path.insert(0, sdk_path)
sys.path.insert(0, intelligence_path)  
sys.path.insert(0, references_path)

# --- 导入模块 ---
from robot_controller import RobotController
from camera_handler import Camera  
from yolo_model import get_all_targets, VisionAnalyzer

# --- 全局配置（修复路径） ---
# 创建临时配置和数据目录
temp_dir = os.path.join(project_root, 'temp_grabber')
os.makedirs(temp_dir, exist_ok=True)
os.makedirs(os.path.join(temp_dir, 'test_data_YOLO'), exist_ok=True)

YOLO_MODEL_PATH = os.path.join(intelligence_path, 'models/8_17.pt') 
CAPTURE_SAVE_DIR = os.path.join(temp_dir, 'test_data_YOLO')
DEFAULT_COLOR_PATH = os.path.join(temp_dir, 'test_data_YOLO/888_color.png')
DEFAULT_DEPTH_PATH = os.path.join(temp_dir, 'test_data_YOLO/888_depth.png')

# ====================== 新增：标签队列（供外部注入） ======================
# 外部模块可调用 set_label_queue([...]) / push_label("red_bull") 来设置
_label_queue: list = ["red_bull"]

def set_label_queue(labels):
    """一次性设置要抓取的标签序列（列表/可迭代）。"""
    global _label_queue
    if labels is None:
        _label_queue = []
        return
    _label_queue = [str(x) for x in labels if str(x).strip()]

def push_label(label):
    """追加单个标签到队列尾部。"""
    global _label_queue
    lab = str(label).strip()
    if lab:
        _label_queue.append(lab)

def clear_label_queue():
    """清空标签队列。"""
    global _label_queue
    _label_queue = []

# ====================== 名称归一化 & 标签查找（仅本文件使用） ======================
def _normalize_name(s: str) -> str:
    """将检测到的名称/输入标签统一到同一规范，方便匹配。"""
    if s is None:
        return ""
    s = s.strip().lower()
    s = s.replace('-', '_').replace(' ', '_')
    s = re.sub(r'[^a-z0-9_]+', '', s)  # 只保留字母数字下划线
    return s

# 可按需增补的别名映射（不会影响原模型输出）
NAME_ALIASES = {
    '百事可乐': 'coke',
    '红牛': 'red_bull',
    '矿泉水': 'mineral_water',
    '营养快线': 'Nutri_express',
    '纯牛奶': 'Milk',
    'AD钙奶':'Ad_calcium_milk'
}

def resolve_label_alias(label: str) -> str:
    """把中文或别名映射到模型输出名称。"""
    key = _normalize_name(label)
    return NAME_ALIASES.get(key, key)

def find_target_index_by_label(label: str, targets: list) -> int:
    """
    给定标签，返回 targets 中的编号（index）。
    - 先精确匹配 name 规范化后相等；
    - 如果多个同名，选置信度最高的；
    - 若精确没找到，做包含式模糊匹配（例如 'coke' 能匹配到 'diet_coke'）。
    - 找不到返回 -1
    """
    if not label or not targets:
        return -1

    want = resolve_label_alias(label)
    want_norm = _normalize_name(want)

    candidates = []
    for i, t in enumerate(targets):
        name_raw = t.get('name', '')
        name_norm = _normalize_name(name_raw)
        conf = float(t.get('confidence', 0.0))
        candidates.append((i, name_norm, conf))

    # 1) 精确匹配
    exact = [c for c in candidates if c[1] == want_norm]
    if exact:
        exact.sort(key=lambda x: x[2], reverse=True)  # 选置信度最高
        return exact[0][0]

    # 2) 模糊匹配（包含）
    fuzzy = [c for c in candidates if want_norm in c[1] or c[1] in want_norm]
    if fuzzy:
        fuzzy.sort(key=lambda x: x[2], reverse=True)
        return fuzzy[0][0]

    return -1

def find_center_most_target(targets, img_width, img_height):
    """从目标列表中找到最接近图像中心的目标"""
    if not targets:
        return None
    img_center_x, img_center_y = img_width / 2, img_height / 2

    min_dist = float('inf')
    center_most_target = None

    for target in targets:
        bbox = target.get('box', [0, 0, 0, 0])  # YOLOv8的输出可能没有box，需要确认
        if 'box' not in target:
            # 如果没有bbox信息，我们只能默认第一个是目标
            print("--- 警告: 目标缺少bbox信息，将默认选择第一个。 ---")
            return target

        center_x = (bbox[0] + bbox[2]) / 2
        center_y = (bbox[1] + bbox[3]) / 2
        dist = np.sqrt((center_x - img_center_x) ** 2 + (center_y - img_center_y) ** 2)

        if dist < min_dist:
            min_dist = dist
            center_most_target = target

    return center_most_target

# ====================== 小工具：统一“按回车确认”的行为 ======================
def ask_enter(prompt: str, auto: bool = AUTO_CONFIRM) -> bool:
    """
    交互确认：auto=True 时自动继续（打印提示但不阻塞）；auto=False 时等待回车。
    返回 True 表示继续，False 表示用户取消。
    """
    if auto:
        print(f"{prompt} [AUTO] 已自动确认并继续。")
        return True
    # 手动模式：按传统逻辑，空串继续，非空取消
    resp = input(prompt).strip()
    return resp == ""

# ====================== 主流程（保留签名与流程） ======================
def main():
    print("======= 欢迎使用连续抓取与放置系统 V5 (精定位版) =======")

    camera = Camera()
    robot = None
    placement_counter = 0

    try:
        # --- 步骤 1: 粗定位扫描（支持环境变量 AUTO_FIRST_MODE 免交互） ---
        mode_env = os.environ.get('AUTO_FIRST_MODE', None)
        if mode_env is None:
            mode = input('>>> 请输入“s”以扫描货架(拍照)，或直接按Enter键使用本地测试图片: ').lower()
        else:
            mode = str(mode_env).lower()
            print(f">>> [AUTO] 使用预设扫描模式: {'扫描相机(s)' if mode == 's' else '默认本地图片'}")

        if mode == 's':
            if not camera.initialize():
                return
            color_path, depth_path = camera.capture_and_save_images(CAPTURE_SAVE_DIR)
        else:
            color_path, depth_path = DEFAULT_COLOR_PATH, DEFAULT_DEPTH_PATH

        if not (color_path and depth_path):
            print("--- 未能获取有效的图像路径，程序终止。 ---")
            return

        analyzer = VisionAnalyzer(model_path=YOLO_MODEL_PATH)
        color_image = cv2.imread(color_path)
        depth_image = cv2.imread(depth_path, cv2.IMREAD_UNCHANGED)
        all_targets_coarse = get_all_targets(analyzer, color_image, depth_image)
        if not all_targets_coarse:
            print("--- 粗定位扫描未能检测到任何物体。 ---")
            return

        # --- 步骤 2: 初始化机器人 & 进入主循环 ---
        robot = RobotController("192.168.1.18", 8080)

        global _label_queue
        while all_targets_coarse:
            print("\n==================== 新的抓放循环 ====================")
            print("--- 当前剩余可抓取目标 (粗定位): ---")
            for i, target in enumerate(all_targets_coarse):
                print(f"  [{i}] {target['name']} (Conf: {target['confidence']:.2f})")

            selected_target_coarse = None
            choice = None

            # 1) 若队列有标签，则优先自动定位编号
            auto_label_in_use = None
            if _label_queue:
                auto_label_in_use = _label_queue[0]
                idx = find_target_index_by_label(auto_label_in_use, all_targets_coarse)
                if idx >= 0:
                    choice = idx
                    selected_target_coarse = all_targets_coarse[choice]
                    print(f"\n>>> 已按标签队列自动选择: '{auto_label_in_use}' -> 编号 [{choice}] {selected_target_coarse['name']}")
                    # 命中后消费此标签
                    _label_queue.pop(0)
                else:
                    print(f"\n!!! 队列标签 '{auto_label_in_use}' 未在列表中匹配到目标，将回退人工输入（该标签保留在队列首位）。")

            # 2) 未选中时，回退人工输入（支持数字或直接输入标签）
            if selected_target_coarse is None:
                try:
                    choice_str = input("\n>>> 请输入您想抓取的物体编号 或 直接输入标签 (输入 'q' 退出): ").strip().lower()
                    if choice_str == 'q':
                        break
                    if not choice_str.isdigit():
                        idx = find_target_index_by_label(choice_str, all_targets_coarse)
                        if idx < 0:
                            print("--- 未匹配到该标签，请重试。 ---")
                            continue
                        choice = idx
                    else:
                        choice = int(choice_str)

                    selected_target_coarse = all_targets_coarse[choice]
                except (ValueError, IndexError):
                    print("--- 无效输入，请重新选择。 ---")
                    continue

            # --- 步骤 3: 转身对准（自动确认） ---
            touch_pose_coarse, _ = robot.calculate_target_poses(selected_target_coarse['coords_3d'])
            if not touch_pose_coarse:
                print("--- 计算粗略位姿失败。 ---")
                continue

            # 这里传 auto_confirm=True，避免在 robot_controller 内再要你确认
            if not robot.orient_base_towards_world_coords(touch_pose_coarse[:3], auto_confirm=True):
                print("--- 基座旋转失败或取消。 ---")
                continue

            # --- 步骤 4: 二次扫描精定位 ---
            print("\n--- 对准完成，开始进行第二次精确扫描... ---")
            if not camera.is_initialized:
                camera.initialize()
            color_path_fine, depth_path_fine = camera.capture_and_save_images(CAPTURE_SAVE_DIR)
            if not (color_path_fine and depth_path_fine):
                print("--- 精定位扫描失败。 ---")
                continue

            fine_color_img = cv2.imread(color_path_fine)
            fine_depth_img = cv2.imread(depth_path_fine, cv2.IMREAD_UNCHANGED)
            all_targets_fine = get_all_targets(analyzer, fine_color_img, fine_depth_img)
            if not all_targets_fine:
                print("--- 精定位扫描未能检测到任何物体。 ---")
                continue

            # 自动选择最接近中心的目标作为最终目标
            h, w, _ = fine_color_img.shape
            final_target = find_center_most_target(all_targets_fine, w, h)
            if not final_target:
                print("--- 精定位扫描无法确定中心目标。 ---")
                continue
            print(f"--- 精定位完成，最终目标锁定: {final_target['name']} ---")

            # --- 步骤 5: 执行最终抓取（全部自动确认） ---
            touch_pose_final, retract_pose_final = robot.calculate_target_poses(final_target['coords_3d'])
            if not touch_pose_final:
                print("--- 计算最终位姿失败。 ---")
                continue

            print("\n--- 开始执行最终抓取动作序列 ---")
            if not ask_enter("确认 (1/4) 打开夹爪? (回车执行): "):
                continue
            robot.set_gripper(1.0)

            if not ask_enter("确认 (2/4) 移动到预抓取点? (回车执行): "):
                continue
            robot.move_to_pose(retract_pose_final)

            if not ask_enter("确认 (3/4) 移动到接触点? (回车执行): "):
                continue
            robot.move_to_pose(touch_pose_final, speed=20)

            if not ask_enter("确认 (4/4) 关闭夹爪并后撤? (回车执行): "):
                continue
            robot.set_gripper(0.2, wait=True)
            time.sleep(1)
            robot.move_to_pose(retract_pose_final)
            time.sleep(1)

            robot.go_home()

            # --- 步骤 6: 放置（自动确认放置） ---
            if ask_enter(f"确认将物体放置在 [位置 {placement_counter % 3 + 1}]? (回车执行): "):
                robot.place_object(placement_counter)
            robot.go_home()

            # 从粗定位列表移除本次选择目标
            all_targets_coarse.pop(choice)
            placement_counter += 1

        print("\n======= 所有目标已处理完毕! =======")

    except Exception as e:
        print(f"\n❌ 程序执行过程中发生严重错误: {e}")
    finally:
        try:
            if hasattr(camera, 'is_initialized') and camera.is_initialized:
                camera.shutdown()
        except Exception:
            pass
        print("\n--- 程序退出。 ---")

# ====================== 对外入口（供其它模块直接调用） ======================
def grab_one(label: str, use_camera: bool = False):
    """
    外部模块入口：抓取单个标签。
    - label: 如 'red_bull' / 'Coke' / '红牛'
    - use_camera: True=用相机拍照；False=使用默认测试图
    用法:
        import main_workflow
        main_workflow.grab_one('red_bull', use_camera=True)
    """
    # 放入队列
    clear_label_queue()
    push_label(label)

    # 设置第一步是否扫描
    os.environ['AUTO_FIRST_MODE'] = 's' if use_camera else ''

    # 开启全自动确认
    global AUTO_CONFIRM
    AUTO_CONFIRM = True

    # 运行主流程
    main()

def grab_labels(labels, use_camera: bool = False):
    """
    外部模块入口：按顺序抓取多个标签。
    用法:
        main_workflow.grab_labels(['red_bull','coke'], use_camera=True)
    """
    clear_label_queue()
    set_label_queue(labels)

    os.environ['AUTO_FIRST_MODE'] = 's' if use_camera else ''
    global AUTO_CONFIRM
    AUTO_CONFIRM = True

    main()

def run_workflow_with_queue(labels=None, use_camera: bool = False, auto_confirm: bool = True):
    """
    更通用的入口：可控是否自动确认。
    用法:
        main_workflow.run_workflow_with_queue(labels=['red_bull','coke'], use_camera=False, auto_confirm=True)
    """
    clear_label_queue()
    if labels:
        set_label_queue(labels)

    os.environ['AUTO_FIRST_MODE'] = 's' if use_camera else ''
    global AUTO_CONFIRM
    AUTO_CONFIRM = bool(auto_confirm)

    main()

if __name__ == '__main__':
    main()