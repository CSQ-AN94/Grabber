#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""微调一个多类别商品 YOLO 模型（在训练机上跑，不是机器人/Mac 上跑体检那套）。

从公开 COCO 预训练权重（默认 yolov8n.pt）做迁移学习，不基于现有部署的
`intelligence/yolo_models/8_17.pt` 继续训练——新类别列表的检测头维度/顺序
跟旧模型对不上，从干净的预训练骨干开始比硬接旧检测头更简单可靠。

跑之前需要先用 `scripts/prepare_yolo_dataset.py` 产出 `data.yaml`。
"""

from __future__ import annotations

import argparse
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--data",
        required=True,
        help="prepare_yolo_dataset.py 产出的 data.yaml 路径",
    )
    parser.add_argument(
        "--base-model",
        default="yolov8n.pt",
        help="起始预训练权重，默认 yolov8n.pt（ultralytics 会自动下载）",
    )
    parser.add_argument("--epochs", type=int, default=100)
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--batch", type=int, default=16)
    parser.add_argument(
        "--device",
        default=None,
        help="cuda:0 / mps / cpu；不给则让 ultralytics 自动选",
    )
    parser.add_argument(
        "--project",
        default="intelligence/data/product_yolo_runs",
        help="训练输出根目录（ultralytics 的 project/name 结构）",
    )
    parser.add_argument("--name", default="product_yolo")
    args = parser.parse_args()

    data_path = Path(args.data)
    if not data_path.is_file():
        print(f"错误: data.yaml 不存在: {data_path}")
        return 1

    from ultralytics import YOLO

    model = YOLO(args.base_model)
    train_kwargs = dict(
        data=str(data_path),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        project=args.project,
        name=args.name,
    )
    if args.device:
        train_kwargs["device"] = args.device
    results = model.train(**train_kwargs)

    save_dir = Path(results.save_dir)
    best = save_dir / "weights" / "best.pt"
    print(f"\n训练完成。最优权重: {best}")
    metrics = getattr(results, "results_dict", {})
    map50 = metrics.get("metrics/mAP50(B)")
    if map50 is not None:
        print(f"mAP50: {map50:.4f}")
    print(
        "这个 .pt 还没有替换线上的 intelligence/yolo_models/8_17.pt——先用 "
        "scripts/verify_yolo_model.py 人工确认识别效果，满意后再手动替换并"
        "更新 config.yaml 的 vision.model_path"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
