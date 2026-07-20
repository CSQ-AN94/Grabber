#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按商品分类采集训练图像（机器人上跑，人工看着拍）。

`scripts/collect_images.py` 的按商品扩展：那个脚本每次运行把图片全丢进
一个目录，要训练多类别检测模型需要知道"这张图是哪个商品"，所以这里改成
一次运行只拍一个商品（--label），自动分文件夹存，不用人工事后再分类一次
（那样容易分错/漏分）。

已知薄弱场景（见 docs/handoff/bottle_grasp_known_risks.md"标签背对相机
置信度骤降"那条教训）：同一商品要在正面/侧面/背面/倾斜多个朝向、不同
距离、不同光照下都拍，不能原地不动连拍——那样训练出来的模型只认得一个
姿态。
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensors.camera_thread import CameraThread
from utils.config import load_config


class ProductImageCollector:
    """单个商品类别的图像采集器：可视化画面，定期/手动存图到该类别目录。"""

    def __init__(
        self,
        *,
        label: str,
        camera_serial: str,
        save_interval: float,
        output_root: str,
    ):
        self.label = label
        self.save_interval = save_interval
        self.output_dir = os.path.join(output_root, label)
        os.makedirs(self.output_dir, exist_ok=True)
        self.image_count = len(
            [f for f in os.listdir(self.output_dir) if f.lower().endswith(".jpg")]
        )
        print(f"类别 '{label}' 已有 {self.image_count} 张图片，继续追加采集")

        self.camera_thread = CameraThread(serial=camera_serial, strict_serial=True)
        if not self.camera_thread.initialization_successful:
            raise RuntimeError(
                f"相机初始化失败: {self.camera_thread.initialization_error}"
            )
        self.camera_thread.start()
        print("等待相机稳定...")
        time.sleep(3)
        color, _ = self.camera_thread.get_latest_frames()
        if color is None:
            raise RuntimeError("相机初始化失败：无法获取彩色图像")

    def _save_image(self, image: np.ndarray) -> None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"{self.label}_{timestamp}_{self.image_count:04d}.jpg"
        filepath = os.path.join(self.output_dir, filename)
        if cv2.imwrite(filepath, image):
            print(f"已保存: {filepath}")
            self.image_count += 1
        else:
            print(f"保存失败: {filepath}")

    def run(self) -> None:
        print(f"开始采集类别 '{self.label}'")
        print(f"保存间隔: {self.save_interval}秒（0 表示只手动保存）")
        print("拍摄提示：转动商品覆盖正面/侧面/背面/倾斜角度，变换距离和光照，"
              "不要原地不动连拍")
        print("按 's' 手动保存一张，按 'q' 结束这个类别")
        print("-" * 50)

        last_save_time = time.time()
        try:
            while True:
                color, _ = self.camera_thread.get_latest_frames()
                if color is not None:
                    display = color.copy()
                    cv2.putText(
                        display,
                        f"[{self.label}] saved: {self.image_count}",
                        (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (0, 255, 0),
                        2,
                    )
                    cv2.putText(
                        display,
                        "'s' save   'q' finish this label",
                        (10, 60),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (255, 255, 255),
                        1,
                    )
                    cv2.imshow("Product Image Collector", display)

                    if (
                        self.save_interval > 0
                        and time.time() - last_save_time >= self.save_interval
                    ):
                        self._save_image(color)
                        last_save_time = time.time()

                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("s") and color is not None:
                    self._save_image(color)
                    last_save_time = time.time()
                time.sleep(0.03)
        except KeyboardInterrupt:
            print("\n用户中断")
        finally:
            self._cleanup()

    def _cleanup(self) -> None:
        cv2.destroyAllWindows()
        if self.camera_thread.is_alive():
            self.camera_thread.stop()
            self.camera_thread.join(timeout=5)
        print(f"类别 '{self.label}' 采集完成，共 {self.image_count} 张图片")
        if self.image_count < 150:
            print(
                f"提示：建议每类至少150-200张覆盖多角度，当前 {self.image_count} 张"
                "偏少，训练效果可能不理想"
            )
        print(f"保存目录: {os.path.abspath(self.output_dir)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="按商品分类采集YOLO训练图像")
    parser.add_argument(
        "--label",
        required=True,
        help=(
            "商品类别名，建议用后续 --target-product 要传的英文/拼音 slug"
            "（比如 coke_bottle），避免中文类名的编码麻烦"
        ),
    )
    parser.add_argument(
        "--camera",
        choices=("head", "right_wrist", "left_wrist"),
        default="head",
        help="用哪个相机采集，默认头部相机",
    )
    parser.add_argument("--interval", type=float, default=2.0, help="自动保存间隔（秒），0表示只手动保存")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument(
        "--output-root",
        default="intelligence/data/raw",
        help="采集图片的根目录，实际会存进 <output-root>/<label>/",
    )
    args = parser.parse_args()

    cfg = load_config(args.config)
    serial = cfg.camera.serial_for(args.camera)

    try:
        collector = ProductImageCollector(
            label=args.label,
            camera_serial=serial,
            save_interval=args.interval,
            output_root=args.output_root,
        )
        collector.run()
    except Exception as exc:
        print(f"错误: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
