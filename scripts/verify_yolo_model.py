#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""检查一个 YOLO .pt 文件的类别列表，可选对一张图跑推理画框看效果。

日常用途两个：
1. 训练完新模型后，人工确认类别名/数量对不对、挑几张真实图看看画框准不准。
2. 排查现在部署的模型（比如 intelligence/yolo_models/8_17.pt）到底还剩哪些
   类别——这就是之前口头给的那行内联命令的正式版本。
"""

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_path", help=".pt 模型文件路径")
    parser.add_argument(
        "--image", default=None, help="可选：对这张图跑一次推理"
    )
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument(
        "--output",
        default="verify_yolo_output.jpg",
        help="画框结果存到哪（仅 --image 给定时有效）",
    )
    args = parser.parse_args()

    from ultralytics import YOLO

    model = YOLO(args.model_path)
    names = list(model.names.values())
    print(f"模型: {args.model_path}")
    print(f"类别数: {len(names)}")
    print(f"类别列表: {names}")

    if args.image:
        results = model.predict(args.image, conf=args.conf, verbose=False)
        result = results[0]
        boxes = result.boxes
        print(f"\n对 {args.image} 的检测结果（conf>={args.conf}）：")
        if boxes is None or len(boxes) == 0:
            print("  没有检测到任何目标")
        else:
            for box in boxes:
                cls_id = int(box.cls[0])
                print(
                    f"  {names[cls_id]}: conf={float(box.conf[0]):.3f} "
                    f"box={box.xyxy[0].tolist()}"
                )
        result.save(filename=args.output)
        print(f"画框结果已存: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
