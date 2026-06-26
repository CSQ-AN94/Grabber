#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Direct command entrypoint for Grabber.

This bypasses Gemini and voice interaction. It keeps the runtime path simple:
initialize hardware, scan visible products, then execute a grab for the exact
product name or list index requested by the operator.
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
import traceback
from typing import Iterable, Optional

_robot_tools = None


def get_robot_tools():
    global _robot_tools
    if _robot_tools is None:
        from intelligence import robot_tools

        _robot_tools = robot_tools
    return _robot_tools


def initialize_hardware_systems():
    """Initialize vision, camera, and arm without importing or starting Gemini."""
    print("=== 初始化直接抓取硬件系统 ===")

    from intelligence.vision import VisionAnalyzer
    from sensors.camera_thread import CameraThread
    from utils.config import load_config
    from controllers.arm_controller import ArmController

    app_config = load_config()

    print("1. 初始化 YOLO 视觉分析器...")
    vision_analyzer = VisionAnalyzer(model_path=app_config.vision.model_path)
    print(f"YOLO 模型加载成功: {app_config.vision.model_path}")

    print("2. 初始化 RealSense 相机系统...")
    camera_thread = CameraThread(
        serial=app_config.camera.head_serial,
        width=app_config.camera.width,
        height=app_config.camera.height,
        fps=app_config.camera.fps,
    )
    camera_thread.start()
    print("相机线程启动成功，等待画面稳定...")
    time.sleep(3)

    color_frame, _ = camera_thread.get_latest_frames()
    if color_frame is None:
        raise RuntimeError("相机数据获取失败")
    print(f"相机数据验证成功，分辨率: {color_frame.shape}")

    print("3. 初始化 Realman 机械臂...")
    arm_controller = ArmController(app_config.connections, app_config.arm, app_config.gripper)
    if arm_controller.get_base_to_end_pose_matrix() is None:
        raise RuntimeError("机械臂状态读取失败")
    print("机械臂状态验证成功")

    robot_tools = get_robot_tools()
    robot_tools.clear_shopping_cart()
    robot_tools.set_hardware_components(vision_analyzer, camera_thread, arm_controller)
    robot_tools.init_real_hardware_mode()

    print("=== 直接抓取硬件系统初始化完成 ===")
    return camera_thread, arm_controller


def shutdown_hardware(camera_thread=None, arm_controller=None) -> None:
    """Best-effort cleanup for camera and arm resources."""
    if camera_thread is not None:
        try:
            camera_thread.stop()
            if camera_thread.is_alive():
                camera_thread.join(timeout=3)
        except Exception as exc:
            print(f"[清理] 相机关闭失败: {exc}")

    if arm_controller is not None:
        try:
            arm_controller.close()
        except Exception as exc:
            print(f"[清理] 机械臂关闭失败: {exc}")


def print_scan_result(result: dict) -> list[str]:
    """Print scan output and return the detected product names."""
    if not result.get("success"):
        print(f"扫描失败: {result.get('message') or result.get('error')}")
        return []

    objects = result.get("objects", [])
    if not objects:
        print("当前未识别到商品")
        return []

    names = []
    print("当前识别到的商品:")
    for idx, obj in enumerate(objects, start=1):
        name = str(obj.get("name", "")).strip()
        confidence = obj.get("confidence")
        box = obj.get("box")
        names.append(name)
        if confidence is None:
            print(f"  {idx}. {name}")
        else:
            print(f"  {idx}. {name}  conf={confidence:.2f}  box={box}")
    return names


def parse_grab_target(raw_text: str, last_items: Iterable[str]) -> Optional[str]:
    """Parse a deterministic command into a product name."""
    text = raw_text.strip()
    if not text:
        return None

    lower = text.lower()
    for prefix in ("grab ", "g ", "抓取", "抓 ", "拿 ", "取 "):
        if lower.startswith(prefix):
            text = text[len(prefix):].strip()
            break

    items = [item for item in last_items if item]
    if text.isdigit():
        index = int(text)
        if 1 <= index <= len(items):
            return items[index - 1]
        print(f"编号 {index} 不在当前列表范围内")
        return None

    if text in items:
        return text

    matches = [item for item in items if text in item]
    if len(matches) == 1:
        print(f"匹配到商品: {matches[0]}")
        return matches[0]
    if len(matches) > 1:
        print(f"输入 '{text}' 匹配多个商品: {', '.join(matches)}，请说完整商品名或编号")
        return None

    return text


def scan_once() -> list[str]:
    robot_tools = get_robot_tools()
    return print_scan_result(robot_tools.scan_shelf())


def grab_item(item_name: str) -> bool:
    robot_tools = get_robot_tools()
    print(f"准备抓取: {item_name}")
    result = robot_tools.execute_grab(item_name)
    print(result.get("message", result))
    return bool(result.get("success"))


def run_interactive(initial_scan: bool = True) -> int:
    camera_thread = None
    arm_controller = None
    try:
        camera_thread, arm_controller = initialize_hardware_systems()
        last_items = scan_once() if initial_scan else []

        print("\n直接命令模式")
        print("输入商品名或编号执行抓取；输入 scan 重新扫描；输入 q 退出。")

        while True:
            raw = input("\n抓取指令> ").strip()
            if not raw:
                continue
            if raw.lower() in {"q", "quit", "exit"}:
                return 0
            if raw.lower() in {"scan", "rescan", "s", "重新扫描"}:
                last_items = scan_once()
                continue

            item_name = parse_grab_target(raw, last_items)
            if item_name:
                if grab_item(item_name):
                    last_items = scan_once()

    except KeyboardInterrupt:
        print("\n用户中断，退出")
        return 130
    except Exception as exc:
        print(f"直接抓取模式失败: {exc}")
        traceback.print_exc()
        return 1
    finally:
        shutdown_hardware(camera_thread, arm_controller)

    return 0


def run_once(command: str, item_words: list[str]) -> int:
    camera_thread = None
    arm_controller = None
    try:
        camera_thread, arm_controller = initialize_hardware_systems()
        if command == "scan":
            scan_once()
            return 0

        if command == "grab":
            item_name = " ".join(item_words).strip()
            if not item_name:
                print("请指定商品名，例如: python direct_grab.py grab 红牛")
                return 2
            visible_items = scan_once()
            item_name = parse_grab_target(item_name, visible_items) or item_name
            return 0 if grab_item(item_name) else 1

        print(f"未知命令: {command}")
        return 2
    except Exception as exc:
        print(f"直接命令执行失败: {exc}")
        traceback.print_exc()
        return 1
    finally:
        shutdown_hardware(camera_thread, arm_controller)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Direct scan/grab mode without Gemini.")
    parser.add_argument(
        "command",
        nargs="?",
        choices=("scan", "grab"),
        help="scan: 只扫描商品；grab: 直接抓取指定商品；不填则进入交互模式",
    )
    parser.add_argument("item", nargs="*", help="grab 命令的商品名，例如 红牛")
    parser.add_argument("--no-initial-scan", action="store_true", help="交互模式启动时不自动扫描")
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    parser = build_parser()
    args = parser.parse_args()

    if args.command:
        return run_once(args.command, args.item)
    return run_interactive(initial_scan=not args.no_initial_scan)


if __name__ == "__main__":
    sys.exit(main())
