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
import time
import numpy as np
import re
from typing import List
from dataclasses import dataclass
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
from references.robot_controller import RobotController
from references.camera_handler import Camera  
from references.yolo_model import get_all_targets, VisionAnalyzer

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


@dataclass
class Pose:
    name: str
    row: str
    x: float
    y: float
    z: float
    roll: float
    pitch: float
    yaw: float


# 新一排（从左往右 1–30）
ROW1: List[Pose] = [
    Pose("新一排-左 1-1", "新一排", -0.149, 0.297, 0.621, 0.029, 1.345, 2.068),
    Pose("新一排-左 1-2", "新一排", -0.140, 0.298, 0.617, -0.158, 1.321, 1.856),
    Pose("新一排-左 1-3", "新一排", -0.128, 0.295, 0.610, -0.016, 1.226, 1.962),
    Pose("新一排-左 1-4", "新一排", -0.121, 0.296, 0.608, -0.017, 1.237, 1.939),
    Pose("新一排-左 1-5", "新一排", -0.112, 0.294, 0.608, -0.023, 1.254, 1.913),
    Pose("新一排-左 1-6", "新一排", -0.099, 0.294, 0.605, -0.025, 1.259, 1.870),
    Pose("新一排-左 1-7", "新一排", -0.090, 0.291, 0.606, -0.031, 1.274, 1.838),
    Pose("新一排-左 1-8", "新一排", -0.079, 0.294, 0.606, -0.033, 1.274, 1.800),
    Pose("新一排-左 1-9", "新一排", -0.064, 0.292, 0.599,  0.063, 1.251, 1.849),
    Pose("新一排-左 1-10", "新一排", -0.053, 0.290, 0.601, 0.052, 1.244, 1.806),
    Pose("新一排-左 1-11", "新一排", -0.041, 0.293, 0.603, -0.003, 1.280, 1.710),
    Pose("新一排-左 1-12", "新一排", -0.029, 0.290, 0.606, -0.004, 1.266, 1.667),
    Pose("新一排-左 1-13", "新一排", -0.013, 0.289, 0.600, -0.011, 1.266, 1.605),
    Pose("新一排-左 1-14", "新一排",  0.005, 0.284, 0.600,  0.058, 1.243, 1.612),
    Pose("新一排-左 1-15", "新一排",  0.020, 0.288, 0.604,  0.055, 1.257, 1.560),
    Pose("新一排-左 1-16", "新一排",  0.035, 0.288, 0.603,  0.056, 1.281, 1.510),
    Pose("新一排-左 1-17", "新一排",  0.052, 0.293, 0.608,  0.234, 1.276, 1.642),
    Pose("新一排-左 1-18", "新一排",  0.062, 0.295, 0.609,  0.241, 1.289, 1.620),
    Pose("新一排-左 1-19", "新一排",  0.074, 0.295, 0.609,  0.238, 1.280, 1.578),
    Pose("新一排-左 1-20", "新一排",  0.089, 0.292, 0.605,  0.526, 1.277, 1.828),
    Pose("新一排-左 1-21", "新一排",  0.097, 0.288, 0.609,  0.354, 1.303, 1.621),
    Pose("新一排-左 1-22", "新一排",  0.103, 0.293, 0.612,  0.161, 1.323, 1.407),
    Pose("新一排-左 1-23", "新一排",  0.106, 0.296, 0.615,  0.398, 1.324, 1.649),
    Pose("新一排-左 1-24", "新一排",  0.114, 0.295, 0.616,  0.382, 1.315, 1.608),
    Pose("新一排-左 1-25", "新一排",  0.128, 0.301, 0.609,  0.467, 1.281, 1.661),
    Pose("新一排-左 1-26", "新一排",  0.142, 0.308, 0.605,  0.193, 1.286, 1.343),
    Pose("新一排-左 1-27", "新一排",  0.153, 0.304, 0.602,  0.451, 1.275, 1.578),
    Pose("新一排-左 1-28", "新一排",  0.161, 0.305, 0.607,  0.199, 1.299, 1.296),
    Pose("新一排-左 1-29", "新一排",  0.177, 0.314, 0.602,  0.182, 1.263, 1.249),
    Pose("新一排-左 1-30", "新一排",  0.192, 0.318, 0.606,  0.176, 1.254, 1.213),

]

# -------- 第二排 --------
ROW2: List[Pose] = [
    Pose("第二排-左 2-2",  "第二排", -0.147, 0.300, 0.402,  2.842, 1.381, -1.434),
    Pose("第二排-左 2-3",  "第二排", -0.139, 0.304, 0.407,  2.829, 1.389, -1.464),
    Pose("第二排-左 2-4",  "第二排", -0.132, 0.302, 0.403,  2.754, 1.427, -1.576),
    Pose("第二排-左 2-4",  "第二排", -0.125, 0.298, 0.400,  2.754, 1.427, -1.576),
    Pose("第二排-左 2-5",  "第二排", -0.115, 0.301, 0.399,  2.780, 1.419, -1.581),
    Pose("第二排-左 2-6",  "第二排", -0.105, 0.302, 0.397,  2.811, 1.404, -1.581),
    Pose("第二排-左 2-7",  "第二排", -0.094, 0.297, 0.399,  2.814, 1.416, -1.604),
    Pose("第二排-左 2-7",  "第二排", -0.084, 0.294, 0.401,  2.814, 1.416, -1.604),
    Pose("第二排-左 2-8",  "第二排", -0.077, 0.293, 0.402,  2.791, 1.425, -1.676),
    Pose("第二排-左 2-9",  "第二排", -0.066, 0.298, 0.406,  2.847, 1.395, -1.659),
    Pose("第二排-左 2-10", "第二排", -0.051, 0.294, 0.395,  2.848, 1.400, -1.704),
    Pose("第二排-左 2-11", "第二排", -0.042, 0.296, 0.396,  2.856, 1.394, -1.728),
    Pose("第二排-左 2-12", "第二排", -0.029, 0.297, 0.396,  2.871, 1.396, -1.757),
    Pose("第二排-左 2-13", "第二排", -0.017, 0.296, 0.399,  2.892, 1.379, -1.772),
    Pose("第二排-左 2-14", "第二排",  0.008, 0.286, 0.399,  2.912, 1.362, -1.836),
    Pose("第二排-左 2-15", "第二排",  0.020, 0.287, 0.400,  2.904, 1.371, -1.885),
    Pose("第二排-左 2-16", "第二排",  0.030, 0.286, 0.398,  3.082, 1.356, -1.738),
    Pose("第二排-左 2-17", "第二排",  0.040, 0.286, 0.402,  3.078, 1.368, -1.777),
    Pose("第二排-左 2-18", "第二排",  0.044, 0.287, 0.407,  3.071, 1.391, -1.799),
    Pose("第二排-左 2-19", "第二排",  0.052, 0.285, 0.408,  3.070, 1.393, -1.828),
    Pose("第二排-左 2-20", "第二排",  0.062, 0.288, 0.405,  3.068, 1.407, -1.862),
    Pose("第二排-左 2-21", "第二排",  0.071, 0.300, 0.402, -2.990, 1.382, -1.652),
    Pose("第二排-左 2-22", "第二排",  0.085, 0.295, 0.405,  3.072, 1.398, -1.926),
    Pose("第二排-左 2-23", "第二排",  0.089, 0.297, 0.405,  3.150, 1.391, -1.860),
    Pose("第二排-左 2-24", "第二排",  0.095, 0.297, 0.402,  2.896, 1.377, -2.136),
    Pose("第二排-左 2-25", "第二排",  0.102, 0.296, 0.402,  3.052, 1.387, -1.998),
    Pose("第二排-左 2-26", "第二排",  0.116, 0.297, 0.399,  2.844, 1.398, -2.253),
    Pose("第二排-左 2-27", "第二排",  0.128, 0.296, 0.399,  2.593, 1.336, -2.546),
    Pose("第二排-左 2-28", "第二排",  0.138, 0.300, 0.399, -2.987, 1.377, -1.846),
    Pose("第二排-左 2-29", "第二排",  0.149, 0.305, 0.402, -2.698, 1.367, -1.576),
    Pose("第二排-左 2-30", "第二排",  0.154, 0.310, 0.404, -3.037, 1.427, -1.926),
    Pose("第二排-左 2-31", "第二排",  0.160, 0.313, 0.404,  2.770, 1.422, -2.420),
    Pose("第二排-左 2-32", "第二排",  0.174, 0.317, 0.396,  2.869, 1.404, -2.349),
    Pose("第二排-左 2-33", "第二排",  0.178, 0.310, 0.402,  2.375, 1.369, -2.869),
    Pose("第二排-左 2-34", "第二排",  0.183, 0.315, 0.403, -2.622, 1.335, -1.566),
    Pose("第二排-左 2-35", "第二排",  0.192, 0.315, 0.408, -2.820, 1.386, -1.791),
]

""""//原始数据1
# -------- 第一排 --------
ROW1: List[Pose] = [
    Pose("第一排-左1-1", "第一排", -0.128, 0.276, 0.617, -0.399, 1.432, 1.590),

    Pose("第一排-左1-2", "第一排", -0.118, 0.276, 0.617, -0.399, 1.432, 1.590),
    Pose("第一排-左1-3", "第一排", -0.102, 0.267, 0.614,  0.287, 1.352, 2.239),

    Pose("第一排-左2-1", "第一排", -0.082, 0.267, 0.614,  0.287, 1.352, 2.239),
    Pose("第一排-左2-2", "第一排", -0.062, 0.267, 0.614,  0.287, 1.352, 2.239),
    Pose("第一排-左2-3", "第一排", -0.042, 0.267, 0.614,  0.287, 1.352, 2.239),
    Pose("第一排-左2-4", "第一排", -0.036, 0.276, 0.627,  0.739, 1.406, 2.423),
    Pose("第一排-左2-5", "第一排", -0.012, 0.269, 0.614,  0.080, 1.516, 1.798),
    Pose("第一排-左2-6", "第一排",  0.012, 0.269, 0.614,  0.080, 1.516, 1.798),
    Pose("第一排-左2-7", "第一排",  0.032, 0.269, 0.614,  0.080, 1.516, 1.798),

    Pose("第一排-左3-1", "第一排",  0.044, 0.288, 0.622, -0.261, 1.507, 1.154),
    Pose("第一排-左3-2", "第一排",  0.060, 0.274, 0.626,  0.204, 1.449, 1.530),
    Pose("第一排-左3-3", "第一排",  0.080, 0.274, 0.626,  0.204, 1.449, 1.530),
    Pose("第一排-左3-4", "第一排",  0.100, 0.274, 0.626,  0.204, 1.449, 1.530),
    Pose("第一排-左3-5", "第一排",  0.131, 0.308, 0.587, -0.007, 1.277, 1.154),
    Pose("第一排-左3-6", "第一排",  0.135, 0.308, 0.587, -0.007, 1.277, 1.154),

    Pose("第一排-左4-1", "第一排",  0.142, 0.289, 0.618,  0.060, 1.403, 1.151),
    Pose("第一排-左4-2", "第一排",  0.171, 0.291, 0.614,  0.318, 1.441, 1.335),
    Pose("第一排-左4-3", "第一排",  0.198, 0.302, 0.594,  0.155, 1.266, 1.154),
]

# -------- 第二排 --------
ROW2: List[Pose] = [
    Pose("第二排-左1-1", "第二排", -0.148, 0.271, 0.390,  2.782, 1.455, -1.442),
    Pose("第二排-左1-2", "第二排", -0.145, 0.273, 0.376,  2.410, 1.517, -1.827),
    Pose("第二排-左1-3", "第二排", -0.125, 0.273, 0.376,  2.410, 1.517, -1.827),
    Pose("第二排-左1-4", "第二排", -0.105, 0.273, 0.376,  2.410, 1.517, -1.827),
    Pose("第二排-左1-5", "第二排", -0.079, 0.317, 0.396,  3.116, 1.317, -1.353),

    Pose("第二排-左2-1", "第二排", -0.057, 0.273, 0.373, -3.109, 1.508, -1.331),
    Pose("第二排-左2-2", "第二排", -0.041, 0.266, 0.385,  1.757, 1.509, -2.818),
    Pose("第二排-左2-3", "第二排", -0.021, 0.266, 0.385,  1.757, 1.509, -2.818),
    Pose("第二排-左2-4", "第二排", -0.003, 0.281, 0.381,  2.951, 1.377, -1.757),
    Pose("第二排-左2-5", "第二排",  0.023, 0.281, 0.381,  2.951, 1.377, -1.757),
    Pose("第二排-左2-6", "第二排",  0.043, 0.281, 0.381,  2.951, 1.377, -1.757),

    Pose("第二排-左3-1", "第二排",  0.057, 0.267, 0.369,  3.060, 1.441, -1.8643),
    Pose("第二排-左3-2", "第二排",  0.061, 0.283, 0.389, -3.113, 1.408, -1.753),
    Pose("第二排-左3-3", "第二排",  0.081, 0.283, 0.389, -3.113, 1.408, -1.753),
    Pose("第二排-左3-4", "第二排",  0.097, 0.285, 0.379,  2.904, 1.394, -2.148),
    Pose("第二排-左3-5", "第二排",  0.110, 0.299, 0.405,  2.840, 1.346, -2.227),
    Pose("第二排-左3-6", "第二排",  0.137, 0.285, 0.379,  2.904, 1.394, -2.148),
    Pose("第二排-左3-7", "第二排",  0.157, 0.285, 0.379,  2.904, 1.394, -2.148),

    Pose("第二排-左4-1", "第二排",  0.166, 0.289, 0.386,  2.524, 1.427, -2.678),
    Pose("第二排-左4-2", "第二排",  0.179, 0.283, 0.381,  2.405, 1.494, -2.828),
    Pose("第二排-左4-3", "第二排",  0.196, 0.305, 0.399,  2.875, 1.389, -2.421),
]
造出来的数据集：
# -------- 第一排 --------
ROW1: List[Pose] = [
    Pose("第一排-左1-1", "第一排", -0.130, 0.265, 0.612, -0.399, 1.432, 1.590),
    Pose("第一排-左1-2", "第一排", -0.120, 0.265, 0.612, -0.399, 1.432, 1.590),
    Pose("第一排-左1-3", "第一排", -0.110, 0.265, 0.612,  0.287, 1.352, 2.239),

    Pose("第一排-左2-1", "第一排", -0.100, 0.265, 0.612,  0.287, 1.352, 2.239),
    Pose("第一排-左2-2", "第一排", -0.090, 0.265, 0.612,  0.287, 1.352, 2.239),
    Pose("第一排-左2-3", "第一排", -0.080, 0.265, 0.612,  0.287, 1.352, 2.239),
    Pose("第一排-左2-4", "第一排", -0.070, 0.265, 0.612,  0.739, 1.406, 2.423),
    Pose("第一排-左2-5", "第一排", -0.060, 0.265, 0.612,  0.080, 1.516, 1.798),
    Pose("第一排-左2-6", "第一排", -0.050, 0.265, 0.612,  0.080, 1.516, 1.798),
    Pose("第一排-左2-7", "第一排", -0.040, 0.265, 0.612,  0.080, 1.516, 1.798),

    Pose("第一排-左3-1", "第一排", -0.030, 0.265, 0.612, -0.261, 1.507, 1.154),
    Pose("第一排-左3-2", "第一排", -0.020, 0.265, 0.612,  0.204, 1.449, 1.530),
    Pose("第一排-左3-3", "第一排", -0.010, 0.265, 0.612,  0.204, 1.449, 1.530),
    Pose("第一排-左3-4", "第一排",  0.000, 0.265, 0.612,  0.204, 1.449, 1.530),
    Pose("第一排-左3-5", "第一排",  0.010, 0.265, 0.612, -0.007, 1.277, 1.154),
    Pose("第一排-左3-6", "第一排",  0.020, 0.265, 0.612, -0.007, 1.277, 1.154),

    Pose("第一排-左4-1", "第一排",  0.030, 0.265, 0.612,  0.060, 1.403, 1.151),
    Pose("第一排-左4-2", "第一排",  0.040, 0.265, 0.612,  0.318, 1.441, 1.335),
    Pose("第一排-左4-3", "第一排",  0.050, 0.265, 0.612,  0.155, 1.266, 1.154),
]

# -------- 第二排 --------
ROW2: List[Pose] = [
    Pose("第二排-左1-1", "第二排", -0.150, 0.265, 0.354,  2.782, 1.455, -1.442),
    Pose("第二排-左1-2", "第二排", -0.140, 0.265, 0.354,  2.410, 1.517, -1.827),
    Pose("第二排-左1-3", "第二排", -0.130, 0.265, 0.354,  2.410, 1.517, -1.827),
    Pose("第二排-左1-4", "第二排", -0.120, 0.265, 0.354,  2.410, 1.517, -1.827),
    Pose("第二排-左1-5", "第二排", -0.110, 0.265, 0.354,  3.116, 1.317, -1.353),

    Pose("第二排-左2-1", "第二排", -0.100, 0.265, 0.354, -3.109, 1.508, -1.331),
    Pose("第二排-左2-2", "第二排", -0.090, 0.265, 0.354,  1.757, 1.509, -2.818),
    Pose("第二排-左2-3", "第二排", -0.080, 0.265, 0.354,  1.757, 1.509, -2.818),
    Pose("第二排-左2-4", "第二排", -0.070, 0.265, 0.354,  2.951, 1.377, -1.757),
    Pose("第二排-左2-5", "第二排", -0.060, 0.265, 0.354,  2.951, 1.377, -1.757),
    Pose("第二排-左2-6", "第二排", -0.050, 0.265, 0.354,  2.951, 1.377, -1.757),

    Pose("第二排-左3-1", "第二排", -0.040, 0.265, 0.354,  3.060, 1.441, -1.8643),
    Pose("第二排-左3-2", "第二排", -0.030, 0.265, 0.354, -3.113, 1.408, -1.753),
    Pose("第二排-左3-3", "第二排", -0.020, 0.265, 0.354, -3.113, 1.408, -1.753),
    Pose("第二排-左3-4", "第二排", -0.010, 0.265, 0.354,  2.904, 1.394, -2.148),
    Pose("第二排-左3-5", "第二排",  0.000, 0.265, 0.354,  2.840, 1.346, -2.227),
    Pose("第二排-左3-6", "第二排",  0.010, 0.265, 0.354,  2.904, 1.394, -2.148),
    Pose("第二排-左3-7", "第二排",  0.020, 0.265, 0.354,  2.904, 1.394, -2.148),

    Pose("第二排-左4-1", "第二排",  0.030, 0.265, 0.354,  2.524, 1.427, -2.678),
    Pose("第二排-左4-2", "第二排",  0.040, 0.265, 0.354,  2.405, 1.494, -2.828),
    Pose("第二排-左4-3", "第二排",  0.050, 0.265, 0.354,  2.875, 1.389, -2.421),
]
"""

ALL_POSES: List[Pose] = ROW1 + ROW2  # 目前未直接使用，但保留以便扩展/调试

# ---- 将 Pose 对象转为 [x,y,z,roll,pitch,yaw] ----


def _as_pose6d(p):
    """把 Pose对象 或 list/tuple 转成 [x,y,z,roll,pitch,yaw]。不符合规范时返回 None。"""
    if hasattr(p, 'x') and hasattr(p, 'y') and hasattr(p, 'z') and hasattr(p, 'roll') and hasattr(p,
                                                                                                  'pitch') and hasattr(
            p, 'yaw'):
        return [float(p.x), float(p.y), float(p.z), float(p.roll), float(p.pitch), float(p.yaw)]  # 注意：是 p.yaw
    if isinstance(p, (list, tuple)) and len(p) >= 6:
        return [float(p[0]), float(p[1]), float(p[2]), float(p[3]), float(p[4]), float(p[5])]
    return None


def _poses_to_matrix(poses: List[Pose]) -> np.ndarray:
    """将 Pose 列表转为矩阵 (N,6): [x,y,z,roll,pitch,yaw]。若为空返回 (0,6)。"""
    if not poses:
        return np.zeros((0, 6), dtype=float)
    rows = []
    for p in poses:
        v = _as_pose6d(p)
        if v is not None:
            rows.append(v)
    if not rows:
        return np.zeros((0, 6), dtype=float)
    return np.asarray(rows, dtype=float)


def pick_nearest_pose_lex(target_pose6d,yolopose,Image_match):
    """
    规则：先在 ROW1 与 ROW2 各自内部找“离目标 tz 最近的 z”，选更接近的一排；
          再在该排里仅比较 x，选离目标 tx 最近的位姿；
    返回 (best_pose_list6d, diffs)，其中 diffs = (dz, dx, dy) 用于日志参考。
    """
    a = 0.0009812949
    b = -0.30355394
    row1_mat = _poses_to_matrix(ROW1)  # (N1,6)
    row2_mat = _poses_to_matrix(ROW2)  # (N2,6)

    if Image_match is True:
        yolo_x = (yolopose[0]+yolopose[2])/2
        yolo_y = (yolopose[1]+yolopose[3])/2
        x = a * yolo_x + b
        print(f"new_caclated x = yolox a+b: {x}")
        print(f"yolo_y: {yolo_y}")
        print(f"yolo_x : {yolo_x}")
        if 0 < yolo_y < 210:
            idx = int(np.argmin(np.abs(row1_mat[:, 0] - x)))
            best_vec = row1_mat[idx]
            print(f"best_vec:{best_vec}")

        elif yolo_y > 210:
            idx = int(np.argmin(np.abs(row2_mat[:, 0] - x)))
            best_vec = row2_mat[idx]
        return  [float(v) for v in best_vec.tolist()], 0

    if not target_pose6d or len(target_pose6d) < 3:
        return None, None

    tx, ty, tz = float(target_pose6d[0]), float(target_pose6d[1]), float(target_pose6d[2])

    row1_mat = _poses_to_matrix(ROW1)  # (N1,6)
    row2_mat = _poses_to_matrix(ROW2)  # (N2,6)
    if row1_mat.shape[0] == 0 and row2_mat.shape[0] == 0:
        return None, None

    def min_abs_z_diff(mat: np.ndarray) -> float:
        if mat.shape[0] == 0:
            return float('inf')
        return float(np.min(np.abs(mat[:, 2] - tz)))

    zdiff_row1 = min_abs_z_diff(row1_mat)
    zdiff_row2 = min_abs_z_diff(row2_mat)

    if zdiff_row1 <= zdiff_row2:
        selected = row1_mat
        selected_row_name = "ROW1"
    else:
        selected = row2_mat
        selected_row_name = "ROW2"

    if selected.shape[0] == 0:
        # 兜底：如果选中的那排为空，换另一排
        selected = row1_mat if selected_row_name == "ROW2" else row2_mat
        selected_row_name = "ROW1" if selected_row_name == "ROW2" else "ROW2"
        if selected.shape[0] == 0:
            return None, None

    # 在选定一排里仅比较 x 与目标 tx 的距离
    idx = int(np.argmin(np.abs(selected[:, 0] - tx)))
    best_vec = selected[idx]

    bx, by, bz = float(best_vec[0]), float(best_vec[1]), float(best_vec[2])
    diffs = (bz - tz, bx - tx, by - ty)  # (dz, dx, dy)

    print(
        f"--- 位姿库选择：先比Z选 {selected_row_name}，再比X选第 {idx} 项。Δz={diffs[0]:+.3f}, Δx={diffs[1]:+.3f}, Δy={diffs[2]:+.3f}")
    return [float(v) for v in best_vec.tolist()], diffs




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